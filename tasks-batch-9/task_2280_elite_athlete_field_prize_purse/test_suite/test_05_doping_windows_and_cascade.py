"""Testing windows, the in-competition clearance gate and the adverse-finding cascade."""
from test_helpers import (
    ApiErrorId,
    FINANCE,
    FINANCE_PAYER,
    LIAISON,
    adjudicate_doping_test,
    api_client,
    approve_award,
    assert_appearance_ledger,
    assert_purse_ledger,
    certify_edition_results,
    certify_result,
    collect_sample,
    compute_awards,
    create_doping_test_payload,
    enroll_bibbed_invitation,
    enter_result,
    list_awards,
    list_fluid_slots,
    lock_field,
    mark_raced,
    pay_award,
    read_award,
    read_doping_test,
    read_edition,
    read_invitation,
    read_result,
    register_athlete,
    reserve_fluid_slot,
    schedule_doping_test,
    set_clock,
    setup_cleared_test,
    setup_field_open_edition,
    validate_error,
    validate_paginated,
)

FIRST_WINDOW_START = "2026-10-10T08:00:00Z"
FIRST_WINDOW_END = "2026-10-10T18:00:00Z"


def _athlete_with_one_scheduled_window():
    """One athlete holding a single `SCHEDULED` out-of-competition window that runs
    to 18:00:00Z on 10 October, observed from a clock set to 1 September."""
    scenario = setup_field_open_edition(
        standards=[{"division": "ELITE", "gender": "MALE",
                    "bib_range_start": 11, "bib_range_end": 20}],
        name="Testing Window Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    athlete = register_athlete(country_code="USA", whereabouts_filed=True)
    set_clock("2026-09-01T00:00:00Z")
    scenario["athlete"] = athlete
    scenario["first_test"] = schedule_doping_test(
        athlete["id"], scenario["edition"]["id"],
        test_type="OUT_OF_COMPETITION",
        window_start_at=FIRST_WINDOW_START, window_end_at=FIRST_WINDOW_END,
        sample_code="S-W-1",
    )
    return scenario


def test_a_testing_window_that_touches_another_overlaps_it():
    """Starting exactly at the previous window's end conflicts; one second later does not.

    PRD §3.6: "The first is overlap: the requested closed window may not touch or
    overlap any window of the same athlete belonging to a test in `SCHEDULED` or
    `COLLECTED`. Touching counts as overlapping, so a window whose start equals
    another window's end conflicts, and the rejection is
    `ERR_TESTING_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/overlap_doping_test_closed_datetime_window_and_frequency_cap
    """
    scenario = _athlete_with_one_scheduled_window()
    athlete_id = scenario["athlete"]["id"]
    edition_id = scenario["edition"]["id"]

    touching = api_client.create_doping_test(
        create_doping_test_payload(
            athlete_id, edition_id, window_start_at=FIRST_WINDOW_END,
            window_end_at="2026-10-10T22:00:00Z", sample_code="S-W-2",
        ),
        LIAISON,
    )
    validate_error(touching, ApiErrorId.ERR_TESTING_WINDOW_OVERLAP.value, 409)

    one_second_clear = schedule_doping_test(
        athlete_id, edition_id, window_start_at="2026-10-10T18:00:01Z",
        window_end_at="2026-10-10T22:00:00Z", sample_code="S-W-3",
    )
    assert one_second_clear["status"] == "SCHEDULED", (
        "a window opening one second after the other closes shares no instant"
    )


def test_the_frequency_cap_refuses_a_third_window_inside_seven_days():
    """Two tests already within a week of the requested start exhaust the capacity.

    PRD §3.6: "The second rule is a frequency cap that applies regardless of overlap:
    counting the athlete's tests in every status, including completed and missed ones,
    whose `window_start_at` falls within seven days either side of the requested
    start, the request is refused with `ERR_TESTING_FREQUENCY_EXCEEDED` once that
    count has reached two."

    Design: Difficulty/resource_temporal_overlap/overlap_doping_test_closed_datetime_window_and_frequency_cap
    """
    scenario = _athlete_with_one_scheduled_window()
    athlete_id = scenario["athlete"]["id"]
    edition_id = scenario["edition"]["id"]
    schedule_doping_test(
        athlete_id, edition_id, window_start_at="2026-10-10T18:00:01Z",
        window_end_at="2026-10-10T22:00:00Z", sample_code="S-W-3",
    )

    over_frequency = api_client.create_doping_test(
        create_doping_test_payload(
            athlete_id, edition_id, window_start_at="2026-10-12T08:00:00Z",
            window_end_at="2026-10-12T18:00:00Z", sample_code="S-W-4",
        ),
        LIAISON,
    )
    validate_error(over_frequency, ApiErrorId.ERR_TESTING_FREQUENCY_EXCEEDED.value, 422)


def test_a_window_beyond_the_frequency_horizon_is_admitted():
    """Outside the seven-day reach the cap does not apply, and the refusals wrote nothing.

    PRD §3.6 counts only tests "whose `window_start_at` falls within seven days
    either side of the requested start". PRD §2.3 fixes the reported count: "where
    `total_count` is the number of matching rows before the window is applied".

    Design: Difficulty/resource_temporal_overlap/overlap_doping_test_closed_datetime_window_and_frequency_cap
    """
    scenario = _athlete_with_one_scheduled_window()
    athlete_id = scenario["athlete"]["id"]
    edition_id = scenario["edition"]["id"]
    schedule_doping_test(
        athlete_id, edition_id, window_start_at="2026-10-10T18:00:01Z",
        window_end_at="2026-10-10T22:00:00Z", sample_code="S-W-3",
    )
    refused = api_client.create_doping_test(
        create_doping_test_payload(
            athlete_id, edition_id, window_start_at="2026-10-12T08:00:00Z",
            window_end_at="2026-10-12T18:00:00Z", sample_code="S-W-4",
        ),
        LIAISON,
    )
    validate_error(refused, ApiErrorId.ERR_TESTING_FREQUENCY_EXCEEDED.value, 422)

    far_enough = schedule_doping_test(
        athlete_id, edition_id, window_start_at="2026-10-25T08:00:00Z",
        window_end_at="2026-10-25T18:00:00Z", sample_code="S-W-5",
    )
    assert far_enough["status"] == "SCHEDULED"

    tests, meta = validate_paginated(
        api_client.list_doping_tests(
            LIAISON, {"athlete_id": athlete_id, "race_edition_id": edition_id}
        )
    )
    assert meta["total_count"] == 3, "the two refused requests created nothing"
    assert len(tests) == 3


def _computed_award_cleared_out_of_competition_only():
    """A `COMPUTED` 1,000,000 award whose athlete holds one `CLEARED` test — and it
    is the out-of-competition one."""
    scenario = setup_field_open_edition(
        purse_lines=[{"category": "OVERALL", "gender": "MALE", "place": 1,
                      "amount_cents": 1_000_000}],
        standards=[{"division": "ELITE", "gender": "MALE",
                    "bib_range_start": 11, "bib_range_end": 20}],
        name="Testing Gate Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    entrant = enroll_bibbed_invitation(
        edition_id,
        offer={"appearance_fee_cents": 500_000, "air_class": "ECONOMY",
               "hotel_nights": 2, "ground_transport": False},
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900},
    )
    lock_field(edition_id)
    setup_cleared_test(
        entrant["athlete"]["id"], edition_id, test_type="OUT_OF_COMPETITION",
        window_start_at="2026-10-01T08:00:00Z",
        window_end_at="2026-10-01T18:00:00Z", sample_code="S-CS-OOC",
        collected_sample_ref="COC-CS-OOC",
    )
    set_clock("2026-11-01T09:00:00Z")
    mark_raced(edition_id)
    result = enter_result(edition_id, entrant["invitation"]["id"], gun_seconds=7_800,
                         net_seconds=7_798)
    certify_result(result["id"])
    certify_edition_results(edition_id)
    compute_awards(edition_id)
    awards, _ = list_awards({"race_edition_id": edition_id, "status": "COMPUTED"})
    scenario["entrant"] = entrant
    scenario["award"] = awards[0]
    return scenario


