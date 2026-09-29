"""Conditional, temporal and polymorphic validation, and which rule wins."""
from test_helpers import (
    ApiErrorId,
    DIRECTOR,
    LIAISON,
    TECHNICAL,
    api_client,
    collect_sample,
    create_doping_test_payload,
    enroll_bibbed_invitation,
    enroll_draft_invitation,
    lock_field,
    read_doping_test,
    read_edition,
    read_invitation,
    register_agent,
    register_athlete,
    schedule_doping_test,
    send_offer,
    set_clock,
    setup_configured_edition,
    setup_field_open_edition,
    validate_error,
    validate_paginated,
)

ELITE_MALE_STANDARD = {"division": "ELITE", "gender": "MALE",
                       "max_qualifying_seconds": 8_100,
                       "bib_range_start": 11, "bib_range_end": 20}
OVERALL_MALE_FIRST = {"category": "OVERALL", "gender": "MALE", "place": 1,
                      "amount_cents": 1_000_000}
STANDARD_OFFER = {"appearance_fee_cents": 700_000, "air_class": "ECONOMY",
                  "hotel_nights": 2, "ground_transport": False}
WINDOW_START = "2026-10-05T08:00:00Z"
WINDOW_END = "2026-10-05T18:00:00Z"


def test_an_offer_through_a_suspended_agent_is_refused():
    """Suspension bites at offer time, and an identical deal through an active agent
    goes out.

    PRD §3.2: "An agent's `status` may be supplied at registration as either `ACTIVE`
    or `SUSPENDED` and defaults to `ACTIVE` when omitted; a `SUSPENDED` agent may
    neither be offered an invitation nor negotiate nor respond, and any such attempt is
    refused with `ERR_AGENT_SUSPENDED`." PRD §3.3 confirms the gate sits on this call:
    "Sending the first offer moves the invitation `DRAFT → OFFERED` and requires the
    edition to be `FIELD_OPEN` and the representing agent to be `ACTIVE`." PRD §2.11
    priority 12 fixes the status code: "a `SUSPENDED` representation agent may neither
    receive an offer nor negotiate nor respond, else `ERR_AGENT_SUSPENDED`. All three
    are 422."

    Design: Corner/validations/corner_validation_suspended_agent_cannot_be_offered_to
    """
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Suspended Agent Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    edition_id = scenario["edition"]["id"]
    struck_off = register_agent(agency_name="Struck Off Agency",
                               license_code="AGT-SU-1", status="SUSPENDED")
    good_standing = register_agent(agency_name="Good Standing Agency",
                                  license_code="AGT-SU-2")
    badly_represented = enroll_draft_invitation(
        edition_id, agent=struck_off,
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900},
    )
    well_represented = enroll_draft_invitation(
        edition_id, agent=good_standing,
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_910},
    )

    refused = api_client.send_offer(badly_represented["invitation"]["id"],
                                   dict(STANDARD_OFFER), DIRECTOR)
    validate_error(refused, ApiErrorId.ERR_AGENT_SUSPENDED.value, 422)

    admitted = send_offer(well_represented["invitation"]["id"], **STANDARD_OFFER)
    assert admitted["status"] == "OFFERED"

    blocked = read_invitation(badly_represented["invitation"]["id"])
    assert blocked["status"] == "DRAFT"
    assert blocked["offer_sent_at"] is None


