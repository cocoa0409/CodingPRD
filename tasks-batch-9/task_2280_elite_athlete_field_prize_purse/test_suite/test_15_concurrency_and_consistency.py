"""Cross-cutting layers: the two version guards, filtered paging, and immediate reads."""
from test_helpers import (
    ApiErrorId,
    DIRECTOR,
    FINANCE,
    LIAISON,
    api_client,
    assign_bib,
    collect_sample,
    compute_awards,
    create_invitation,
    create_verified_performance,
    enroll_draft_invitation,
    list_awards,
    make_athlete_agent_headers,
    negotiation_round_payload,
    read_edition,
    read_invitation,
    register_agent,
    register_athlete,
    respond_as_agent,
    schedule_doping_test,
    send_offer,
    set_clock,
    setup_edition_with_certified_results,
    setup_field_open_edition,
    validate_error,
    validate_paginated,
    validate_success,
    withdraw_invitation,
)

ELITE_MALE_STANDARD = {"division": "ELITE", "gender": "MALE",
                       "max_qualifying_seconds": 8_100,
                       "bib_range_start": 11, "bib_range_end": 20}
OVERALL_MALE_FIRST = {"category": "OVERALL", "gender": "MALE", "place": 1,
                      "amount_cents": 1_000_000}
OPENING_OFFER = {"appearance_fee_cents": 800_000, "air_class": "ECONOMY",
                 "hotel_nights": 3, "ground_transport": False}
AGENT_COUNTER = {"appearance_fee_cents": 1_200_000, "air_class": "BUSINESS",
                 "hotel_nights": 5, "ground_transport": True}
COMMITTEE_COUNTER = {"appearance_fee_cents": 1_000_000, "air_class": "BUSINESS",
                     "hotel_nights": 4, "ground_transport": True}


