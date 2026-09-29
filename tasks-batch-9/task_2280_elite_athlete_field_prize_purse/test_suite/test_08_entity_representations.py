"""What each entity's representation must carry: defaults, derived fields and identity."""
from test_helpers import (
    ApiErrorId,
    CLOCK_START,
    CLOCK_START_STAMP,
    DIRECTOR,
    NON_EXISTENT_UUID,
    add_division_standard,
    agent_counters,
    api_client,
    assert_common_fields,
    create_edition,
    create_invitation_payload,
    create_race_edition_payload,
    enroll_draft_invitation,
    is_iso8601_timestamp,
    is_valid_uuid,
    read_athlete,
    read_edition,
    read_invitation,
    register_agent,
    register_athlete,
    send_offer,
    set_clock,
    setup_field_open_edition,
    submit_performance,
    validate_error,
    validate_paginated,
    validate_success,
    verify_performance,
)

CREATION_INPUTS = {
    "name": "Corner Creation Marathon",
    "city": "Metro City",
    "race_date": "2026-11-01",
    "appearance_budget_cents": 4_000_000,
    "total_purse_cents": 6_000_000,
    "bonus_pool_cap_cents": 500_000,
}
ELITE_MALE_STANDARD = {"division": "ELITE", "gender": "MALE",
                       "max_qualifying_seconds": 8_100,
                       "bib_range_start": 11, "bib_range_end": 20}
OVERALL_MALE_FIRST = {"category": "OVERALL", "gender": "MALE", "place": 1,
                      "amount_cents": 1_000_000}


def test_a_new_edition_echoes_its_inputs_and_seeds_every_ledger_projection():
    """The purse starts wholly unallocated rather than at zero, and the row persists.

    PRD §3.1: "A freshly created edition is in `PLANNING`, with
    `appearance_committed_cents` and `purse_allocated_cents` both at zero,
    `expired_offer_count` at zero, and `version` at 1." PRD §2.9 fixes the two
    complements: "`appearance_uncommitted_cents` is `appearance_budget_cents` less
    `appearance_committed_cents`" and "`purse_unallocated_cents` is
    `total_purse_cents` less `purse_allocated_cents`."

    Design: Corner/entities/corner_create_race_edition_returns_full_ledger_baseline
    """
    set_clock(CLOCK_START)
    created = validate_success(
        api_client.create_race_edition(dict(CREATION_INPUTS), DIRECTOR), 201
    )

    for field, value in CREATION_INPUTS.items():
        assert created[field] == value, f"{field} must be echoed as supplied"
    assert created["status"] == "PLANNING"
    assert created["appearance_committed_cents"] == 0
    assert created["appearance_uncommitted_cents"] == 4_000_000
    assert created["purse_allocated_cents"] == 0
    assert created["purse_unallocated_cents"] == 6_000_000
    assert created["bonus_pool_consumed_cents"] == 0
    assert created["expired_offer_count"] == 0
    assert created["version"] == 1
    assert_common_fields(created, "race_edition")

    reread = read_edition(created["id"])
    for field in list(CREATION_INPUTS) + ["status", "appearance_uncommitted_cents",
                                          "purse_unallocated_cents", "version"]:
        assert reread[field] == created[field], (
            f"{field} was persisted rather than echoed"
        )


def test_reading_an_athlete_returns_the_stored_row_with_its_derived_residency():
    """Tax residency was never supplied, yet it reads back filled in from nationality.

    PRD §3.2: the tax profile "consists of `tax_residency_country`, again an ISO
    3166-1 alpha-3 code, which when omitted is filled in from `country_code`". PRD
    §3.2 also fixes the counter: "A system counter, `missed_test_count`, starts at
    zero and tracks how many of that athlete's tests have ended up missed."

    Design: Corner/entities/corner_read_athlete_returns_stored_representation
    """
    set_clock(CLOCK_START)
    athlete = register_athlete(full_name="Read Back Ruth", country_code="KEN",
                              gender="FEMALE", birth_date="1997-04-04")

    stored = read_athlete(athlete["id"])
    assert stored["full_name"] == "Read Back Ruth"
    assert stored["country_code"] == "KEN"
    assert stored["gender"] == "FEMALE"
    assert stored["birth_date"] == "1997-04-04"
    assert stored["tax_residency_country"] == "KEN", (
        "an omitted residency is filled in from the nationality code"
    )
    assert stored["missed_test_count"] == 0
    assert stored["version"] == 1


