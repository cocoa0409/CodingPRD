"""Validation precedence, cross-entity state dependencies, and numeric
boundary precision."""
from test_helpers import validate_success, validate_error, fixtures
from test_helpers.api_errors import ApiErrorId
from test_helpers.fixtures import LP, AD, PC


# --------------------------------------------------------------------------- #
# Difficulty/priority_pair_validation_conflict/invalid_state_beats_budget_on_approve_pay
# --------------------------------------------------------------------------- #
def test_approve_pay_state_error_beats_budget_error(api):
    """PRD 2.8: "For an operation that drives a state machine, the system fifth
    confirms the target resource is in a state from which the requested transition
    is defined, failing otherwise with ERR_INVALID_STATE." PRD 2.8: "Only after
    all of these pass does the system evaluate the domain-specific business rules
    described in Section 3 ... budget ceilings".

    A CHECKED_IN (not WRAPPED) assignment whose cost would also exceed the tiny
    budget fails the state check first => ERR_INVALID_STATE.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_budget_on_approve_pay
    """
    ctx = fixtures.setup_checked_in_assignment(
        total_budget_cents=100_000, daily_rate_cents=200_000,
        is_sag_aftra=True, union_code="SAG_AFTRA", fringe_rate_bps=1800,
        fringe_flat_cents=15_000,
        call_time="2026-07-20T06:00:00.000Z", shoot_date="2026-07-20")
    resp = api.approve_pay_assignment(ctx["assignment"]["id"], PC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_approve_pay_on_scheduled_assignment_is_invalid_state(api):
    """PRD 3.5: "this is permitted only while payment_status is UNPAID and the
    assignment's attendance_status is WRAPPED." PRD 2.8: "the system fifth
    confirms the target resource is in a state from which the requested transition
    is defined, failing otherwise with ERR_INVALID_STATE."

    A still-SCHEDULED assignment (never checked in) is also non-WRAPPED, so
    approve-pay is refused with ERR_INVALID_STATE before any budget gate.

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_budget_on_approve_pay
    """
    ctx = fixtures.setup_scheduled_assignment(
        total_budget_cents=100_000, daily_rate_cents=200_000,
        is_sag_aftra=True, union_code="SAG_AFTRA", fringe_rate_bps=1800,
        fringe_flat_cents=15_000,
        call_time="2026-07-20T06:00:00.000Z", shoot_date="2026-07-20")
    resp = api.approve_pay_assignment(ctx["assignment"]["id"], PC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# --------------------------------------------------------------------------- #
# Difficulty/priority_pair_validation_conflict/stale_version_beats_double_booked_on_create_assignment
# --------------------------------------------------------------------------- #
def test_stale_version_beats_double_booked_on_assignment_create(api):
    """PRD 2.8: "Sixth, where an operation is OCC-guarded, the version check from
    Section 2.6 runs and a mismatch fails with ERR_STALE_VERSION. Only after all
    of these pass does the system evaluate the domain-specific business rules ...
    double bookings".

    The first booking bumped the day version; the second carries the pre-booking
    version AND repeats the same crew member. The OCC check (sixth) precedes the
    double-booked business rule => ERR_STALE_VERSION.

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_double_booked_on_create_assignment
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    fixtures.create_budget_line(prod["id"], estimated_cents=500_000)
    crew = fixtures.create_crew(prod["id"], full_name="Crew C", role_title="Grip",
                                daily_rate_cents=100_000, is_sag_aftra=False, union_code="NONE")
    fixtures.advance_production(prod["id"])
    day = fixtures.create_shooting_day(prod["id"], shoot_date="2026-07-22", day_number=1)
    fixtures.advance_production(prod["id"])
    pre_version = day["version"]
    fixtures.book_assignment(day["id"], crew["id"], pre_version,
                             call_time="2026-07-22T06:00:00.000Z")
    resp = api.create_assignment(
        {"shooting_day_id": day["id"], "crew_member_id": crew["id"],
         "call_time": "2026-07-22T07:00:00.000Z",
         "expected_shooting_day_version": pre_version}, AD)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


def test_stale_version_rejected_even_for_distinct_crew(api):
    """PRD 2.8: "Sixth, where an operation is OCC-guarded, the version check from
    Section 2.6 runs and a mismatch fails with ERR_STALE_VERSION." PRD 2.6: "if
    the supplied expected_shooting_day_version does not equal the day's current
    version, the booking is rejected with ERR_STALE_VERSION (HTTP 412)".

    The stale-version check fires independently of the double-booked rule: a
    second, distinct crew member booked with the pre-bump version is still
    rejected with ERR_STALE_VERSION (it never reaches the business-rule layer).

    Design: Difficulty/priority_pair_validation_conflict/stale_version_beats_double_booked_on_create_assignment
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    fixtures.create_budget_line(prod["id"], estimated_cents=500_000)
    crew_a = fixtures.create_crew(prod["id"], full_name="Crew A", role_title="Grip",
                                  daily_rate_cents=100_000, is_sag_aftra=False, union_code="NONE")
    crew_b = fixtures.create_crew(prod["id"], full_name="Crew B", role_title="Grip",
                                  daily_rate_cents=100_000, is_sag_aftra=False, union_code="NONE")
    fixtures.advance_production(prod["id"])
    day = fixtures.create_shooting_day(prod["id"], shoot_date="2026-07-22", day_number=1)
    fixtures.advance_production(prod["id"])
    pre_version = day["version"]
    fixtures.book_assignment(day["id"], crew_a["id"], pre_version,
                             call_time="2026-07-22T06:00:00.000Z")
    resp = api.create_assignment(
        {"shooting_day_id": day["id"], "crew_member_id": crew_b["id"],
         "call_time": "2026-07-22T07:00:00.000Z",
         "expected_shooting_day_version": pre_version}, AD)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# --------------------------------------------------------------------------- #
# Difficulty/cross_entity_state_dependency/checkin_requires_shooting_day_in_progress
# --------------------------------------------------------------------------- #
def test_checkin_requires_day_in_progress(api):
    """PRD 3.4: "Checking a person in moves attendance from SCHEDULED to
    CHECKED_IN and increments the assignment's version; it is permitted only when
    the assignment is SCHEDULED and the parent day is IN_PROGRESS."

    On a merely CALLED day check-in is refused with ERR_INVALID_STATE and the
    assignment stays SCHEDULED.

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_shooting_day_in_progress
    """
    ctx = fixtures.setup_scheduled_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="NONE", with_fringe=False,
        call_time="2026-07-28T06:00:00.000Z", shoot_date="2026-07-28")
    cs = fixtures.create_call_sheet(ctx["day"]["id"], general_call_time="2026-07-28T06:00:00.000Z")
    validate_success(api.publish_call_sheet(cs["id"], AD))  # day -> CALLED (not started)
    resp = api.check_in_assignment(ctx["assignment"]["id"], AD)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    asg = validate_success(api.get_assignment(ctx["assignment"]["id"], AD))
    assert asg["attendance_status"] == "SCHEDULED"


def test_checkin_succeeds_once_day_in_progress(api):
    """PRD 3.4: "Checking a person in moves attendance from SCHEDULED to
    CHECKED_IN and increments the assignment's version; it is permitted only when
    the assignment is SCHEDULED and the parent day is IN_PROGRESS."

    Once the parent day is started to IN_PROGRESS the same check-in succeeds,
    confirming the IN_PROGRESS dependency was the gate.

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_shooting_day_in_progress
    """
    ctx = fixtures.setup_in_progress_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="NONE", with_fringe=False,
        call_time="2026-07-28T06:00:00.000Z", shoot_date="2026-07-28")
    checked_in = validate_success(api.check_in_assignment(ctx["assignment"]["id"], AD))
    assert checked_in["attendance_status"] == "CHECKED_IN", \
        f"expected CHECKED_IN on IN_PROGRESS day, got {checked_in['attendance_status']}"