def test_award_approval_needs_an_in_competition_test_that_has_cleared():
    """A cleared out-of-competition test does not substitute, and a merely collected
    in-competition test does not either.

    PRD §3.8: approval "requires a doping test to exist for that result's athlete in
    that edition whose `test_type` is `IN_COMPETITION` and whose status is `CLEARED`;
    without that clearance the approval is refused with
    `ERR_IN_COMPETITION_TEST_NOT_CLEARED`." PRD §3.6 confirms which transition
    supplies it: "An outcome of `CLEARED` moves the test `COLLECTED → CLEARED`, and
    for an `IN_COMPETITION` test that clearance is what unlocks prize approval for the
    athlete."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_award_approval_requires_cleared_in_competition_test
    """
    scenario = _computed_award_cleared_out_of_competition_only()
    award_id = scenario["award"]["id"]
    edition_id = scenario["edition"]["id"]
    athlete_id = scenario["entrant"]["athlete"]["id"]

    wrong_type = api_client.approve_prize_award(award_id, FINANCE)
    validate_error(wrong_type, ApiErrorId.ERR_IN_COMPETITION_TEST_NOT_CLEARED.value,
                   422)

    in_competition = schedule_doping_test(
        athlete_id, edition_id, test_type="IN_COMPETITION",
        window_start_at="2026-11-01T06:00:00Z",
        window_end_at="2026-11-01T20:00:00Z", sample_code="S-CS-IC",
    )
    collected = collect_sample(in_competition["id"], "COC-CS-IC")
    assert collected["status"] == "COLLECTED"

    wrong_state = api_client.approve_prize_award(award_id, FINANCE)
    validate_error(wrong_state, ApiErrorId.ERR_IN_COMPETITION_TEST_NOT_CLEARED.value,
                   422)


