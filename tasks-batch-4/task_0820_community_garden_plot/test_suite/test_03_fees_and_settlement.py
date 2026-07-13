"""Provisional vs final fees, the combinatorial final-fee formula, water-overage
rounding, work-hour boundary, the money axis, and ledger conservation."""
from test_helpers import (
    validate_success, validate_error,
    TEST_USERS,
    ApiErrorId, PROVISIONAL_FEE_CENTS,
    setup_assigned_plot, setup_assignment_with_usage,
    add_water_reading, pay_full,
    create_water_reading_payload, make_gardener_headers,
)

MANAGER = TEST_USERS["manager_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


# ----------------------------------------------------------------------
# Difficulty: assignment_fee provisional (creation) vs final (settle)
# ----------------------------------------------------------------------

def test_provisional_fee_medium_is_base_plus_deposit(api):
    """PRD §3.6: "The `provisional_fee_cents` stored at creation is simply the base fee
    plus the deposit for that size, ignoring actual water usage and work hours
    entirely."
    PRD §3.6: "The base fee is 3000 cents for a `SMALL` plot, 5000 for `MEDIUM`, and
    8000 for `LARGE`; the water deposit is 500 cents for `SMALL`, 1000 for `MEDIUM`,
    and 1500 for `LARGE`."

    Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_on_assignment
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    assert ctx["assignment"]["provisional_fee_cents"] == 6000
    assert PROVISIONAL_FEE_CENTS["MEDIUM"] == 6000


def test_final_fee_medium_diverges_from_provisional_at_settle(api):
    """PRD §3.6: "The final fee starts from the same size-based base fee, adds the
    season's water overage charge, adds a work-hour shortfall penalty, and then
    subtracts the water deposit — with the whole result floored at zero."
    PRD §3.6: "Settling ... moves occupancy to `ENDED`, computes `final_fee_cents`, and
    returns the plot from `ASSIGNED` to `AVAILABLE` (incrementing the plot's `version`)
    with no automatic re-offer."

    Design: Difficulty/dual_variant_calc/fee_provisional_vs_final_on_assignment
    """
    ctx = setup_assignment_with_usage(api, size="MEDIUM", readings=[201, 201, 201], hours=10)
    settled = validate_success(api.settle_assignment(ctx["assignment"]["id"], MANAGER), 200)
    assert settled["provisional_fee_cents"] == 6000
    assert settled["final_fee_cents"] == 7012
    assert settled["final_fee_cents"] != settled["provisional_fee_cents"]


# ----------------------------------------------------------------------
# Difficulty: nonlinear final fee combining size, water, work shortfall
# ----------------------------------------------------------------------

def test_small_final_fee_combines_three_inputs(api):
    """PRD §3.6: "Concretely: the water overage charge and the work-shortfall penalty
    are each fully resolved first, then combined as base plus water overage plus work
    penalty minus deposit, and only then is the outer floor applied so the final fee is
    never negative."

    Design: Difficulty/combinatorial_formula/final_fee_nonlinear_three_inputs
    """
    ctx = setup_assignment_with_usage(api, size="SMALL", readings=[150, 120, 100], hours=5)
    settled = validate_success(api.settle_assignment(ctx["assignment"]["id"], MANAGER), 200)
    assert settled["final_fee_cents"] == 7245


def test_small_settle_leaves_fee_axis_unpaid(api):
    """PRD §3.6: "The two move independently: an assignment can be settled on the
    occupancy axis while still `UNPAID`, or paid while still `ACTIVE`."
    PRD §3.6: "Concretely: the water overage charge and the work-shortfall penalty are
    each fully resolved first, then combined as base plus water overage plus work
    penalty minus deposit, and only then is the outer floor applied so the final fee is
    never negative."

    Design: Difficulty/combinatorial_formula/final_fee_nonlinear_three_inputs
    """
    ctx = setup_assignment_with_usage(api, size="SMALL", readings=[150, 120, 100], hours=5)
    settled = validate_success(api.settle_assignment(ctx["assignment"]["id"], MANAGER), 200)
    assert settled["final_fee_cents"] == 7245
    assert settled["occupancy_status"] == "ENDED"
    assert settled["fee_status"] == "UNPAID"


# ----------------------------------------------------------------------
# Difficulty: water-overage per-period rounding order
# ----------------------------------------------------------------------

def test_water_overage_rounds_each_period_before_summing(api):
    """PRD §3.6: "Each period's overage gallons are multiplied by the water rate of 3.5
    cents per gallon and that per-period charge is rounded half-up to whole cents
    **before** it is added to the running total."

    Design: Difficulty/combinatorial_formula/water_overage_rounding_order
    """
    ctx = setup_assignment_with_usage(api, size="MEDIUM", readings=[201, 201, 201], hours=12)
    settled = validate_success(api.settle_assignment(ctx["assignment"]["id"], MANAGER), 200)
    assert settled["final_fee_cents"] == 4012


def test_water_overage_not_summed_then_rounded_once(api):
    """PRD §3.6: "Rounding each period first and then summing is the pinned order;
    summing raw overage gallons across all periods and rounding once at the end would
    yield a different, incorrect figure."

    Design: Difficulty/combinatorial_formula/water_overage_rounding_order
    """
    ctx = setup_assignment_with_usage(api, size="MEDIUM", readings=[201, 201, 201], hours=12)
    settled = validate_success(api.settle_assignment(ctx["assignment"]["id"], MANAGER), 200)
    # Per-period: round(1*3.5)=4 thrice -> 12. Summing first (3*3.5=10.5 -> 11) is wrong.
    assert settled["final_fee_cents"] == 4012
    assert settled["final_fee_cents"] != 4011


# ----------------------------------------------------------------------
# Difficulty: work-hour requirement exact boundary
# ----------------------------------------------------------------------

def test_exactly_required_hours_incurs_no_penalty(api):
    """PRD §3.6: "A gardener who met or exceeded the requirement has a zero shortfall
    and no penalty."
    PRD §3.5: "a `SMALL` plot requires 8 hours, a `MEDIUM` plot 12 hours, and a `LARGE`
    plot 16 hours."

    Design: Difficulty/boundary_precision_check/work_hours_requirement_exact_boundary_no_penalty
    """
    ctx = setup_assignment_with_usage(api, size="MEDIUM", readings=[200, 200, 200], hours=12)
    settled = validate_success(api.settle_assignment(ctx["assignment"]["id"], MANAGER), 200)
    assert settled["final_fee_cents"] == 4000


def test_one_hour_short_incurs_shortfall_penalty(api):
    """PRD §3.6: "The work-hour shortfall penalty is computed from the shortfall hours,
    which is the greater of zero and the assignment's `required_work_hours` minus its
    accumulated `logged_work_hours`; that shortfall is multiplied by a penalty rate of
    1500 cents per hour and rounded half-up to whole cents."

    Design: Difficulty/boundary_precision_check/work_hours_requirement_exact_boundary_no_penalty
    """
    ctx = setup_assignment_with_usage(api, size="MEDIUM", readings=[200, 200, 200], hours=11)
    settled = validate_success(api.settle_assignment(ctx["assignment"]["id"], MANAGER), 200)
    # base 5000 + water 0 + penalty (1h * 1500) - deposit 1000 = 5500
    assert settled["final_fee_cents"] == 5500


# ----------------------------------------------------------------------
# Difficulty: fee-ledger conservation across pay then refund
# ----------------------------------------------------------------------

def test_pay_then_refund_restores_prepay_balance(api):
    """PRD §2.6: "This ledger is conserved: a payment of some amount immediately
    followed by a refund of that same amount leaves `balance_owed_cents` exactly at its
    pre-payment value, with no drift."

    Design: Difficulty/compensating_invariant/fee_ledger_conservation_pay_then_refund
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    asg_id = ctx["assignment"]["id"]
    pay_full(api, asg_id, 6000)
    validate_success(api.refund_assignment(asg_id, {"amount_cents": 6000}, TREASURER), 200)
    gardener = validate_success(api.get_gardener(ctx["gardener"]["id"], MANAGER), 200)
    assert gardener["balance_owed_cents"] == 6000


def test_refund_marks_fee_refunded(api):
    """PRD §3.6: "Refunding requires `fee_status` to be `PAID` (`ERR_FEE_NOT_REFUNDABLE`,
    HTTP 409 otherwise) and an `amount_cents` equal to the amount previously paid
    (`ERR_AMOUNT_MISMATCH` otherwise); it moves `fee_status` to `REFUNDED` and adds
    `amount_cents` back to `balance_owed_cents` as a compensating entry."

    Design: Difficulty/compensating_invariant/fee_ledger_conservation_pay_then_refund
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    asg_id = ctx["assignment"]["id"]
    pay_full(api, asg_id, 6000)
    refunded = validate_success(api.refund_assignment(asg_id, {"amount_cents": 6000}, TREASURER), 200)
    assert refunded["fee_status"] == "REFUNDED"


# ----------------------------------------------------------------------
# Corner: money-axis and water-reading validation
# ----------------------------------------------------------------------

def test_pay_wrong_amount_returns_amount_mismatch(api):
    """PRD §3.6: "Recording a payment requires the assignment's `fee_status` to be
    `UNPAID` (otherwise `ERR_FEE_NOT_PAYABLE`, HTTP 409) and carries an `amount_cents`
    that must equal the currently owed fee — the `final_fee_cents` if it has been set,
    otherwise the `provisional_fee_cents`; a wrong figure is rejected with
    `ERR_AMOUNT_MISMATCH` (HTTP 422)."

    Design: Corner/validations/pay_wrong_amount_returns_amount_mismatch
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    resp = api.pay_assignment(ctx["assignment"]["id"], {"amount_cents": 5000}, TREASURER)
    validate_error(resp, ApiErrorId.ERR_AMOUNT_MISMATCH.value, 422)


def test_duplicate_water_period_rejected(api):
    """PRD §3.5: "At most one reading may exist for a given assignment and period: a
    second reading for the same `assignment_id` and `period_index` is rejected during
    body validation with `ERR_VALIDATION` (HTTP 422), the same code that rejects a
    missing field, a bad enum, or an out-of-range value such as a `period_index`
    outside 1 through 3 or a negative `gallons_used`."

    Design: Corner/validations/duplicate_water_period_returns_validation
    """
    ctx = setup_assigned_plot(api, size="MEDIUM")
    asg_id = ctx["assignment"]["id"]
    add_water_reading(api, asg_id, ctx["gardener"]["id"], 1, 100)
    headers = make_gardener_headers(ctx["gardener"]["id"])
    resp = api.create_water_reading(
        create_water_reading_payload(asg_id, 1, 120, recorded_on="2026-04-15T00:00:00Z"), headers
    )
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value, 422)