# --------------------------------------------------------------------------- #
# Difficulty/cross_entity_state_dependency/production_wrap_blocked_by_active_shooting_day
# --------------------------------------------------------------------------- #
def test_production_wrap_blocked_while_day_open(api):
    """PRD 3.1: "Advancing from ACTIVE to WRAPPED requires the production to be in
    ACTIVE and, critically, that none of its shooting days remain in PLANNED,
    CALLED, or IN_PROGRESS — every day must already have reached WRAPPED or
    CANCELLED". PRD 3.1: "Any advance attempted from a state that does not match
    the expected source state is refused with ERR_INVALID_STATE."

    With a still-PLANNED day, advancing the ACTIVE production is refused and it
    stays ACTIVE.

    Design: Difficulty/cross_entity_state_dependency/production_wrap_blocked_by_active_shooting_day
    """
    prod, day = fixtures.production_active_with_day(
        total_budget_cents=1_000_000, shoot_date="2026-07-30", day_number=1)
    resp = api.advance_production(prod["id"], LP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    refreshed = validate_success(api.get_production(prod["id"], LP))
    assert refreshed["status"] == "ACTIVE"


def test_production_wrap_succeeds_once_day_cancelled(api):
    """PRD 3.1: "Advancing from ACTIVE to WRAPPED requires the production to be in
    ACTIVE and, critically, that none of its shooting days remain in PLANNED,
    CALLED, or IN_PROGRESS — every day must already have reached WRAPPED or
    CANCELLED — and it increments version."

    Once the only open day is CANCELLED, the ACTIVE production advances to
    WRAPPED, confirming the open-day condition was the blocker.

    Design: Difficulty/cross_entity_state_dependency/production_wrap_blocked_by_active_shooting_day
    """
    prod, day = fixtures.production_active_with_day(
        total_budget_cents=1_000_000, shoot_date="2026-07-30", day_number=1)
    validate_success(api.cancel_shooting_day(day["id"], AD))
    advanced = validate_success(api.advance_production(prod["id"], LP))
    assert advanced["status"] == "WRAPPED", \
        f"expected WRAPPED after cancelling open day, got {advanced['status']}"


# --------------------------------------------------------------------------- #
# Difficulty/boundary_precision_check/meal_penalty_at_exactly_six_hours
# --------------------------------------------------------------------------- #
def test_meal_penalty_at_exactly_six_hours(api):
    """PRD 3.5: "the number of required meals is the worked hours divided by six
    and rounded down to a whole number ... the penalty is 2500 cents for the first
    missed meal". PRD 3.5: "The boundary is inclusive at six hours: reaching
    exactly six worked hours triggers the first required meal."

    SAG crew wrapped at exactly 6.0h, 0 meals => 1 required, 1 missed => 2500.

    Design: Difficulty/boundary_precision_check/meal_penalty_at_exactly_six_hours
    """
    ctx = fixtures.setup_checked_in_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=200_000,
        is_sag_aftra=True, union_code="SAG_AFTRA", fringe_rate_bps=1800,
        fringe_flat_cents=15_000,
        call_time="2026-07-24T06:00:00.000Z", shoot_date="2026-07-24")
    wrapped = validate_success(api.check_out_assignment(
        ctx["assignment"]["id"],
        {"wrap_time": "2026-07-24T12:00:00.000Z", "meal_breaks_taken": 0}, AD))
    assert wrapped["hours_worked"] == 6.0, \
        f"expected hours_worked 6.0, got {wrapped['hours_worked']}"
    assert wrapped["meal_penalty_cents"] == 2500, \
        f"expected meal 2500 at 6.0h, got {wrapped['meal_penalty_cents']}"