def test_the_list_envelope_counts_the_filtered_set_not_the_page():
    """Three rows behind a two-row page, and a narrowing filter moves the count itself.

    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the `meta` object of the envelope, where `total_count` is the
    number of matching rows before the window is applied and `has_more` indicates
    whether rows remain beyond it." PRD §3.3 fixes the filters: invitations "may be
    listed and filtered on `race_edition_id`, `athlete_id`, `agent_id`,
    `qualifying_performance_id`, `status` and `division`".

    Design: Corner/entities/corner_list_invitations_pagination_envelope_and_filter
    """
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST], standards=[ELITE_MALE_STANDARD],
        name="Pagination Marathon", appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000, bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    agent = register_agent(agency_name="Page Turner Sports")
    for date in ("2026-03-01", "2026-03-02", "2026-03-03"):
        enroll_draft_invitation(
            edition_id, agent=agent, athlete_overrides={"country_code": "USA"},
            performance_overrides={"performance_seconds": 7_900,
                                   "performance_date": date},
        )

    first_page, meta = validate_paginated(api_client.list_invitations(
        DIRECTOR, {"race_edition_id": edition_id, "limit": 2, "offset": 0}
    ))
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(first_page) == 2

    second_page, meta = validate_paginated(api_client.list_invitations(
        DIRECTOR, {"race_edition_id": edition_id, "limit": 2, "offset": 2}
    ))
    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert len(second_page) == 1

    accepted, meta = validate_paginated(api_client.list_invitations(
        DIRECTOR, {"race_edition_id": edition_id, "status": "ACCEPTED"}
    ))
    assert meta["total_count"] == 0, "the status filter narrows the count itself"
    assert accepted == []

    over_limit = api_client.list_invitations(
        DIRECTOR, {"race_edition_id": edition_id, "limit": 200}
    )
    validate_error(over_limit, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_an_unknown_edition_id_gets_the_edition_specific_not_found_code():
    """A well-formed UUID that resolves to nothing is a 404, not a 400 or an empty 200.

    PRD §2.10: identifiers are resolved so that "The first identifier that does not
    resolve determines the error, and each entity type has its own code —
    `ERR_RACE_EDITION_NOT_FOUND`, `ERR_ATHLETE_NOT_FOUND`, `ERR_REP_AGENT_NOT_FOUND`,
    `ERR_PERFORMANCE_RECORD_NOT_FOUND`, `ERR_INVITATION_NOT_FOUND`,
    `ERR_DOPING_TEST_NOT_FOUND`, `ERR_RACE_RESULT_NOT_FOUND` and
    `ERR_PRIZE_AWARD_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/corner_get_unknown_race_edition_returns_not_found
    """
    set_clock(CLOCK_START)
    response = api_client.get_race_edition(NON_EXISTENT_UUID, DIRECTOR)
    validate_error(response, ApiErrorId.ERR_RACE_EDITION_NOT_FOUND.value, 404)

    body = response.json()
    assert body["response_type"] == "error"
    assert body["data"]["error_id"] == "ERR_RACE_EDITION_NOT_FOUND"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"]


def test_omitting_the_prize_purse_is_rejected_rather_than_defaulted():
    """`total_purse_cents` has no default, so its absence is a malformed request.

    PRD §3.1: "Three money figures are supplied at the same time:
    `appearance_budget_cents`, the total guaranteed pool for appearance fees, air
    travel and hotel; `total_purse_cents`, the total prize purse covering both place
    prizes and bonuses; and `bonus_pool_cap_cents`, the ceiling on aggregate time and
    record bonuses." PRD §2.11 priority 4 rejects the omission, since the body schema
    check demands "Required fields present; enum values are declared members; integers
    inside their declared ranges" and closes with "Otherwise `ERR_INVALID_REQUEST` (400).
    Applies to every endpoint."

    Design: Corner/entities/corner_create_race_edition_missing_total_purse_rejected
    """
    set_clock(CLOCK_START)
    payload = create_race_edition_payload(name="Missing Field Marathon",
                                          city="Metro City",
                                          appearance_budget_cents=4_000_000,
                                          bonus_pool_cap_cents=0)
    payload.pop("total_purse_cents")

    response = api_client.create_race_edition(payload, DIRECTOR)
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_every_omitted_optional_lands_on_its_declared_default():
    """Fourteen response days, three rounds, masters forty, a two-year window and more.

    PRD §3.1: "`offer_response_days` is how long an offer or a counter stays open
    before it goes stale; it defaults to 14 and must lie between 1 and 60 inclusive.
    `max_negotiation_rounds` is the per-side round allowance; it defaults to 3 and must
    lie between 1 and 6 inclusive". PRD §3.1 continues: "`window_months` bounds how far
    back a qualifying performance may have been run; it defaults to 24 and must lie
    between 1 and 60 inclusive. `requires_chip_timing` defaults to true". PRD §3.2
    fixes the agent's: an agent's "`status` may be supplied at registration as either
    `ACTIVE` or `SUSPENDED` and defaults to `ACTIVE` when omitted".

    Design: Corner/entities/corner_optional_fields_take_declared_defaults
    """
    set_clock(CLOCK_START)
    edition = create_edition(name="Defaults Marathon", city="Metro City",
                            appearance_budget_cents=4_000_000,
                            total_purse_cents=6_000_000, bonus_pool_cap_cents=0)
    assert edition["offer_response_days"] == 14
    assert edition["max_negotiation_rounds"] == 3
    assert edition["masters_min_age"] == 40
    for key in ("course_record_male_seconds", "course_record_female_seconds",
                "course_record_wheelchair_male_seconds",
                "course_record_wheelchair_female_seconds"):
        assert edition[key] is None, f"{key} defaults to null with no record on file"

    standard = add_division_standard(edition["id"], **ELITE_MALE_STANDARD)
    assert standard["window_months"] == 24
    assert standard["requires_chip_timing"] is True

    athlete = register_athlete(full_name="Default Dana", country_code="USA",
                              gender="MALE", birth_date="1996-05-05")
    assert athlete["w8ben_on_file"] is False
    assert athlete["treaty_withholding_bps"] == 0
    assert athlete["whereabouts_filed"] is False
    assert athlete["missed_test_count"] == 0

    agent = register_agent(agency_name="Default Agency")
    assert agent["status"] == "ACTIVE"
    assert agent["commission_bps"] == 1_500


def test_the_invitation_money_fields_are_server_derived_at_every_step():
    """They start at zero in `DRAFT` and no create or offer field ever supplies them.

    PRD §3.3: "A `DRAFT` invitation has `guaranteed_commitment_cents` at zero,
    `full_exposure_cents` at zero and `round_count` at zero, and its
    `current_appearance_fee_cents`, `current_air_class`, `current_hotel_nights`,
    `current_ground_transport`, `offer_sent_at`, `response_deadline_at`, `bib_number`
    and `negotiated_by_user_id` are all null." Sending the offer "mirrors the posted
    terms onto the invitation's four `current_` fields". PRD §3.4 keeps the money at
    zero until terms are struck: "In every status other than `ACCEPTED`,
    `guaranteed_commitment_cents` reads as zero", and PRD §2.9 counts only "the
    invitations of that edition whose `status` is `ACCEPTED`".

    Design: Corner/entities/corner_invitation_computed_fields_seeded_then_derived_from_offer
    """
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST], standards=[ELITE_MALE_STANDARD],
        name="Computed Fields Marathon", appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000, bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    enrolled = enroll_draft_invitation(
        edition_id, athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900,
                              "performance_date": "2026-03-01"},
    )
    draft = enrolled["invitation"]
    assert draft["status"] == "DRAFT"
    assert draft["guaranteed_commitment_cents"] == 0
    assert draft["full_exposure_cents"] == 0
    assert draft["round_count"] == 0
    assert draft["bib_number"] is None
    for key in ("current_appearance_fee_cents", "current_air_class",
                "current_hotel_nights", "current_ground_transport",
                "offer_sent_at", "response_deadline_at", "negotiated_by_user_id"):
        assert draft[key] is None, f"{key} is null before any offer is sent"

    offered = send_offer(draft["id"], appearance_fee_cents=1_000_000,
                        air_class="PREMIUM_ECONOMY", hotel_nights=4,
                        ground_transport=True)
    assert offered["status"] == "OFFERED"
    assert offered["round_count"] == 1
    assert offered["current_appearance_fee_cents"] == 1_000_000
    assert offered["current_air_class"] == "PREMIUM_ECONOMY"
    assert offered["current_hotel_nights"] == 4
    assert offered["current_ground_transport"] is True
    assert offered["guaranteed_commitment_cents"] == 0, (
        "the package is on the table but nothing is committed yet"
    )

    assert read_edition(edition_id)["appearance_committed_cents"] == 0, (
        "an offer alone commits nothing; only acceptance debits the budget"
    )


