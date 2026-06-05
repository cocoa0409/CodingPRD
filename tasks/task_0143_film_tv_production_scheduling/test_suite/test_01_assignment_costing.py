"""Labor-costing tests: booking estimate vs. final pay, penalties, fringe, overtime.

Every test drives the system to a real check-out / approve-pay state and pins
the stamped monetary fields to literal PRD-derived values.
"""
from test_helpers import (
    validate_success,
    fixtures,
)
from test_helpers.fixtures import LP, AD, PC


# --------------------------------------------------------------------------- #
# Difficulty/dual_variant_calc/assignment_estimate_vs_actual_diverges
# --------------------------------------------------------------------------- #
def test_estimate_at_booking_is_base_plus_projected_fringe(api):
    """PRD 3.5: "the forward-looking estimated_cost_cents is the sum
    of a base and a projected fringe." PRD 3.5: "the projected fringe is the base
    multiplied by that configuration's fringe_rate_bps, divided by 10000, rounded
    half-up to whole cents, and then with the configuration's
    pension_health_flat_cents added on top of the rounded figure."

    SAG crew rate 200000, fringe 1800 bps + flat 15000 => 200000 + 36000 + 15000
    = 251000, no penalties projected at booking.

    Design: Difficulty/dual_variant_calc/assignment_estimate_vs_actual_diverges
    """
    ctx = fixtures.setup_scheduled_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=200_000,
        is_sag_aftra=True, union_code="SAG_AFTRA", fringe_rate_bps=1800,
        fringe_flat_cents=15_000)
    asg = validate_success(api.get_assignment(ctx["assignment"]["id"], AD))
    assert asg["estimated_cost_cents"] == 251000, \
        f"expected estimate 251000, got {asg['estimated_cost_cents']}"


def test_actual_pay_diverges_from_estimate_with_overtime_and_meal(api):
    """PRD 3.5: "The locked paid_cost_cents is the sum of five terms: straight
    time, equal to the daily_rate_cents; overtime; the stamped meal_penalty_cents;
    the stamped turnaround_penalty_cents; and the stamped fringe_cents."

    Wrapped at 13.0h with 1 meal break: base 200000 + OT 25000 + meal 2500 +
    fringe 51000 = 278500, distinct from the 251000 booking estimate.

    Design: Difficulty/dual_variant_calc/assignment_estimate_vs_actual_diverges
    """
    ctx = fixtures.setup_approved_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=200_000,
        is_sag_aftra=True, union_code="SAG_AFTRA", fringe_rate_bps=1800,
        fringe_flat_cents=15_000,
        wrap_time="2026-07-01T19:00:00.000Z", meal_breaks_taken=1)
    asg = ctx["assignment"]
    assert asg["paid_cost_cents"] == 278500, \
        f"expected paid 278500, got {asg['paid_cost_cents']}"
    assert asg["estimated_cost_cents"] == 251000, \
        f"expected estimate 251000, got {asg['estimated_cost_cents']}"
    assert asg["estimated_cost_cents"] != asg["paid_cost_cents"], \
        "estimate and actual must diverge"