def test_meal_penalty_just_below_six_hours_is_zero(api):
    """PRD 3.5: "the number of required meals is the worked hours divided by six
    and rounded down to a whole number ... If no meals were missed the penalty is
    zero". PRD 3.5: "The boundary is inclusive at six hours: reaching exactly six
    worked hours triggers the first required meal."

    Just under six hours (5.5h) gives 0 required meals => meal_penalty_cents == 0,
    the X-1 side of the boundary.

    Design: Difficulty/boundary_precision_check/meal_penalty_at_exactly_six_hours
    """
    ctx = fixtures.setup_checked_in_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=200_000,
        is_sag_aftra=True, union_code="SAG_AFTRA", fringe_rate_bps=1800,
        fringe_flat_cents=15_000,
        call_time="2026-07-24T06:00:00.000Z", shoot_date="2026-07-24")
    wrapped = validate_success(api.check_out_assignment(
        ctx["assignment"]["id"],
        {"wrap_time": "2026-07-24T11:30:00.000Z", "meal_breaks_taken": 0}, AD))
    assert wrapped["hours_worked"] == 5.5, \
        f"expected hours_worked 5.5, got {wrapped['hours_worked']}"
    assert wrapped["meal_penalty_cents"] == 0, \
        f"expected meal 0 below 6.0h, got {wrapped['meal_penalty_cents']}"