def test_award_approval_succeeds_once_the_in_competition_test_clears():
    """The identical approval request succeeds solely because the doping test moved.

    PRD §3.8: "Approval is the first of two `FinanceOfficer` acts on an individual
    award and moves it `COMPUTED → APPROVED`." It "records the acting operator in
    `approved_by_user_id`". The winner is a domestic athlete, and PRD §3.8 says of
    that case: "When the athlete's `tax_residency_country` is `USA`, the domestic
    case, the variant is `NONE`, `withholding_bps` is zero and `withholding_cents` is
    zero on every award."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_award_approval_requires_cleared_in_competition_test
    """
    scenario = _computed_award_cleared_out_of_competition_only()
    award_id = scenario["award"]["id"]

    in_competition = schedule_doping_test(
        scenario["entrant"]["athlete"]["id"], scenario["edition"]["id"],
        test_type="IN_COMPETITION", window_start_at="2026-11-01T06:00:00Z",
        window_end_at="2026-11-01T20:00:00Z", sample_code="S-CS-IC",
    )
    collect_sample(in_competition["id"], "COC-CS-IC")
    cleared = adjudicate_doping_test(in_competition["id"], "CLEARED")
    assert cleared["status"] == "CLEARED"

    approved = approve_award(award_id, FINANCE)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == FINANCE["X-User-ID"]

    award = read_award(award_id)
    assert award["gross_amount_cents"] == 1_000_000
    assert award["withholding_variant"] == "NONE"
    assert award["withholding_cents"] == 0
    assert award["net_amount_cents"] == 1_000_000