# --------------------------------------------------------------------------- #
# Difficulty/combinatorial_formula/actual_cost_nonlinear_multi_input
# --------------------------------------------------------------------------- #
def _setup_turnaround_breach_then_overtime_meal(api):
    """Day1 wraps at 23:00 (no penalties), day2 booked next morning 06:00 (7h
    rest), wrapped at 13.0h with 0 meals. Returns the day2 assignment id."""
    prod = fixtures.create_production(total_budget_cents=1_000_000)
    fixtures.create_budget_line(prod["id"], estimated_cents=800_000)
    fixtures.create_union_fringe(prod["id"], union_code="SAG_AFTRA",
                                 fringe_rate_bps=1800, pension_health_flat_cents=15_000)
    crew = fixtures.create_crew(prod["id"], daily_rate_cents=200_000,
                                is_sag_aftra=True, union_code="SAG_AFTRA")
    fixtures.advance_production(prod["id"])
    day1 = fixtures.create_shooting_day(prod["id"], shoot_date="2026-07-01", day_number=1)
    day2 = fixtures.create_shooting_day(prod["id"], shoot_date="2026-07-02", day_number=2)
    fixtures.advance_production(prod["id"])
    # day1: book, publish, start, check in, check out at 23:00, wrap
    asg1 = fixtures.book_assignment(day1["id"], crew["id"], day1["version"],
                                    call_time="2026-07-01T13:00:00.000Z")
    cs1 = fixtures.create_call_sheet(day1["id"], general_call_time="2026-07-01T13:00:00.000Z")
    validate_success(api.publish_call_sheet(cs1["id"], AD))
    validate_success(api.start_shooting_day(day1["id"], AD))
    validate_success(api.check_in_assignment(asg1["id"], AD))
    validate_success(api.check_out_assignment(
        asg1["id"], {"wrap_time": "2026-07-01T23:00:00.000Z", "meal_breaks_taken": 2}, AD))
    validate_success(api.wrap_shooting_day(day1["id"], AD))
    # day2: book at 06:00 (7h rest from prior 23:00 wrap), check out at 13.0h, 0 meals
    asg2 = fixtures.book_assignment(day2["id"], crew["id"], day2["version"],
                                    call_time="2026-07-02T06:00:00.000Z")
    cs2 = fixtures.create_call_sheet(day2["id"], general_call_time="2026-07-02T06:00:00.000Z")
    validate_success(api.publish_call_sheet(cs2["id"], AD))
    validate_success(api.start_shooting_day(day2["id"], AD))
    validate_success(api.check_in_assignment(asg2["id"], AD))
    return asg2["id"]


def test_meal_and_turnaround_penalties_stamped_at_checkout(api):
    """PRD 3.5: "the penalty is 2500 cents for the first missed meal plus 3500
    cents for each additional missed meal beyond the first." PRD 3.5: "if it is
    strictly under ten hours the breach incurs a flat forced-call penalty of
    exactly one full daily_rate_cents."

    13.0h / 0 meals => 2 missed => 2500+3500 = 6000; 7h rest breach => 200000.

    Design: Difficulty/combinatorial_formula/actual_cost_nonlinear_multi_input
    """
    asg2_id = _setup_turnaround_breach_then_overtime_meal(api)
    wrapped = validate_success(api.check_out_assignment(
        asg2_id, {"wrap_time": "2026-07-02T19:00:00.000Z", "meal_breaks_taken": 0}, AD))
    assert wrapped["meal_penalty_cents"] == 6000, \
        f"expected meal 6000, got {wrapped['meal_penalty_cents']}"
    assert wrapped["turnaround_penalty_cents"] == 200000, \
        f"expected turnaround 200000, got {wrapped['turnaround_penalty_cents']}"


def test_actual_pay_combines_all_five_terms_nonlinearly(api):
    """PRD 3.5: "The locked paid_cost_cents is the sum of five terms: straight
    time, equal to the daily_rate_cents; overtime; the stamped meal_penalty_cents;
    the stamped turnaround_penalty_cents; and the stamped fringe_cents."

    base 200000 + OT 25000 + meal 6000 + turnaround 200000 + fringe 51000 = 482000.

    Design: Difficulty/combinatorial_formula/actual_cost_nonlinear_multi_input
    """
    asg2_id = _setup_turnaround_breach_then_overtime_meal(api)
    validate_success(api.check_out_assignment(
        asg2_id, {"wrap_time": "2026-07-02T19:00:00.000Z", "meal_breaks_taken": 0}, AD))
    approved = validate_success(api.approve_pay_assignment(asg2_id, PC))
    assert approved["paid_cost_cents"] == 482000, \
        f"expected paid 482000, got {approved['paid_cost_cents']}"