def test_identity_and_timestamps_are_minted_from_the_logical_clock():
    """Two athletes a logical second apart carry different stamps, and neither is client-set.

    PRD §2.5: "Every persisted resource carries a server-minted `id`, formatted as a
    UUID with no type prefix, and a `created_at` timestamp expressed as an ISO 8601 UTC
    instant with three fractional digits (for example `2026-08-01T00:00:00.000Z`)."
    PRD §2.4: "Nothing in this system reads real wall-clock time", and "every timestamp
    the server stamps on a resource — an offer's `offer_sent_at`, a recomputed
    `response_deadline_at`, a sample's `collected_at`, an award's `paid_at` — is the
    logical clock's current value."

    Design: Corner/entities/corner_system_fields_are_server_minted_on_athlete
    """
    set_clock(CLOCK_START)
    first = register_athlete(full_name="System Sam", country_code="USA",
                            gender="MALE", birth_date="1996-07-07")
    assert first["created_at"] == CLOCK_START_STAMP
    assert first["updated_at"] == first["created_at"]
    assert first["version"] == 1
    assert first["missed_test_count"] == 0

    set_clock("2026-08-01T00:00:01Z")
    second = register_athlete(full_name="System Sue", country_code="USA",
                             gender="FEMALE", birth_date="1996-08-08")
    assert second["created_at"] == "2026-08-01T00:00:01.000Z", (
        "the logical clock, not wall time, stamps the row"
    )

    assert first["id"] != second["id"]
    assert is_valid_uuid(first["id"]) and is_valid_uuid(second["id"])
    assert is_iso8601_timestamp(second["created_at"])
    assert read_athlete(first["id"])["created_at"] == CLOCK_START_STAMP, (
        "creating a later row never rewrites an earlier one's stamp"
    )