def _athlete_awaiting_a_testing_window():
    """One athlete on a `FIELD_OPEN` edition, observed from a clock on 1 September."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Window Order Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    scenario["athlete"] = register_athlete(country_code="USA", gender="FEMALE",
                                          birth_date="1995-10-01",
                                          whereabouts_filed=True)
    set_clock("2026-09-01T00:00:00Z")
    return scenario


def test_a_window_that_ends_before_it_starts_is_malformed():
    """Reversed endpoints are caught by the schema check, not by a capacity rule.

    PRD §3.6 describes the field pair as "the window as `window_start_at` and
    `window_end_at` — a closed datetime interval whose end must be strictly later than
    its start". PRD §2.11 priority 4 places that among the schema checks —
    "`window_start_at` strictly earlier than `window_end_at`" — and closes with
    "Otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/validations/corner_validation_doping_window_end_before_start_rejected
    """
    scenario = _athlete_awaiting_a_testing_window()

    reversed_window = api_client.create_doping_test(
        create_doping_test_payload(
            scenario["athlete"]["id"], scenario["edition"]["id"],
            window_start_at=WINDOW_END, window_end_at=WINDOW_START,
            sample_code="S-WO-1",
        ),
        LIAISON,
    )
    validate_error(reversed_window, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    ordered = schedule_doping_test(
        scenario["athlete"]["id"], scenario["edition"]["id"],
        test_type="OUT_OF_COMPETITION", window_start_at=WINDOW_START,
        window_end_at=WINDOW_END, sample_code="S-WO-2",
    )
    assert ordered["status"] == "SCHEDULED"


def test_collection_is_refused_a_second_early_and_admitted_on_the_boundary():
    """The closed interval includes its opening instant and excludes anything before it.

    PRD §3.6: "Collection moves a test `SCHEDULED → COLLECTED` and is admitted only
    when the logical clock sits at or after `window_start_at` and at or before
    `window_end_at`; outside that closed interval it is refused with
    `ERR_COLLECTION_WINDOW_INVALID`. The request supplies a `collected_sample_ref`, the
    chain-of-custody reference, which is stored alongside a `collected_at` taken from
    the logical clock."

    Design: Corner/validations/corner_validation_doping_window_end_before_start_rejected
    """
    scenario = _athlete_awaiting_a_testing_window()
    test = schedule_doping_test(
        scenario["athlete"]["id"], scenario["edition"]["id"],
        test_type="OUT_OF_COMPETITION", window_start_at=WINDOW_START,
        window_end_at=WINDOW_END, sample_code="S-WO-2",
    )

    set_clock("2026-10-05T07:59:59Z")
    too_early = api_client.collect_sample(
        test["id"], {"collected_sample_ref": "COC-EARLY"}, LIAISON
    )
    validate_error(too_early, ApiErrorId.ERR_COLLECTION_WINDOW_INVALID.value, 422)
    assert read_doping_test(test["id"])["status"] == "SCHEDULED"

    collected = collect_sample(test["id"], "COC-ONTIME", at_iso8601=WINDOW_START)
    assert collected["status"] == "COLLECTED"
    assert collected["collected_at"] == "2026-10-05T08:00:00.000Z"
    assert collected["collected_sample_ref"] == "COC-ONTIME"


def _planning_edition_with_one_overall_line():
    """A `PLANNING` edition already carrying an OVERALL MALE place-1 line."""
    return setup_configured_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[],
        name="Polymorphic Config Marathon",
        appearance_budget_cents=9_000_000,
        total_purse_cents=8_000_000,
        bonus_pool_cap_cents=1_000_000,
    )


def test_each_purse_category_demands_its_own_field_combination():
    """A division on an OVERALL line, a place on a bonus line and a missing threshold
    are all malformed.

    PRD §3.1: "A `division` of `ELITE`, `SUB_ELITE` or `WHEELCHAIR` is required on
    `DIVISION`, `TIME_BONUS` and `RECORD_BONUS` lines and must be null on `OVERALL` and
    `MASTERS` lines. A `place` between 1 and 20 inclusive is required on `OVERALL`,
    `DIVISION` and `MASTERS` lines and must be null on `TIME_BONUS` and `RECORD_BONUS`
    lines. A `threshold_seconds`, the qualifying time in whole seconds that a bonus tier
    pays out at, is required on `TIME_BONUS` lines and must be null on every other
    category." PRD §2.11 priority 4 covers exactly this as "a coherent combination of
    `category`, `division`, `place` and `threshold_seconds` on a purse line".

    Design: Corner/validations/corner_validation_purse_line_category_combination_coherence
    """
    scenario = _planning_edition_with_one_overall_line()
    edition_id = scenario["edition"]["id"]

    overall_with_division = api_client.create_purse_line(
        {"race_edition_id": edition_id, "category": "OVERALL", "gender": "MALE",
         "place": 2, "division": "ELITE", "amount_cents": 600_000},
        DIRECTOR,
    )
    validate_error(overall_with_division, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    bonus_with_place = api_client.create_purse_line(
        {"race_edition_id": edition_id, "category": "TIME_BONUS", "division": "ELITE",
         "gender": "MALE", "place": 1, "threshold_seconds": 7_600,
         "amount_cents": 400_000},
        DIRECTOR,
    )
    validate_error(bonus_with_place, ApiErrorId.ERR_INVALID_REQUEST.value, 400)

    bonus_without_threshold = api_client.create_purse_line(
        {"race_edition_id": edition_id, "category": "TIME_BONUS", "division": "ELITE",
         "gender": "MALE", "amount_cents": 400_000},
        DIRECTOR,
    )
    validate_error(bonus_without_threshold, ApiErrorId.ERR_INVALID_REQUEST.value, 400)


def test_a_masters_line_is_legal_while_a_repeated_coordinate_is_a_duplicate():
    """The coherent combination is admitted; the already-taken coordinate is not.

    PRD §3.1: "No two purse lines of an edition may share the same combination of
    category, division, gender, place and threshold; a duplicate is refused with
    `ERR_CONFIG_DUPLICATE`." A `MASTERS` line legitimately carries a place, because a
    place "is required on `OVERALL`, `DIVISION` and `MASTERS` lines". PRD §3.1 also
    opens the structure for reading: "Committee staff and finance may read an edition's
    purse structure at any time, filtering by `category` and by `gender`".

    Design: Corner/validations/corner_validation_purse_line_category_combination_coherence
    """
    scenario = _planning_edition_with_one_overall_line()
    edition_id = scenario["edition"]["id"]

    masters = api_client.create_purse_line(
        {"race_edition_id": edition_id, "category": "MASTERS", "gender": "MALE",
         "place": 1, "amount_cents": 300_000},
        DIRECTOR,
    )
    assert masters.status_code == 201

    duplicate = api_client.create_purse_line(
        {"race_edition_id": edition_id, "category": "OVERALL", "gender": "MALE",
         "place": 1, "amount_cents": 999_000},
        DIRECTOR,
    )
    validate_error(duplicate, ApiErrorId.ERR_CONFIG_DUPLICATE.value, 409)

    lines, meta = validate_paginated(
        api_client.list_purse_lines(edition_id, DIRECTOR)
    )
    assert meta["total_count"] == 2, "only the OVERALL line and the MASTERS line exist"
    assert len(lines) == 2


def _bibbed_field_the_night_before_the_race():
    """One accepted, bibbed ELITE MALE starter with the field still open and the clock
    one second short of race day."""
    scenario = setup_field_open_edition(
        purse_lines=[OVERALL_MALE_FIRST],
        standards=[ELITE_MALE_STANDARD],
        name="Race Date Gate Marathon",
        race_date="2026-11-01",
        appearance_budget_cents=9_000_000,
        total_purse_cents=3_000_000,
        bonus_pool_cap_cents=0,
    )
    scenario["entrant"] = enroll_bibbed_invitation(
        scenario["edition"]["id"], offer=STANDARD_OFFER,
        athlete_overrides={"country_code": "USA"},
        performance_overrides={"performance_seconds": 7_900},
    )
    set_clock("2026-10-31T23:59:59Z")
    return scenario


def test_the_posture_check_surfaces_ahead_of_the_race_day_check():
    """From `FIELD_OPEN` the state error wins even though the date is also unmet.

    PRD §2.11 puts posture at priority 6 — "**Edition posture.** The owning edition's
    `status` permits the operation, per the map in §2.6, else
    `ERR_EDITION_STATE_INVALID` (409)." — and the date gate at priority 13, where
    "marking the edition raced requires the logical clock to have reached the edition's
    `race_date` at midnight UTC, else `ERR_RACE_DATE_NOT_REACHED`". PRD §3.7 states the
    transition itself: "A `TechnicalOfficial` opens the race by moving the edition
    `FIELD_LOCKED → RACED`, which is admitted only once the logical clock has reached
    the edition's `race_date` at midnight UTC; before that instant it is refused with
    `ERR_RACE_DATE_NOT_REACHED`."

    Design: Corner/validations/corner_validation_mark_raced_before_race_date_rejected
    """
    scenario = _bibbed_field_the_night_before_the_race()
    edition_id = scenario["edition"]["id"]

    from_field_open = api_client.mark_raced(edition_id, TECHNICAL)
    validate_error(from_field_open, ApiErrorId.ERR_EDITION_STATE_INVALID.value, 409)

    assert lock_field(edition_id)["status"] == "FIELD_LOCKED"

    from_field_locked = api_client.mark_raced(edition_id, TECHNICAL)
    validate_error(from_field_locked, ApiErrorId.ERR_RACE_DATE_NOT_REACHED.value, 422)


def test_midnight_on_race_day_is_early_enough_to_start_the_race():
    """The race-day boundary is inclusive, so the transition lands at 00:00:00Z.

    PRD §3.1: "Race day is a date rather than an instant, and every window measured
    against it — the race-day gate, the qualifying lookback — is measured from midnight
    UTC at the start of that date." PRD §3.7 admits the transition "only once the
    logical clock has reached the edition's `race_date` at midnight UTC".

    Design: Corner/validations/corner_validation_mark_raced_before_race_date_rejected
    """
    scenario = _bibbed_field_the_night_before_the_race()
    edition_id = scenario["edition"]["id"]
    lock_field(edition_id)
    validate_error(api_client.mark_raced(edition_id, TECHNICAL),
                   ApiErrorId.ERR_RACE_DATE_NOT_REACHED.value, 422)

    set_clock("2026-11-01T00:00:00Z")
    raced = api_client.mark_raced(edition_id, TECHNICAL)
    assert raced.status_code == 200
    assert read_edition(edition_id)["status"] == "RACED"