def _an_invitation_with_two_versions_in_play():
    """An `OFFERED` invitation, remembering both the version it had at creation and the
    version the offer left behind."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="OCC Invitation Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    enrolled = enroll_draft_invitation(
        scenario["edition"]["id"],
        athlete_overrides={"country_code": "KEN"},
        performance_overrides={"performance_seconds": 7_900},
    )
    scenario.update(enrolled)
    scenario["version_at_creation"] = enrolled["invitation"]["version"]
    scenario["invitation"] = send_offer(enrolled["invitation"]["id"], **OPENING_OFFER)
    scenario["version_after_the_offer"] = scenario["invitation"]["version"]
    return scenario


def test_a_negotiation_round_pinned_to_a_superseded_invitation_version_is_refused():
    """The version read at creation is already stale once the offer has been sent.

    PRD §2.7: "Appending a negotiation round to an invitation — the
    `POST /invitations/{id}/negotiation-rounds` operation of §4 — requires
    `expected_invitation_version` as a non-optional field of the request, carrying the
    client's last observed `version` of that `Invitation`." and "When
    `expected_invitation_version` does not equal the invitation's current `version`, the
    append is rejected with `ERR_STALE_INVITATION_VERSION` and HTTP 412." The offer is
    itself a write that moves the version, since sending it "increments the invitation's
    `version`" is the rule for every append and PRD §2.5 makes `version` "a
    system-managed integer that starts at 1 on creation and increases by one on every
    mutation".

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_invitation_version_on_negotiation_round
    """
    scenario = _an_invitation_with_two_versions_in_play()
    invitation_id = scenario["invitation"]["id"]
    agent_headers = make_athlete_agent_headers(scenario["agent"]["id"])
    assert scenario["version_at_creation"] < scenario["version_after_the_offer"]

    stale = api_client.create_negotiation_round(
        invitation_id,
        negotiation_round_payload(scenario["version_at_creation"], **AGENT_COUNTER),
        agent_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_INVITATION_VERSION.value, 412)

    agent_rounds, meta = validate_paginated(
        api_client.list_negotiation_rounds(invitation_id, DIRECTOR, {"side": "AGENT"})
    )
    assert meta["total_count"] == 0, "a rejected round leaves no row behind"
    assert agent_rounds == []
    assert read_invitation(invitation_id)["status"] == "OFFERED"


def test_the_accepted_version_is_consumed_by_the_write_that_used_it():
    """The value that worked one call earlier is stale for the next append, and the
    refreshed value works again.

    PRD §2.7: "A round legitimately supersedes the previous package —
    `current_appearance_fee_cents`, `current_air_class`, `current_hotel_nights` and
    `current_ground_transport` are all replaced — so a writer holding a version older
    than the invitation's current one would overwrite terms it never read. When
    `expected_invitation_version` does not equal the invitation's current `version`, the
    append is rejected with `ERR_STALE_INVITATION_VERSION` and HTTP 412." PRD §3.3 says
    each successful append "increments the invitation's `version`; and flips the status to
    the opposite side of the cycle", the cycle being "`OFFERED → COUNTERED → OFFERED`".

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_invitation_version_on_negotiation_round
    """
    scenario = _an_invitation_with_two_versions_in_play()
    invitation_id = scenario["invitation"]["id"]
    agent_headers = make_athlete_agent_headers(scenario["agent"]["id"])
    offer_version = scenario["version_after_the_offer"]

    countered = validate_success(
        api_client.create_negotiation_round(
            invitation_id,
            negotiation_round_payload(offer_version, **AGENT_COUNTER),
            agent_headers,
        ),
        201,
    )
    assert countered["side"] == "AGENT"
    assert read_invitation(invitation_id)["status"] == "COUNTERED"
    assert read_invitation(invitation_id)["version"] == offer_version + 1

    replayed = api_client.create_negotiation_round(
        invitation_id,
        negotiation_round_payload(offer_version, **COMMITTEE_COUNTER),
        DIRECTOR,
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_INVITATION_VERSION.value, 412)

    refreshed = validate_success(
        api_client.create_negotiation_round(
            invitation_id,
            negotiation_round_payload(read_invitation(invitation_id)["version"],
                                     **COMMITTEE_COUNTER),
            DIRECTOR,
        ),
        201,
    )
    assert refreshed["side"] == "COMMITTEE"
    assert read_invitation(invitation_id)["status"] == "OFFERED"

    history, meta = validate_paginated(
        api_client.list_negotiation_rounds(invitation_id, DIRECTOR)
    )
    assert meta["total_count"] == 3, "the opening offer plus the two accepted appends"
    assert [row["round_number"] for row in history] == [1, 2, 3]


def _a_certified_edition_with_two_versions_in_play():
    """A `RESULTS_CERTIFIED` edition carrying one certified finisher."""
    scenario = setup_edition_with_certified_results(
        [{"gun_seconds": 7_400, "net_seconds": 7_398,
          "athlete_overrides": {"country_code": "USA"},
          "performance_overrides": {"performance_seconds": 7_900}}],
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        race_clock="2026-11-01T09:00:00Z",
        name="OCC Edition Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=8_000_000,
        bonus_pool_cap_cents=0,
        course_record_male_seconds=7_000,
    )
    assert scenario["edition"]["status"] == "RESULTS_CERTIFIED"
    return scenario


def test_award_generation_refuses_a_version_older_than_the_live_edition():
    """A version predating the whole posture pipeline computes nothing at all.

    PRD §2.7: "Recomputing an edition's award set — the
    `POST /race-editions/{id}/compute-awards` operation of §4 — requires
    `expected_race_edition_version` as a non-optional field of the request, carrying the
    client's last observed `version` of that `RaceEdition`." and "When
    `expected_race_edition_version` does not equal the edition's current `version`, the
    recompute is rejected with `ERR_STALE_EDITION_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_edition_version_on_compute_awards
    """
    scenario = _a_certified_edition_with_two_versions_in_play()
    edition_id = scenario["edition"]["id"]

    stale = api_client.compute_awards(
        edition_id, {"expected_race_edition_version": 1}, FINANCE
    )
    validate_error(stale, ApiErrorId.ERR_STALE_EDITION_VERSION.value, 412)

    awards, meta = list_awards({"race_edition_id": edition_id})
    assert meta["total_count"] == 0, "the refused run computed nothing"
    assert awards == []


def test_a_recompute_consumes_its_version_and_supersedes_its_own_award_set():
    """The accepted version cannot be replayed, and the refreshed run leaves one live
    award.

    PRD §2.7: "A recompute supersedes the whole award set — awards still in `COMPUTED`
    are voided and regenerated from the current result data — so a writer holding an
    older version would silently discard awards generated from newer results." PRD §2.9
    fixes the ledger the run reports: "`purse_allocated_cents` is the sum of
    `gross_amount_cents` over the prize awards of that edition whose `status` is any of
    `COMPUTED`, `APPROVED`, `PAID` or `CLAWBACK_PENDING`, and `purse_unallocated_cents` is
    `total_purse_cents` less `purse_allocated_cents`", and "awards in `VOID` contribute
    nothing to the purse ledger".

    Design: Corner/cross_cutting_complexity_layers/corner_layer_occ_stale_edition_version_on_compute_awards
    """
    scenario = _a_certified_edition_with_two_versions_in_play()
    edition_id = scenario["edition"]["id"]
    certified_version = scenario["edition"]["version"]

    first_run = compute_awards(edition_id,
                               expected_race_edition_version=certified_version)
    assert first_run["purse_allocated_cents"] == 1_000_000
    assert first_run["purse_unallocated_cents"] == 7_000_000
    assert first_run["version"] == certified_version + 1

    replayed = api_client.compute_awards(
        edition_id, {"expected_race_edition_version": certified_version}, FINANCE
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_EDITION_VERSION.value, 412)

    second_run = compute_awards(
        edition_id, expected_race_edition_version=read_edition(edition_id)["version"]
    )
    assert second_run["purse_allocated_cents"] == 1_000_000
    assert second_run["purse_unallocated_cents"] == 7_000_000

    live, meta = list_awards({"race_edition_id": edition_id, "status": "COMPUTED"})
    assert meta["total_count"] == 1, "the earlier award set was voided by the recompute"
    assert live[0]["gross_amount_cents"] == 1_000_000


def _four_scheduled_tests_across_two_athletes():
    """Three tests for one athlete and one for another, created one clock tick apart."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Pagination Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    alpha = register_athlete(full_name="Page Alpha", country_code="USA",
                            gender="MALE", birth_date="1997-10-01",
                            whereabouts_filed=True)
    beta = register_athlete(full_name="Page Beta", country_code="USA",
                           gender="MALE", birth_date="1997-10-02",
                           whereabouts_filed=True)
    windows = [
        (alpha, "2026-09-05T08:00:00Z", "2026-09-05T18:00:00Z", "S-PG-A1"),
        (alpha, "2026-09-20T08:00:00Z", "2026-09-20T18:00:00Z", "S-PG-A2"),
        (alpha, "2026-10-05T08:00:00Z", "2026-10-05T18:00:00Z", "S-PG-A3"),
        (beta, "2026-09-06T08:00:00Z", "2026-09-06T18:00:00Z", "S-PG-B1"),
    ]
    tests = []
    for tick, (athlete, start, end, code) in enumerate(windows):
        set_clock(f"2026-08-01T00:00:0{tick}Z")
        tests.append(schedule_doping_test(
            athlete["id"], edition_id, test_type="OUT_OF_COMPETITION",
            window_start_at=start, window_end_at=end, sample_code=code,
        ))
    scenario["alpha"] = alpha
    scenario["beta"] = beta
    scenario["tests"] = tests
    return scenario


def test_a_filtered_page_reports_the_filtered_total_and_the_declared_defaults():
    """Paging walks the filtered set in creation order and an offset past the end is an
    empty page.

    PRD §2.3: "`limit` caps the number of items returned; it defaults to 10, may not be
    smaller than 1 and may not be larger than 100. `offset` is the number of items to
    skip; it defaults to 0 and may not be negative." Ordering and totals are declared
    too: "Unless a specific endpoint states otherwise, list results are ordered by
    `created_at` ascending." and "Every list response carries `limit`, `offset`,
    `total_count` and `has_more` inside the `meta` object of the envelope, where
    `total_count` is the number of matching rows before the window is applied and
    `has_more` indicates whether rows remain beyond it." PRD §3.6 provides the filters:
    doping tests "may be read individually or listed and filtered on `athlete_id`,
    `race_edition_id`, `test_type` and `status`".

    Design: Corner/cross_cutting_complexity_layers/corner_layer_pagination_with_filtering_on_doping_tests
    """
    scenario = _four_scheduled_tests_across_two_athletes()
    september_5, september_20, october_5, _beta_test = scenario["tests"]

    everything, meta = validate_paginated(
        api_client.list_doping_tests(
            LIAISON, {"race_edition_id": scenario["edition"]["id"]})
    )
    assert meta["total_count"] == 4
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["has_more"] is False
    assert len(everything) == 4

    first_page, first_meta = validate_paginated(
        api_client.list_doping_tests(
            LIAISON, {"athlete_id": scenario["alpha"]["id"], "limit": 2, "offset": 0})
    )
    assert first_meta["total_count"] == 3
    assert first_meta["has_more"] is True
    assert [row["id"] for row in first_page] == [september_5["id"],
                                                september_20["id"]]

    second_page, second_meta = validate_paginated(
        api_client.list_doping_tests(
            LIAISON, {"athlete_id": scenario["alpha"]["id"], "limit": 2, "offset": 2})
    )
    assert second_meta["total_count"] == 3
    assert second_meta["has_more"] is False
    assert [row["id"] for row in second_page] == [october_5["id"]]

    past_the_end, tail_meta = validate_paginated(
        api_client.list_doping_tests(
            LIAISON, {"athlete_id": scenario["alpha"]["id"], "limit": 2, "offset": 99})
    )
    assert past_the_end == []
    assert tail_meta["total_count"] == 3
    assert tail_meta["has_more"] is False


def test_a_status_change_moves_one_row_between_two_filtered_views():
    """Collecting one sample removes it from the scheduled view and adds it to the
    collected view, and two filters intersect.

    PRD §3.6: "Collection moves a test `SCHEDULED → COLLECTED`" and doping tests "may be
    read individually or listed and filtered on `athlete_id`, `race_edition_id`,
    `test_type` and `status`, which is the reverse-navigation channel for both of the
    entity's foreign keys." PRD §2.3 keeps the remaining rows in place: "Unless a
    specific endpoint states otherwise, list results are ordered by `created_at`
    ascending."

    Design: Corner/cross_cutting_complexity_layers/corner_layer_pagination_with_filtering_on_doping_tests
    """
    scenario = _four_scheduled_tests_across_two_athletes()
    september_5, september_20, october_5, _beta_test = scenario["tests"]
    alpha_id = scenario["alpha"]["id"]

    collected = collect_sample(september_5["id"], "COC-PG-A1",
                              at_iso8601="2026-09-05T09:00:00Z")
    assert collected["status"] == "COLLECTED"

    still_scheduled, scheduled_meta = validate_paginated(
        api_client.list_doping_tests(
            LIAISON, {"athlete_id": alpha_id, "status": "SCHEDULED",
                      "limit": 2, "offset": 0})
    )
    assert scheduled_meta["total_count"] == 2
    assert [row["id"] for row in still_scheduled] == [september_20["id"],
                                                     october_5["id"]]

    now_collected, collected_meta = validate_paginated(
        api_client.list_doping_tests(
            LIAISON, {"athlete_id": alpha_id, "status": "COLLECTED"})
    )
    assert collected_meta["total_count"] == 1
    assert now_collected[0]["id"] == september_5["id"]
    assert now_collected[0]["status"] == "COLLECTED"

    intersection, intersection_meta = validate_paginated(
        api_client.list_doping_tests(
            LIAISON, {"athlete_id": alpha_id, "status": "SCHEDULED",
                      "test_type": "IN_COMPETITION"})
    )
    assert intersection_meta["total_count"] == 0, "the filters intersect, they do not union"
    assert intersection == []


def _one_draft_invitation_on_a_ten_day_deadline():
    """A `FIELD_OPEN` edition whose `offer_response_days` is 10, with one `DRAFT`
    invitation ready to be offered to."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Immediate Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
        offer_response_days=10,
    )
    agent = register_agent(agency_name="Immediate Reps", license_code="AGT-IM-1")
    athlete = register_athlete(full_name="Instant Ida", country_code="ETH",
                              gender="MALE", birth_date="1997-11-01",
                              whereabouts_filed=True)
    record = create_verified_performance(
        athlete["id"], race_name="Qual IM", performance_date="2026-03-01",
        performance_seconds=7_900, division="ELITE", sanctioning_ref="SB-IM-1",
        chip_timed=True,
    )
    scenario["agent"] = agent
    scenario["athlete"] = athlete
    scenario["invitation"] = create_invitation(
        scenario["edition"]["id"], athlete["id"], agent["id"], record["id"], "ELITE"
    )
    return scenario


def test_the_write_body_and_the_next_read_carry_the_same_derived_values():
    """Everything the offer and the acceptance derive is present in their own responses
    and in the reads that follow.

    PRD §2.10: "Cascades run to completion inside the request that triggered them;
    consistency is immediate and there is no deferred reconciliation." PRD §3.3 lists
    what the offer stamps: it "mirrors the posted terms onto the invitation's four
    `current_` fields, stamps `offer_sent_at` from the logical clock, sets
    `response_deadline_at` to the logical clock plus the edition's `offer_response_days`
    days, records the acting operator in `negotiated_by_user_id`, and leaves the
    invitation in `OFFERED`." PRD §3.4 prices the package: "The air component is a flat
    allowance keyed to `current_air_class`: 120,000 cents for `ECONOMY`, 260,000 cents
    for `PREMIUM_ECONOMY`, and 540,000 cents for `BUSINESS`." with a hotel component of
    "32,000 cents per night multiplied by the number of nights" and a ground component of
    "18,000 cents when `current_ground_transport` is true and nothing when it is false",
    and "In every status other than `ACCEPTED`, `guaranteed_commitment_cents` reads as
    zero."

    Design: Corner/consistency_model/corner_consistency_immediate_every_derived_field_visible_in_the_same_response
    """
    scenario = _one_draft_invitation_on_a_ten_day_deadline()
    invitation_id = scenario["invitation"]["id"]

    offered = send_offer(invitation_id, appearance_fee_cents=1_500_000,
                        air_class="BUSINESS", hotel_nights=4, ground_transport=True)
    assert offered["status"] == "OFFERED"
    assert offered["offer_sent_at"] == "2026-08-01T00:00:00.000Z"
    assert offered["response_deadline_at"] == "2026-08-11T00:00:00.000Z"
    assert offered["current_appearance_fee_cents"] == 1_500_000
    assert offered["current_air_class"] == "BUSINESS"
    assert offered["current_hotel_nights"] == 4
    assert offered["current_ground_transport"] is True
    assert offered["guaranteed_commitment_cents"] == 0
    assert offered["round_count"] == 1

    reread = read_invitation(invitation_id)
    assert reread == offered, "the read adds nothing the write had not already returned"

    accepted = respond_as_agent(invitation_id, scenario["agent"]["id"], "ACCEPT")
    assert accepted["status"] == "ACCEPTED"
    assert accepted["guaranteed_commitment_cents"] == 2_186_000, (
        "1,500,000 fee plus 540,000 business air plus four nights at 32,000 plus 18,000"
    )

    edition = read_edition(scenario["edition"]["id"])
    assert edition["appearance_committed_cents"] == 2_186_000
    assert edition["appearance_uncommitted_cents"] == 6_814_000


def test_a_compensating_withdrawal_is_visible_in_the_very_next_read():
    """The bib appears on the assignment response and the reversal on the edition read.

    PRD §3.5: bib assignment writes the chosen number, and "The lowest remaining number is
    written to `bib_number`". PRD §3.4 describes the reversal from `ACCEPTED`: "It reduces
    the edition's `appearance_committed_cents` by the invitation's
    `guaranteed_commitment_cents`, resets `guaranteed_commitment_cents` to zero and
    increments the edition's `version`, so that the appearance-budget invariant of §2.9
    holds exactly again; it nulls `bib_number`, returning that bib to its division pool
    for immediate reuse". PRD §2.10: "Cascades run to completion inside the request that
    triggered them; consistency is immediate and there is no deferred reconciliation."

    Design: Corner/consistency_model/corner_consistency_immediate_every_derived_field_visible_in_the_same_response
    """
    scenario = _one_draft_invitation_on_a_ten_day_deadline()
    invitation_id = scenario["invitation"]["id"]
    send_offer(invitation_id, appearance_fee_cents=1_500_000, air_class="BUSINESS",
               hotel_nights=4, ground_transport=True)
    respond_as_agent(invitation_id, scenario["agent"]["id"], "ACCEPT")

    bibbed = assign_bib(invitation_id)
    assert bibbed["bib_number"] == 11

    accepted_rows, meta = validate_paginated(
        api_client.list_invitations(
            FINANCE, {"race_edition_id": scenario["edition"]["id"],
                      "status": "ACCEPTED"})
    )
    assert meta["total_count"] == 1
    assert accepted_rows[0]["bib_number"] == 11

    withdrawn = withdraw_invitation(invitation_id, reason="injury")
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["bib_number"] is None
    assert withdrawn["guaranteed_commitment_cents"] == 0

    edition = read_edition(scenario["edition"]["id"])
    assert edition["appearance_committed_cents"] == 0
    assert edition["appearance_uncommitted_cents"] == 9_000_000
