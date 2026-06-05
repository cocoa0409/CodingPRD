"""Temporal-overlap rules: half-open permit windows and closed-interval crew
occupations."""
from test_helpers import validate_success, validate_error, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import LP, AD


# --------------------------------------------------------------------------- #
# Difficulty/resource_temporal_overlap/permit_window_half_open_overlap
# --------------------------------------------------------------------------- #
def test_permit_window_overlap_rejected(api):
    """PRD 3.7: "Approving a REQUESTED permit takes it to APPROVED, but only if no
    other already-APPROVED or ACTIVE permit on the same location overlaps this
    permit's window; overlap is judged on the half-open interval
    [window_start, window_end), so two windows that merely abut at the boundary
    instant do not conflict, and any genuine overlap is refused with
    ERR_PERMIT_WINDOW_CONFLICT."

    [10:00,14:00) genuinely overlaps an APPROVED [12:00,16:00) => rejected; the
    second permit stays REQUESTED.

    Design: Difficulty/resource_temporal_overlap/permit_window_half_open_overlap
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    loc = fixtures.create_location(prod["id"], name="Rooftop", address="1 Main St")
    p1 = fixtures.create_permit(loc["id"], "P-1",
                                "2026-08-01T12:00:00.000Z", "2026-08-01T16:00:00.000Z")
    validate_success(api.approve_location_permit(p1["id"], LP))
    p2 = fixtures.create_permit(loc["id"], "P-2",
                                "2026-08-01T10:00:00.000Z", "2026-08-01T14:00:00.000Z")
    resp = api.approve_location_permit(p2["id"], LP)
    validate_error(resp, ApiErrorId.ERR_PERMIT_WINDOW_CONFLICT.value)
    refreshed = validate_success(api.get_location_permit(p2["id"], LP))
    assert refreshed["status"] == "REQUESTED"


def test_permit_window_abutting_endpoint_allowed(api):
    """PRD 3.7: "overlap is judged on the half-open interval
    [window_start, window_end), so two windows that merely abut at the boundary
    instant do not conflict".

    A back-to-back [16:00,18:00) touching the prior APPROVED window's exclusive
    end (16:00) is allowed and is approved.

    Design: Difficulty/resource_temporal_overlap/permit_window_half_open_overlap
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    loc = fixtures.create_location(prod["id"], name="Rooftop", address="1 Main St")
    p1 = fixtures.create_permit(loc["id"], "P-1",
                                "2026-08-01T12:00:00.000Z", "2026-08-01T16:00:00.000Z")
    validate_success(api.approve_location_permit(p1["id"], LP))
    p2 = fixtures.create_permit(loc["id"], "P-3",
                                "2026-08-01T16:00:00.000Z", "2026-08-01T18:00:00.000Z")
    approved = validate_success(api.approve_location_permit(p2["id"], LP))
    assert approved["status"] == "APPROVED", \
        f"expected abutting permit APPROVED, got {approved['status']}"


# --------------------------------------------------------------------------- #
# Difficulty/resource_temporal_overlap/crew_time_conflict_closed_interval_touching
# --------------------------------------------------------------------------- #
def _book_and_wrap_first_day(api):
    """ACTIVE production with the same NONE crew. Day1 wrapped [06:00,18:00].
    Returns (prod, crew, day2)."""
    prod = fixtures.create_production(total_budget_cents=2_000_000)
    fixtures.create_budget_line(prod["id"], estimated_cents=1_000_000)
    crew = fixtures.create_crew(prod["id"], daily_rate_cents=100_000,
                                is_sag_aftra=False, union_code="NONE")
    fixtures.advance_production(prod["id"])
    day1 = fixtures.create_shooting_day(prod["id"], shoot_date="2026-08-05", day_number=1)
    day2 = fixtures.create_shooting_day(prod["id"], shoot_date="2026-08-05", day_number=2, unit="SECOND")
    fixtures.advance_production(prod["id"])
    asg1 = fixtures.book_assignment(day1["id"], crew["id"], day1["version"],
                                    call_time="2026-08-05T06:00:00.000Z")
    cs1 = fixtures.create_call_sheet(day1["id"], general_call_time="2026-08-05T06:00:00.000Z")
    validate_success(api.publish_call_sheet(cs1["id"], AD))
    validate_success(api.start_shooting_day(day1["id"], AD))
    validate_success(api.check_in_assignment(asg1["id"], AD))
    validate_success(api.check_out_assignment(
        asg1["id"], {"wrap_time": "2026-08-05T18:00:00.000Z", "meal_breaks_taken": 2}, AD))
    return prod, crew, day2


def test_crew_time_conflict_touching_endpoint_rejected(api):
    """PRD 3.4: "Treating each wrapped assignment's [call_time, wrap_time] as a
    closed interval — so two intervals that merely touch at an endpoint still
    conflict — if this check-out would overlap another wrapped assignment of the
    same person, it is refused with ERR_CREW_TIME_CONFLICT."

    First wrapped [06:00,18:00]; second booked at call 18:00 and checked out at
    22:00 — the closed intervals touch at 18:00 and conflict => rejected, second
    stays CHECKED_IN.

    Design: Difficulty/resource_temporal_overlap/crew_time_conflict_closed_interval_touching
    """
    prod, crew, day2 = _book_and_wrap_first_day(api)
    asg2 = fixtures.book_assignment(day2["id"], crew["id"], day2["version"],
                                    call_time="2026-08-05T18:00:00.000Z")
    cs2 = fixtures.create_call_sheet(day2["id"], general_call_time="2026-08-05T18:00:00.000Z")
    validate_success(api.publish_call_sheet(cs2["id"], AD))
    validate_success(api.start_shooting_day(day2["id"], AD))
    validate_success(api.check_in_assignment(asg2["id"], AD))
    resp = api.check_out_assignment(
        asg2["id"], {"wrap_time": "2026-08-05T22:00:00.000Z", "meal_breaks_taken": 2}, AD)
    validate_error(resp, ApiErrorId.ERR_CREW_TIME_CONFLICT.value)
    refreshed = validate_success(api.get_assignment(asg2["id"], AD))
    assert refreshed["attendance_status"] == "CHECKED_IN"


def test_crew_time_non_overlapping_checkout_allowed(api):
    """PRD 3.4: "if this check-out would overlap another wrapped assignment of the
    same person, it is refused with ERR_CREW_TIME_CONFLICT."

    First wrapped [06:00,18:00]; a second occupation that starts strictly after
    the first ends (call 19:00, wrap 22:00) does not overlap and the check-out
    succeeds to WRAPPED.

    Design: Difficulty/resource_temporal_overlap/crew_time_conflict_closed_interval_touching
    """
    prod, crew, day2 = _book_and_wrap_first_day(api)
    asg2 = fixtures.book_assignment(day2["id"], crew["id"], day2["version"],
                                    call_time="2026-08-05T19:00:00.000Z")
    cs2 = fixtures.create_call_sheet(day2["id"], general_call_time="2026-08-05T19:00:00.000Z")
    validate_success(api.publish_call_sheet(cs2["id"], AD))
    validate_success(api.start_shooting_day(day2["id"], AD))
    validate_success(api.check_in_assignment(asg2["id"], AD))
    wrapped = validate_success(api.check_out_assignment(
        asg2["id"], {"wrap_time": "2026-08-05T22:00:00.000Z", "meal_breaks_taken": 2}, AD))
    assert wrapped["attendance_status"] == "WRAPPED", \
        f"expected WRAPPED on non-overlapping checkout, got {wrapped['attendance_status']}"