def _paid_award_with_a_pending_out_of_competition_sample():
    """A paid prize, a claimed course record and an out-of-competition sample whose
    laboratory outcome has not yet come back."""
    scenario = setup_field_open_edition(
        purse_lines=[{"category": "OVERALL", "gender": "MALE", "place": 1,
                      "amount_cents": 1_000_000}],
        standards=[{"division": "ELITE", "gender": "MALE",
                    "bib_range_start": 11, "bib_range_end": 20}],
        name="Cascade Marathon",
        appearance_budget_cents=10_000_000,
        total_purse_cents=10_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    entrant = enroll_bibbed_invitation(
        edition_id,
        offer={"appearance_fee_cents": 1_000_000, "air_class": "ECONOMY",
               "hotel_nights": 3, "ground_transport": False},
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900},
    )
    invitation_id = entrant["invitation"]["id"]
    reserve_fluid_slot(invitation_id, station_km=10.0, table_position=5,
                       bottle_count=2)
    lock_field(edition_id)

    set_clock("2026-10-01T09:00:00Z")
    out_of_competition = schedule_doping_test(
        entrant["athlete"]["id"], edition_id, test_type="OUT_OF_COMPETITION",
        window_start_at="2026-10-01T08:00:00Z",
        window_end_at="2026-10-01T18:00:00Z", sample_code="S-OOC-1",
    )
    collect_sample(out_of_competition["id"], "COC-OOC-1")

    set_clock("2026-11-01T06:30:00Z")
    in_competition = schedule_doping_test(
        entrant["athlete"]["id"], edition_id, test_type="IN_COMPETITION",
        window_start_at="2026-11-01T06:00:00Z",
        window_end_at="2026-11-01T20:00:00Z", sample_code="S-IC-1",
    )
    collect_sample(in_competition["id"], "COC-IC-1")
    adjudicate_doping_test(in_competition["id"], "CLEARED")

    set_clock("2026-11-01T09:00:00Z")
    mark_raced(edition_id)
    result = enter_result(edition_id, invitation_id, gun_seconds=7_500,
                         net_seconds=7_498)
    certify_result(result["id"])
    certify_edition_results(edition_id)
    compute_awards(edition_id)
    awards, _ = list_awards({"race_edition_id": edition_id, "status": "COMPUTED"})
    approve_award(awards[0]["id"], FINANCE)
    paid = pay_award(awards[0]["id"], "TRSY-9001", FINANCE_PAYER)

    scenario["entrant"] = entrant
    scenario["result"] = read_result(result["id"])
    scenario["out_of_competition"] = out_of_competition
    scenario["in_competition"] = in_competition
    scenario["award"] = paid
    scenario["edition"] = read_edition(edition_id)
    return scenario


def test_adverse_finding_disqualifies_the_certified_result_and_rejects_its_claim():
    """The laboratory outcome reaches across into the result and its record claim.

    PRD §3.6: "An outcome of `ADVERSE` moves the test `COLLECTED → ADVERSE` and
    starts a four-hop cascade that is the most consequential chain in the system.
    Because the test is `ADVERSE`, every race result sharing that test's athlete and
    edition whose `certification_status` is `PROVISIONAL` or `CERTIFIED` moves to
    `DISQUALIFIED` with `dq_reason` set to `ADVERSE_ANALYTICAL_FINDING`. Because each
    of those results is now disqualified, any record claim it held in `CLAIMED` or
    `SUBMITTED` moves to `REJECTED`". PRD §3.7 adds that on disqualification
    "`place_overall`, `place_division` and `place_masters` are nulled and
    `tie_group_size` returns to 1."

    Design: Difficulty/transitive_cascade/adverse_finding_four_hop_clawback_and_breach_cascade
    """
    scenario = _paid_award_with_a_pending_out_of_competition_sample()
    assert scenario["result"]["record_claim_status"] == "CLAIMED", (
        "no course record is on file, so the certification pass raised a claim"
    )

    adverse = adjudicate_doping_test(
        scenario["out_of_competition"]["id"], "ADVERSE",
        outcome_notes="adverse analytical finding on sample S-OOC-1",
    )
    assert adverse["status"] == "ADVERSE"

    result = read_result(scenario["result"]["id"])
    assert result["certification_status"] == "DISQUALIFIED"
    assert result["dq_reason"] == "ADVERSE_ANALYTICAL_FINDING"
    assert result["place_overall"] is None
    assert result["place_division"] is None
    assert result["place_masters"] is None
    assert result["tie_group_size"] == 1
    assert result["record_claim_status"] == "REJECTED"


