"""Requests that violate two rules of the global rejection order at once, each
paired with a control call that proves the lower-priority rule was armed rather
than dormant.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    MEASUREMENT_A,
    MEASUREMENT_B,
    MEASUREMENT_D,
    ApiErrorId,
    assert_same_instant,
    build_accepted_fleet_world,
    create_protest_payload,
    merge_division,
    patch_member,
    read_division,
    read_entry,
    read_member,
    read_race,
    read_regatta,
    record_result,
    set_clock,
    withdraw_entry,
)

RACE_START = "2026-08-05T14:00:00Z"
RESULTS_CLOSED = "2026-08-05T18:00:00Z"
PAST_THE_LIMIT = "2026-08-05T21:00:00Z"

THREE_ENTRANTS = (
    {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A},
    {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
    {"key": "C", "helm": "helm_3", "measurement": MEASUREMENT_D},
)


def _expired_window_world(api):
    """Three accepted boats, a started race whose results closed at 18:00, one
    entry withdrawn afterwards, and the clock pushed well past the 90-minute
    protest limit that therefore expired at 19:30.
    """
    world = build_accepted_fleet_world(
        entrants=THREE_ENTRANTS,
        panel=True,
        racing=True,
        staffing=True,
        races=({"race_number": 1, "scheduled_start_utc": RACE_START},),
        start_races=(1,),
    )
    set_clock(RESULTS_CLOSED)
    pro_id = world["ids"]["pro"]
    race_id = world["races"][1]["id"]
    for key, elapsed in (("A", 5027.8), ("B", 5312.8), ("C", 5105.4)):
        record_result(race_id, world["entries"][key]["id"], pro_id, elapsed_seconds=elapsed)
    world["entries"]["B"] = withdraw_entry(
        world["entries"]["B"]["id"], world["ids"]["helm_2"]
    )
    set_clock(PAST_THE_LIMIT)
    return world


def _file_against(api, world, protestee_key):
    return api.create_protest(
        create_protest_payload(
            world["races"][1]["id"],
            world["entries"]["A"]["id"],
            world["entries"][protestee_key]["id"],
            "2026-08-05T14:20:00Z",
            rule_cited="RRS_11",
        ),
        world["h"]["helm_1"],
    )


def test_a_withdrawn_protestee_outranks_the_expired_protest_window(api):
    """PRD 2.7 item 17: "No entry named by the request is `WITHDRAWN`, else
    `ERR_ENTRY_WITHDRAWN`. This check applies to four operations: protest filing,
    evidence filing, result recording and recall signalling. Because it outranks
    the protest-window deadline, a protest filed against a withdrawn entry after
    the window has closed is answered with `ERR_ENTRY_WITHDRAWN`, not with
    `ERR_PROTEST_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/protest_on_withdrawn_entry_past_window_returns_entry_withdrawn
    """
    world = _expired_window_world(api)
    assert read_entry(world["entries"]["B"]["id"])["registration_status"] == "WITHDRAWN"

    validate_error(
        _file_against(api, world, "B"),
        ApiErrorId.ERR_ENTRY_WITHDRAWN,
        expected_status=409,
    )

    validate_error(
        _file_against(api, world, "C"),
        ApiErrorId.ERR_PROTEST_WINDOW_CLOSED,
        expected_status=422,
    )


def test_neither_precedence_refusal_of_a_protest_filing_leaves_a_trace(api):
    """PRD 2.7: "The server therefore evaluates its checks in one strict, global
    order and answers with the **first** failing check — never with a later one,
    and never with a collection of them."

    PRD 3.10 records the same ordering from the protest side: "Neither party may
    be `WITHDRAWN`, and that check outranks the window deadline as section 2.7
    records."

    Design: Difficulty/priority_pair_validation_conflict/protest_on_withdrawn_entry_past_window_returns_entry_withdrawn
    """
    world = _expired_window_world(api)
    validate_error(_file_against(api, world, "B"), ApiErrorId.ERR_ENTRY_WITHDRAWN)
    validate_error(_file_against(api, world, "C"), ApiErrorId.ERR_PROTEST_WINDOW_CLOSED)

    rows, pagination = validate_paginated(
        api.list_protests(world["h"]["chair"], {"regatta_id": world["regatta_id"]})
    )
    assert rows == []
    assert pagination["total_count"] == 0, "a refused filing creates no protest row"

    assert read_entry(world["entries"]["A"]["id"])["registration_status"] == "ACCEPTED"
    race = read_race(world["races"][1]["id"])
    assert_same_instant(race["results_closed_utc"], RESULTS_CLOSED, "results_closed_utc")
    assert race["scoring_status"] == "PROVISIONAL"
    division = read_division(world["divisions"]["A"]["id"])
    assert division["status"] == "CONFIRMED", "two assigned entries still meet the floor"
    assert division["assigned_entry_count"] == 2
    assert division["accepted_entry_count"] == 2


NARROW = {
    "code": "N",
    "boat_type_filter": "MONOHULL",
    "rating_band_low": 165.0,
    "rating_band_high": 175.0,
    "min_entries": 2,
}
WIDE = {
    "code": "W",
    "boat_type_filter": "MONOHULL",
    "rating_band_low": 210.0,
    "rating_band_high": 230.0,
    "min_entries": 2,
}
LAPSED_COURSE = "2026-01-31T00:00:00Z"
VALID_COURSE = "2027-06-30T00:00:00Z"


def _merged_band_mismatch_world():
    """An entry legitimately assigned to a narrow division, then carried into a
    band it does not fit by the merge of that division into a wider one.

    No band is ever edited: the merge target is chosen by band-midpoint proximity
    and re-points every entry it absorbs without re-testing their keys.
    """
    world = build_accepted_fleet_world(
        divisions=(NARROW, WIDE),
        entrants=(
            {"key": "B", "helm": "helm_2", "measurement": MEASUREMENT_B},
            {"key": "C", "helm": "helm_3", "measurement": MEASUREMENT_B},
            {"key": "A", "helm": "helm_1", "measurement": MEASUREMENT_A, "accept": False},
        ),
        confirm_division_codes=("W",),
    )
    assert world["entries"]["A"]["division_id"] == world["divisions"]["N"]["id"], (
        "171.3 fits only the narrow band at assignment time"
    )
    world["divisions"]["N"] = merge_division(
        world["divisions"]["N"]["id"], world["ids"]["chair"]
    )
    return world


def test_a_lapsed_crew_safety_course_outranks_the_division_band_mismatch(api):
    """PRD 2.7 item 18: "Every member on the entry's `crew_manifest` has a
    non-null `safety_course_expiry_utc` that is at or after the regatta's
    `series_start_utc`, else `ERR_CREW_SAFETY_COURSE_EXPIRED`. This check applies
    to crew addition and to entry acceptance. Because it outranks the band check,
    an entry whose crew safety course has lapsed and whose pinned band no longer
    matches its division is answered with `ERR_CREW_SAFETY_COURSE_EXPIRED`, not
    with `ERR_DIVISION_BAND_MISMATCH`."

    Both members of this pair answer with 422, so the ordering cannot be inferred
    from the status code; only the error identifier distinguishes them.

    Design: Difficulty/priority_pair_validation_conflict/accept_with_expired_safety_and_band_mismatch_returns_safety_first
    """
    world = _merged_band_mismatch_world()
    entry_id = world["entries"]["A"]["id"]
    helm_id = world["ids"]["helm_1"]
    assert read_entry(entry_id)["division_id"] == world["divisions"]["W"]["id"], (
        "the merge re-pointed the entry without re-testing its band"
    )

    patch_member(helm_id, safety_course_expiry_utc=LAPSED_COURSE)
    validate_error(
        api.accept_entry(entry_id, world["h"]["chair"]),
        ApiErrorId.ERR_CREW_SAFETY_COURSE_EXPIRED,
        expected_status=422,
    )

    patch_member(helm_id, safety_course_expiry_utc=VALID_COURSE)
    validate_error(
        api.accept_entry(entry_id, world["h"]["chair"]),
        ApiErrorId.ERR_DIVISION_BAND_MISMATCH,
        expected_status=422,
    )

    restored = read_member(helm_id)
    assert restored["safety_course_expiry_utc"] == VALID_COURSE
    assert restored["version"] == 3, "enrolment and the two credential patches"


def test_the_merge_that_manufactured_the_mismatch_left_the_counts_consistent(api):
    """PRD 3.4: "Hop two re-points every entry currently held by the merged
    division to the target division — only entries in `SUBMITTED` or `ACCEPTED`
    bear on any count, but the pointer itself moves for every entry of the merged
    division."

    PRD 3.5 states the check the re-pointed entry now fails: "And the pinned
    `band_key_spm` must still fall inside the assigned division's band, low edge
    inclusive and high edge exclusive, with the boat's `boat_type` still matching
    that division's `boat_type_filter`, otherwise `ERR_DIVISION_BAND_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/accept_with_expired_safety_and_band_mismatch_returns_safety_first
    """
    world = _merged_band_mismatch_world()
    entry_id = world["entries"]["A"]["id"]
    wide_id = world["divisions"]["W"]["id"]

    patch_member(world["ids"]["helm_1"], safety_course_expiry_utc=LAPSED_COURSE)
    validate_error(
        api.accept_entry(entry_id, world["h"]["chair"]),
        ApiErrorId.ERR_CREW_SAFETY_COURSE_EXPIRED,
    )
    patch_member(world["ids"]["helm_1"], safety_course_expiry_utc=VALID_COURSE)
    validate_error(
        api.accept_entry(entry_id, world["h"]["chair"]),
        ApiErrorId.ERR_DIVISION_BAND_MISMATCH,
    )

    refused = read_entry(entry_id)
    assert refused["registration_status"] == "SUBMITTED", "neither refusal admitted it"
    assert refused["inspection_status"] == "PASSED"
    assert refused["division_id"] == wide_id

    merged = read_division(world["divisions"]["N"]["id"])
    assert merged["status"] == "MERGED"
    assert merged["merged_into_division_id"] == wide_id

    target = read_division(wide_id)
    assert target["status"] == "CONFIRMED"
    assert target["assigned_entry_count"] == 3
    assert target["accepted_entry_count"] == 2, "the refused accepts never moved the count"

    regatta = read_regatta(world["regatta_id"])
    assert regatta["confirmed_division_count"] == 1
    assert regatta["status"] == "SI_PUBLISHED"
