"""Volunteer staffing: sign-up shape, same-person overlap, shift state guards, and
the confirmed-hours posture threshold."""
from test_helpers import (
    ApiErrorId,
    create_volunteer_shift_payload,
    get_season,
    make_faire_day,
    make_season,
    make_shift,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ANY, OPERATOR, VOLUNTEER_CO
from test_helpers.test_users import make_volunteer_headers


def test_volunteer_shift_invalid_enum_returns_invalid_request(api):
    """PRD §2.9: "Required fields must be present; types, enum memberships, and
    ranges must be valid — end times strictly after their start times, `closing_date`
    on or after `opening_date`, `quantity` at least 1, fraction fields between 0 and
    1 inclusive, jury scores between 0 and 10 inclusive; a `SEASON` order must omit
    `faire_day_id` while `DAY` and `GROUP` orders must include it; unknown fields
    are rejected. All shape failures return `ERR_INVALID_REQUEST` (HTTP 400)."
    PRD §3.8: "a `role` of `GATE`, `PARKING`, `TAVERN`, `INFO`, or `BACKSTAGE`"

    Design: Corner/entities/volunteer_shift_invalid_enum_returns_invalid_request
    """
    season = make_season(name="Enum Revel")
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    res = api.create_volunteer_shift(
        create_volunteer_shift_payload(season["id"], day["id"], role="JESTER"),
        make_volunteer_headers("vol-eve"),
    )
    validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_volunteer_same_person_overlap_rejected(api):
    """PRD §3.8: "the same person may not hold two overlapping live shifts: a new
    sign-up whose half-open interval intersects that of an existing `SIGNED_UP` or
    `CONFIRMED` shift under the same `volunteer_handle` is rejected with
    `ERR_VOLUNTEER_SHIFT_OVERLAP`."
    PRD §2.5: "an interval includes its start and excludes its end, so one residency
    or shift may begin at the exact instant another ends without conflict."

    Design: Corner/validations/volunteer_same_person_overlap_rejected
    """
    season = make_season(name="Overlap Revel")
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    make_shift(season["id"], day["id"], "vol-h", "GATE",
               "2026-06-06T08:00:00Z", "2026-06-06T12:00:00Z")

    # Intersecting interval for the same handle.
    res = api.create_volunteer_shift(
        create_volunteer_shift_payload(
            season["id"], day["id"], role="INFO",
            start_time="2026-06-06T11:00:00Z", end_time="2026-06-06T15:00:00Z",
        ),
        make_volunteer_headers("vol-h"),
    )
    validate_error(res, ApiErrorId.ERR_VOLUNTEER_SHIFT_OVERLAP, expected_status=409)

    # Back-to-back (end == start) under half-open semantics is allowed.
    back_to_back = validate_success(
        api.create_volunteer_shift(
            create_volunteer_shift_payload(
                season["id"], day["id"], role="INFO",
                start_time="2026-06-06T12:00:00Z", end_time="2026-06-06T16:00:00Z",
            ),
            make_volunteer_headers("vol-h"),
        ),
        201,
    )
    assert back_to_back["status"] == "SIGNED_UP"

    # The same window under a different handle is allowed.
    other = validate_success(
        api.create_volunteer_shift(
            create_volunteer_shift_payload(season["id"], day["id"], role="INFO"),
            make_volunteer_headers("vol-i"),
        ),
        201,
    )
    assert other["status"] == "SIGNED_UP"


def test_shift_confirm_and_closeout_state_guards(api, volunteer_coordinator_headers):
    """PRD §3.8: "Confirmation by a `VolunteerCoordinator` moves `SIGNED_UP` →
    `CONFIRMED` (from any other state, `ERR_SHIFT_NOT_CONFIRMABLE`)"
    PRD §3.8: "Close-out by the coordinator takes an `outcome` against a `CONFIRMED`
    shift (else `ERR_SHIFT_NOT_CLOSABLE`) and requires the faire day to be
    `OPERATING` or `COMPLETED` (else `ERR_DAY_NOT_OPERATING`)."

    Design: Corner/validations/shift_confirm_and_closeout_state_guards
    """
    season = make_season(name="ShiftGuard Revel")
    day = make_faire_day(season["id"], "2026-06-06T00:00:00Z")
    shift = make_shift(season["id"], day["id"], "vol-j")

    # Close-out while SIGNED_UP: the shift state gate (layer 5) fires.
    res = api.close_out_shift(shift["id"], {"outcome": "WORKED"}, volunteer_coordinator_headers)
    validate_error(res, ApiErrorId.ERR_SHIFT_NOT_CLOSABLE, expected_status=409)

    confirmed = validate_success(
        api.confirm_shift(shift["id"], volunteer_coordinator_headers), 200
    )
    assert confirmed["status"] == "CONFIRMED"

    res = api.confirm_shift(shift["id"], volunteer_coordinator_headers)
    validate_error(res, ApiErrorId.ERR_SHIFT_NOT_CONFIRMABLE, expected_status=409)


def test_posture_volunteer_hours_exact_threshold(api, volunteer_coordinator_headers):
    """PRD §2.6: "The volunteer threshold is inclusive at the boundary: confirmed
    hours exactly equal to `volunteer_min_hours` satisfy it and permit `READY`.
    Hours are compared exactly, at two decimal places."
    PRD §2.6: "the season's `volunteer_confirmed_hours` is strictly below its
    `volunteer_min_hours`" yields `CONDITIONAL`.

    Design: Corner/calculations/posture_volunteer_hours_exact_threshold
    """
    set_clock()
    # Exactly 8.0 confirmed hours against a minimum of 8.
    s1 = make_season(name="Exact Revel", volunteer_min_hours=8)
    d1 = make_faire_day(s1["id"], "2026-06-06T00:00:00Z")
    sh1 = make_shift(s1["id"], d1["id"], "vol-fay", "GATE",
                     "2026-06-06T08:00:00Z", "2026-06-06T16:00:00Z")
    validate_success(api.confirm_shift(sh1["id"], volunteer_coordinator_headers), 200)
    season1 = get_season(s1["id"])
    assert season1["volunteer_confirmed_hours"] == 8.0
    assert season1["readiness_posture"] == "READY"

    # 7.5 confirmed hours against the same minimum.
    s2 = make_season(name="Short Revel", volunteer_min_hours=8)
    d2 = make_faire_day(s2["id"], "2026-06-06T00:00:00Z")
    sh2 = make_shift(s2["id"], d2["id"], "vol-gus", "GATE",
                     "2026-06-06T08:00:00Z", "2026-06-06T15:30:00Z")
    validate_success(api.confirm_shift(sh2["id"], volunteer_coordinator_headers), 200)
    season2 = get_season(s2["id"])
    assert season2["volunteer_confirmed_hours"] == 7.5
    assert season2["readiness_posture"] == "CONDITIONAL"