def test_numeric_ranges_and_enum_membership_are_enforced_field_by_field():
    """A zero amount, place 21, an undeclared category and an inverted bib pool all fail.

    PRD §3.1: a purse line takes "a `category` drawn from `OVERALL`, `DIVISION`,
    `MASTERS`, `TIME_BONUS` and `RECORD_BONUS`, a `gender` of either `MALE` or
    `FEMALE`, and an `amount_cents` that must be strictly greater than zero", and "A
    `place` between 1 and 20 inclusive is required on `OVERALL`, `DIVISION` and
    `MASTERS` lines". A standard's pool runs "from `bib_range_start` — an integer
    between 1 and 9999 inclusive — through `bib_range_end`, which may not be smaller
    than the start." PRD §2.11 priority 4 collects all four: "enum values are declared
    members; integers inside their declared ranges; `net_seconds` no greater than
    `gun_seconds`; `window_start_at` strictly earlier than `window_end_at`; `start_km`
    strictly less than `end_km`; `bib_range_end` not less than `bib_range_start`", and
    closes with "Otherwise `ERR_INVALID_REQUEST` (400). Applies to every endpoint."

    Design: Corner/entities/corner_type_constraints_rejected_on_purse_line_and_result
    """
    set_clock(CLOCK_START)
    edition = create_edition(name="Constraint Marathon", city="Metro City",
                            appearance_budget_cents=4_000_000,
                            total_purse_cents=6_000_000, bonus_pool_cap_cents=0)
    edition_id = edition["id"]

    zero_amount = api_client.create_purse_line(
        {"race_edition_id": edition_id, "category": "OVERALL", "gender": "MALE",
         "place": 1, "amount_cents": 0}, DIRECTOR,
    )
    validate_error(zero_amount, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    place_over_twenty = api_client.create_purse_line(
        {"race_edition_id": edition_id, "category": "OVERALL", "gender": "MALE",
         "place": 21, "amount_cents": 100_000}, DIRECTOR,
    )
    validate_error(place_over_twenty, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    undeclared_category = api_client.create_purse_line(
        {"race_edition_id": edition_id, "category": "PODIUM", "gender": "MALE",
         "place": 1, "amount_cents": 100_000}, DIRECTOR,
    )
    validate_error(undeclared_category, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    inverted_pool = api_client.create_division_standard(
        {"race_edition_id": edition_id, "division": "ELITE", "gender": "MALE",
         "max_qualifying_seconds": 8_100, "bib_range_start": 20,
         "bib_range_end": 11}, DIRECTOR,
    )
    validate_error(inverted_pool, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    lines, meta = validate_paginated(api_client.list_purse_lines(edition_id, DIRECTOR))
    assert meta["total_count"] == 0, "none of the four rejected requests persisted"
    assert lines == []


def test_negotiation_history_is_append_only_and_carries_no_version():
    """A round has `id` and `created_at` and nothing else from the common set.

    PRD §2.5: "A `NegotiationRound` is the one exception. Rounds are append-only
    historical facts and are never edited, so a round carries only `id` and
    `created_at`; it has no `updated_at` field and no `version` field at all, and
    neither key appears in its representation." PRD §3.3: "The full negotiation history
    of an invitation can be read in ascending `round_number` and filtered by `side`."

    Design: Corner/entities/corner_negotiation_round_is_immutable_and_versionless
    """
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST], standards=[ELITE_MALE_STANDARD],
        name="Immutable History Marathon", appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000, bonus_pool_cap_cents=0,
    )
    enrolled = enroll_draft_invitation(
        scenario["edition"]["id"], athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900,
                              "performance_date": "2026-03-01"},
    )
    invitation = send_offer(enrolled["invitation"]["id"],
                           appearance_fee_cents=1_000_000, air_class="ECONOMY",
                           hotel_nights=2, ground_transport=False)

    counter = agent_counters(
        invitation["id"], enrolled["agent"]["id"],
        expected_invitation_version=invitation["version"],
        appearance_fee_cents=1_500_000, air_class="BUSINESS", hotel_nights=5,
        ground_transport=True,
    )
    assert is_valid_uuid(counter["id"])
    assert is_iso8601_timestamp(counter["created_at"])
    assert "version" not in counter
    assert "updated_at" not in counter

    committee_rounds, meta = validate_paginated(api_client.list_negotiation_rounds(
        invitation["id"], DIRECTOR, {"side": "COMMITTEE"}
    ))
    assert meta["total_count"] == 1
    assert committee_rounds[0]["round_number"] == 1
    assert committee_rounds[0]["appearance_fee_cents"] == 1_000_000, (
        "the original committee round survives the counter verbatim"
    )
    assert committee_rounds[0]["air_class"] == "ECONOMY"

    all_rounds, meta = validate_paginated(api_client.list_negotiation_rounds(
        invitation["id"], DIRECTOR
    ))
    assert meta["total_count"] == 2
    assert [row["round_number"] for row in all_rounds] == [1, 2]
    assert [row["side"] for row in all_rounds] == ["COMMITTEE", "AGENT"]


def test_a_purse_line_for_an_unknown_edition_fails_on_the_edition():
    """The parent foreign key is resolved before the line's own fields are considered.

    PRD §2.10: "A request for the purse lines of a non-existent edition therefore
    fails on the edition before anything else is considered." PRD §2.11 puts existence
    at priority 3: "Every referenced identifier resolves, path identifiers left to
    right first and then body foreign keys in input order, else the matching 404 code
    from §2.10."

    Design: Corner/entities/corner_purse_line_requires_existing_parent_edition
    """
    set_clock(CLOCK_START)
    response = api_client.create_purse_line(
        {"race_edition_id": NON_EXISTENT_UUID, "category": "OVERALL",
         "gender": "MALE", "place": 1, "amount_cents": 1_000_000}, DIRECTOR,
    )
    validate_error(response, ApiErrorId.ERR_RACE_EDITION_NOT_FOUND.value, 404)

    listing = api_client.list_purse_lines(NON_EXISTENT_UUID, DIRECTOR)
    validate_error(listing, ApiErrorId.ERR_RACE_EDITION_NOT_FOUND.value, 404)


def test_each_invitation_foreign_key_gets_its_own_not_found_code():
    """A bad agent, a bad athlete and a bad performance produce three distinct 404s.

    PRD §2.10: "Because the entity graph is flat — peers linked by foreign keys
    carried in request bodies rather than nested creation paths — reverse navigation is
    provided by sub-resource listings hanging off the three hub entities and by
    filtered top-level lists." Each key has its own code: "`ERR_RACE_EDITION_NOT_FOUND`,
    `ERR_ATHLETE_NOT_FOUND`, `ERR_REP_AGENT_NOT_FOUND`,
    `ERR_PERFORMANCE_RECORD_NOT_FOUND`". PRD §3.3 lists the five things a create names:
    "the `race_edition_id` being recruited for, the `athlete_id` being invited, the
    `agent_id` of the agent who represents that athlete for this deal, the
    `qualifying_performance_id` of the performance record pinned as the qualifying
    proof, and the `division`".

    Design: Corner/entities/corner_flat_topology_invitation_fk_integrity_across_three_parents
    """
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST], standards=[ELITE_MALE_STANDARD],
        name="FK Integrity Marathon", appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000, bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    agent = register_agent(agency_name="FK Sports")
    athlete = register_athlete(full_name="Foreign Key Fay", country_code="USA",
                              gender="MALE", birth_date="1996-10-10")
    record = submit_performance(athlete["id"], race_name="Qual FK",
                               performance_date="2026-03-01",
                               performance_seconds=7_900, division="ELITE",
                               sanctioning_ref="SB-FK-1", chip_timed=True)
    record = verify_performance(record["id"], 7_900)

    bad_agent = api_client.create_invitation(
        create_invitation_payload(edition_id, athlete["id"],
                                  "00000000-0000-4000-8000-000000000001",
                                  record["id"]),
        DIRECTOR,
    )
    validate_error(bad_agent, ApiErrorId.ERR_REP_AGENT_NOT_FOUND.value, 404)

    bad_athlete = api_client.create_invitation(
        create_invitation_payload(edition_id,
                                  "00000000-0000-4000-8000-000000000002",
                                  agent["id"], record["id"]),
        DIRECTOR,
    )
    validate_error(bad_athlete, ApiErrorId.ERR_ATHLETE_NOT_FOUND.value, 404)

    bad_record = api_client.create_invitation(
        create_invitation_payload(edition_id, athlete["id"], agent["id"],
                                  "00000000-0000-4000-8000-000000000003"),
        DIRECTOR,
    )
    validate_error(bad_record, ApiErrorId.ERR_PERFORMANCE_RECORD_NOT_FOUND.value, 404)

    created = validate_success(api_client.create_invitation(
        create_invitation_payload(edition_id, athlete["id"], agent["id"],
                                  record["id"]),
        DIRECTOR,
    ), 201)
    assert created["status"] == "DRAFT"

    invitations, meta = validate_paginated(api_client.list_invitations(
        DIRECTOR, {"race_edition_id": edition_id}
    ))
    assert meta["total_count"] == 1, "the three rejected requests created nothing"
    assert read_invitation(invitations[0]["id"])["athlete_id"] == athlete["id"]