def test_adverse_finding_flips_the_paid_award_to_clawback_pending():
    """Cash that already left stays inside the allocated purse.

    PRD §3.7: on a disqualification "each of its prize awards in `COMPUTED` or
    `APPROVED` becomes `VOID` and each in `PAID` becomes `CLAWBACK_PENDING`", and "a
    `VOID` award leaves the allocated pool and its cents return to the unallocated
    pool, whereas a `CLAWBACK_PENDING` award stays inside the allocated pool and the
    unallocated pool does not grow." PRD §2.9 gives the reason: "awards in
    `CLAWBACK_PENDING` still do contribute, because the cash has already left the
    building and recovering it is a collections problem rather than an accounting
    one."

    Design: Difficulty/transitive_cascade/adverse_finding_four_hop_clawback_and_breach_cascade
    """
    scenario = _paid_award_with_a_pending_out_of_competition_sample()
    paid_at_before = scenario["award"]["paid_at"]
    assert_purse_ledger(scenario["edition"], 1_000_000, 9_000_000)

    adjudicate_doping_test(
        scenario["out_of_competition"]["id"], "ADVERSE",
        outcome_notes="adverse analytical finding on sample S-OOC-1",
    )

    award = read_award(scenario["award"]["id"])
    assert award["status"] == "CLAWBACK_PENDING"
    assert award["gross_amount_cents"] == 1_000_000
    assert award["paid_at"] == paid_at_before, (
        "the payment instant is a historical fact and is not rewritten"
    )
    assert_purse_ledger(read_edition(scenario["edition"]["id"]), 1_000_000, 9_000_000)


def test_adverse_finding_breaches_the_invitation_and_frees_its_resources():
    """The final hop rewrites the appearance ledger, the bib and the fluid slots.

    PRD §3.6: "because `ADVERSE_ANALYTICAL_FINDING` is one of the breach reasons, the
    invitation each disqualified result ran under moves `ACCEPTED → BREACHED` with all
    of that transition's own effects." PRD §3.7 spells those out: "the edition's
    `appearance_committed_cents` is reduced by the invitation's
    `guaranteed_commitment_cents`, that field is then reset to zero, `bib_number` is
    nulled, and every fluid-station reservation of the invitation moves from
    `RESERVED` to `RELEASED`."

    Design: Difficulty/transitive_cascade/adverse_finding_four_hop_clawback_and_breach_cascade
    """
    scenario = _paid_award_with_a_pending_out_of_competition_sample()
    invitation_id = scenario["entrant"]["invitation"]["id"]
    assert_appearance_ledger(scenario["edition"], 1_216_000, 8_784_000)

    adjudicate_doping_test(
        scenario["out_of_competition"]["id"], "ADVERSE",
        outcome_notes="adverse analytical finding on sample S-OOC-1",
    )

    invitation = read_invitation(invitation_id)
    assert invitation["status"] == "BREACHED"
    assert invitation["guaranteed_commitment_cents"] == 0
    assert invitation["bib_number"] is None

    slots, meta = list_fluid_slots(invitation_id)
    assert meta["total_count"] == 1
    assert slots[0]["status"] == "RELEASED"

    assert_appearance_ledger(read_edition(scenario["edition"]["id"]), 0, 10_000_000)
    assert read_doping_test(scenario["in_competition"]["id"])["status"] == "CLEARED", (
        "the in-competition clearance is untouched by the cascade"
    )