# --------------------------------------------------------------------------- #
# Difficulty/combinatorial_formula/union_fringe_round_then_add_order
# --------------------------------------------------------------------------- #
def test_fringe_rounds_percentage_then_adds_flat(api):
    """PRD 3.5: "it is the daily_rate_cents multiplied by the configuration's
    fringe_rate_bps, divided by 10000, rounded half-up to whole cents, with
    pension_health_flat_cents added on top of the rounded figure (round first,
    then add the flat term)."

    IATSE rate 100000 at 1200 bps => 12000, + flat 8000 => fringe 20000.

    Design: Difficulty/combinatorial_formula/union_fringe_round_then_add_order
    """
    ctx = fixtures.setup_checked_in_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="IATSE", fringe_rate_bps=1200,
        fringe_flat_cents=8_000,
        call_time="2026-07-05T08:00:00.000Z", shoot_date="2026-07-05")
    wrapped = validate_success(api.check_out_assignment(
        ctx["assignment"]["id"],
        {"wrap_time": "2026-07-05T16:00:00.000Z", "meal_breaks_taken": 2}, AD))
    assert wrapped["fringe_cents"] == 20000, \
        f"expected fringe 20000, got {wrapped['fringe_cents']}"


def test_non_sag_iatse_crew_has_zero_meal_penalty(api):
    """PRD 3.5: "The first is the meal penalty, which applies only to crew where
    is_sag_aftra is true — for anyone whose is_sag_aftra is false the meal penalty
    is zero regardless of the hours worked."

    The IATSE crew here has is_sag_aftra=false, so meal_penalty_cents == 0.

    Design: Difficulty/combinatorial_formula/union_fringe_round_then_add_order
    """
    ctx = fixtures.setup_checked_in_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="IATSE", fringe_rate_bps=1200,
        fringe_flat_cents=8_000,
        call_time="2026-07-05T08:00:00.000Z", shoot_date="2026-07-05")
    wrapped = validate_success(api.check_out_assignment(
        ctx["assignment"]["id"],
        {"wrap_time": "2026-07-05T16:00:00.000Z", "meal_breaks_taken": 2}, AD))
    assert wrapped["meal_penalty_cents"] == 0, \
        f"expected meal 0, got {wrapped['meal_penalty_cents']}"


# --------------------------------------------------------------------------- #
# Corner/calculations/non_sag_crew_meal_penalty_zero
# --------------------------------------------------------------------------- #
def test_non_sag_crew_meal_penalty_zero_at_13_hours(api):
    """PRD 3.5: "for anyone whose is_sag_aftra is false the meal penalty is zero
    regardless of the hours worked."

    Non-SAG crew checked out at 13.0h with 0 meals accrues meal_penalty_cents == 0.

    Design: Corner/calculations/non_sag_crew_meal_penalty_zero
    """
    ctx = fixtures.setup_checked_in_assignment(
        total_budget_cents=1_000_000, daily_rate_cents=100_000,
        is_sag_aftra=False, union_code="NONE", with_fringe=False,
        call_time="2026-09-16T06:00:00.000Z", shoot_date="2026-09-16")
    wrapped = validate_success(api.check_out_assignment(
        ctx["assignment"]["id"],
        {"wrap_time": "2026-09-16T19:00:00.000Z", "meal_breaks_taken": 0}, AD))
    assert wrapped["meal_penalty_cents"] == 0, \
        f"expected meal 0, got {wrapped['meal_penalty_cents']}"
    assert wrapped["hours_worked"] == 13.0, \
        f"expected hours_worked 13.0, got {wrapped['hours_worked']}"