# --------------------------------------------------------------------------- #
# Difficulty/boundary_precision_check/budget_summary_over_budget_strict_greater
# --------------------------------------------------------------------------- #
def _setup_summary_equal_actual_to_estimate(api):
    """Production with labor line 227500 + fringe line 51000; one assignment paid
    at 278500 so both lines' actuals exactly meet their estimates."""
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    fixtures.create_budget_line(prod["id"], category="BELOW_THE_LINE_LABOR",
                                estimated_cents=227_500)
    fixtures.create_budget_line(prod["id"], category="FRINGES", estimated_cents=51_000)
    fixtures.create_union_fringe(prod["id"], union_code="SAG_AFTRA",
                                 fringe_rate_bps=1800, pension_health_flat_cents=15_000)
    crew = fixtures.create_crew(prod["id"], daily_rate_cents=200_000,
                                is_sag_aftra=True, union_code="SAG_AFTRA")
    fixtures.advance_production(prod["id"])
    day = fixtures.create_shooting_day(prod["id"], shoot_date="2026-07-26", day_number=1)
    fixtures.advance_production(prod["id"])
    asg = fixtures.book_assignment(day["id"], crew["id"], day["version"],
                                   call_time="2026-07-26T06:00:00.000Z")
    cs = fixtures.create_call_sheet(day["id"], general_call_time="2026-07-26T06:00:00.000Z")
    validate_success(api.publish_call_sheet(cs["id"], AD))
    validate_success(api.start_shooting_day(day["id"], AD))
    validate_success(api.check_in_assignment(asg["id"], AD))
    validate_success(api.check_out_assignment(
        asg["id"], {"wrap_time": "2026-07-26T19:00:00.000Z", "meal_breaks_taken": 1}, AD))
    validate_success(api.approve_pay_assignment(asg["id"], PC))
    validate_success(api.mark_paid_assignment(asg["id"], PC))
    return prod


def test_budget_summary_not_over_budget_when_actual_equals_estimate(api):
    """PRD 3.1: "over_budget (true only when total actual is strictly greater than
    total estimated — a production whose actual exactly equals its estimate is not
    over budget)". PRD 3.1: "total_variance_cents (the total estimated minus the
    total actual)".

    Actuals (227500 + 51000) exactly equal estimates => over_budget false,
    total_variance 0.

    Design: Difficulty/boundary_precision_check/budget_summary_over_budget_strict_greater
    """
    prod = _setup_summary_equal_actual_to_estimate(api)
    summary = validate_success(api.get_budget_summary(prod["id"], LP))
    assert summary["total_actual_cents"] == 278500, \
        f"expected total_actual 278500, got {summary['total_actual_cents']}"
    assert summary["total_estimated_cents"] == 278500, \
        f"expected total_estimated 278500, got {summary['total_estimated_cents']}"
    assert summary["total_variance_cents"] == 0, \
        f"expected total_variance 0, got {summary['total_variance_cents']}"
    assert summary["over_budget"] is False, \
        f"expected over_budget false, got {summary['over_budget']}"


def test_budget_summary_over_budget_when_actual_strictly_exceeds_estimate(api):
    """PRD 3.1: "over_budget (true only when total actual is strictly greater than
    total estimated".

    A LOCATIONS line estimated 100000 with a manual actual of 100001 posted
    against it makes total actual strictly exceed total estimate => over_budget
    true. (X+1 side of the strict-> boundary.)

    Design: Difficulty/boundary_precision_check/budget_summary_over_budget_strict_greater
    """
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    line = fixtures.create_budget_line(prod["id"], category="LOCATIONS",
                                       estimated_cents=100_000)
    prod_v = prod["version"]
    validate_success(api.post_actual(
        line["id"], {"amount_cents": 100_001, "expected_production_version": prod_v}, LP))
    summary = validate_success(api.get_budget_summary(prod["id"], LP))
    assert summary["total_actual_cents"] == 100001
    assert summary["total_estimated_cents"] == 100000
    assert summary["over_budget"] is True, \
        f"expected over_budget true, got {summary['over_budget']}"