# --------------------------------------------------------------------------- #
# Corner/calculations/estimated_cost_no_fringe_when_no_union_config
# --------------------------------------------------------------------------- #
def test_estimate_has_no_fringe_when_no_union_config(api):
    """PRD 3.5: "If the person's union_code is NONE, or no matching fringe
    configuration exists, the projected fringe is zero."

    A NONE-union crew (rate 100000) with no UnionFringe row gets
    estimated_cost_cents == 100000.

    Design: Corner/calculations/estimated_cost_no_fringe_when_no_union_config
    """
    prod, day = fixtures.production_active_with_day(
        total_budget_cents=1_000_000, shoot_date="2026-09-20", day_number=1)
    crew = fixtures.create_crew(prod["id"], full_name="PA", role_title="PA",
                                daily_rate_cents=100_000, is_sag_aftra=False, union_code="NONE")
    asg = validate_success(api.create_assignment(
        {"shooting_day_id": day["id"], "crew_member_id": crew["id"],
         "call_time": "2026-09-20T06:00:00.000Z",
         "expected_shooting_day_version": day["version"]}, AD), expected_status=201)
    assert asg["estimated_cost_cents"] == 100000, \
        f"expected estimate 100000, got {asg['estimated_cost_cents']}"


# --------------------------------------------------------------------------- #
# Corner/calculations/turnaround_compliant_at_exactly_ten_hours
# --------------------------------------------------------------------------- #
def test_turnaround_compliant_at_exactly_ten_hours_rest(api):
    """PRD 3.5: "if that rest is at least ten hours the turnaround penalty is
    zero, and if it is strictly under ten hours the breach incurs a flat
    forced-call penalty of exactly one full daily_rate_cents."

    Prior wrap 18:00, next call next-day 04:00 = exactly 10.0h rest => penalty 0.

    Design: Corner/calculations/turnaround_compliant_at_exactly_ten_hours
    """
    prod = fixtures.create_production(total_budget_cents=2_000_000)
    fixtures.create_budget_line(prod["id"], estimated_cents=1_000_000)
    fixtures.create_union_fringe(prod["id"], union_code="SAG_AFTRA",
                                 fringe_rate_bps=1800, pension_health_flat_cents=15_000)
    crew = fixtures.create_crew(prod["id"], daily_rate_cents=200_000,
                                is_sag_aftra=True, union_code="SAG_AFTRA")
    fixtures.advance_production(prod["id"])
    day1 = fixtures.create_shooting_day(prod["id"], shoot_date="2026-09-18", day_number=1)
    day2 = fixtures.create_shooting_day(prod["id"], shoot_date="2026-09-19", day_number=2)
    fixtures.advance_production(prod["id"])
    asg1 = fixtures.book_assignment(day1["id"], crew["id"], day1["version"],
                                    call_time="2026-09-18T06:00:00.000Z")
    cs1 = fixtures.create_call_sheet(day1["id"], general_call_time="2026-09-18T06:00:00.000Z")
    validate_success(api.publish_call_sheet(cs1["id"], AD))
    validate_success(api.start_shooting_day(day1["id"], AD))
    validate_success(api.check_in_assignment(asg1["id"], AD))
    validate_success(api.check_out_assignment(
        asg1["id"], {"wrap_time": "2026-09-18T18:00:00.000Z", "meal_breaks_taken": 2}, AD))
    validate_success(api.wrap_shooting_day(day1["id"], AD))
    asg2 = fixtures.book_assignment(day2["id"], crew["id"], day2["version"],
                                    call_time="2026-09-19T04:00:00.000Z")
    cs2 = fixtures.create_call_sheet(day2["id"], general_call_time="2026-09-19T04:00:00.000Z")
    validate_success(api.publish_call_sheet(cs2["id"], AD))
    validate_success(api.start_shooting_day(day2["id"], AD))
    validate_success(api.check_in_assignment(asg2["id"], AD))
    wrapped = validate_success(api.check_out_assignment(
        asg2["id"], {"wrap_time": "2026-09-19T12:00:00.000Z", "meal_breaks_taken": 2}, AD))
    assert wrapped["turnaround_penalty_cents"] == 0, \
        f"expected turnaround 0, got {wrapped['turnaround_penalty_cents']}"
