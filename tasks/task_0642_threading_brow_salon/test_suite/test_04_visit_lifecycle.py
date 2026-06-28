"""Service-visit lifecycle: line items + polymorphic reference, the provisional
estimate vs the finalized settlement (dual-variant + combinatorial pricing), loyalty
earn rounding, the parallel service/payment dimensions, settle-time redemption, and
the line-item / settlement validation gates.

Covers difficulty queue A rules `dual_variant_calc`, `combinatorial_formula`,
`non_linear_state_machine` (parallel dimensions), and `boundary_precision_check`
(redeem floor); plus corner queue B instances under `calculations`,
`state_machines` (settle guard, complete invalid-from), and `validations`
(line gates).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_technician_headers,
)
import test_helpers as th

FRONT_DESK = TEST_USERS["front_desk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ===========================================================================
# Difficulty A: dual_variant_calc / visit_estimate_vs_final_settlement_diverge
# ===========================================================================
def test_estimate_uses_list_prices_at_seating(api):
    """PRD §3.5: "The provisional `estimate_total_cents` is a list-price view computed
    at seating ... The estimate deliberately ignores every membership discount and
    package credit, counting retail at full unit price."

    Design: Difficulty/dual_variant_calc/visit_estimate_vs_final_settlement_diverge
    """
    s = th.setup_divergence_visit(tier="SILVER", package_eligible=True)
    visit = validate_success(api.get_service_visit(s["visit"]["id"], FRONT_DESK))
    # service 2000 + TINT 1500 + SERUM 3000, list prices, ignoring discount/credit.
    assert visit["estimate_total_cents"] == 6500, (
        f"expected estimate 6500, got {visit['estimate_total_cents']}"
    )


def test_final_settlement_diverges_from_estimate(api):
    """PRD §3.6: "Fourth, `final_total_cents` is the chargeable service part plus the
    add-on part, minus the floored discount, plus the retail part. This finalized total
    generally differs from the provisional `estimate_total_cents` for the same set of
    lines."

    Design: Difficulty/dual_variant_calc/visit_estimate_vs_final_settlement_diverge
    """
    s = th.setup_divergence_visit(tier="SILVER", package_eligible=True)
    completed = th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    # SILVER credit zeroes service; discount over addon 1500 only = floor(1500*1000/10000)=150;
    # final = 0 + 1500 - 150 + 3000 = 4350. Estimate was 6500.
    assert completed["final_total_cents"] == 4350, (
        f"expected final 4350, got {completed['final_total_cents']}"
    )
    assert completed["estimate_total_cents"] == 6500
    assert completed["final_total_cents"] != completed["estimate_total_cents"]
    assert completed["used_package_credit"] is True


# ===========================================================================
# Difficulty A: combinatorial_formula / settlement_credit_then_discount_nonlinear_branch
# ===========================================================================
def test_credit_then_discount_nonlinear_final_total(api):
    """PRD §3.6: "the credit decision, evaluated before the discount: if the visit
    carries a `membership_package_id`, the package is `ACTIVE`, the visit's service is
    `package_eligible`, and the package's `credits_remaining` is greater than zero,
    then `used_package_credit` is set true, the service line is charged at zero ... and
    the package's `credits_remaining` is decremented by one."

    Design: Difficulty/combinatorial_formula/settlement_credit_then_discount_nonlinear_branch
    """
    s = th.setup_divergence_visit(tier="SILVER", package_eligible=True)
    completed = th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    assert completed["final_total_cents"] == 4350
    pkg_after = validate_success(api.get_package(s["package"]["id"], MANAGER))
    # SILVER starts with 8 credits; one drawn at completion -> 7.
    assert pkg_after["credits_remaining"] == 7, (
        f"expected 7 credits remaining, got {pkg_after['credits_remaining']}"
    )


def test_retail_never_discounted_in_settlement(api):
    """PRD §3.6: "First, the discountable base is the service part plus the add-on part;
    retail is never discounted."
    PRD §3.6: "Fourth, `final_total_cents` is the chargeable service part plus the
    add-on part, minus the floored discount, plus the retail part."

    Design: Difficulty/combinatorial_formula/settlement_credit_then_discount_nonlinear_branch
    """
    # SILVER credit zeroes the service; discount touches addon only (150); the SERUM
    # retail 3000 passes through undiscounted and is added back whole: 0+1500-150+3000=4350.
    s = th.setup_divergence_visit(tier="SILVER", package_eligible=True)
    completed = th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    assert completed["final_total_cents"] == 4350
    # The retail 3000 component is the dominant term and is never discounted.
    assert completed["final_total_cents"] - 3000 == 1350


# ===========================================================================
# Difficulty A: combinatorial_formula / loyalty_earn_floor_rounding_order_pinned
# ===========================================================================
def test_loyalty_earn_per_step_floor_after_discount(api):
    """PRD §3.6: "The `loyalty_earned` figure is computed by taking `final_total_cents`
    divided by 100 to express it in whole dollars, multiplying by the salon's
    `loyalty_earn_rate_bps`, dividing by 100, and flooring the result to a whole number
    of points."

    Design: Difficulty/combinatorial_formula/loyalty_earn_floor_rounding_order_pinned
    """
    # GOLD package but service NOT package_eligible -> no credit; discount over
    # service+addon. service 2000 + addon 1500 = 3500; discount floor(3500*1500/10000)=525;
    # final = 2000 + 1500 - 525 + 3000(retail) = 5975. earn = floor(5975/100 * 500/100)
    # = floor(59.75*5) = floor(298.75) = 298.
    s = th.setup_divergence_visit(tier="GOLD", package_eligible=False, loyalty_earn_rate_bps=500)
    completed = th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    assert completed["final_total_cents"] == 5975, (
        f"expected final 5975, got {completed['final_total_cents']}"
    )
    assert completed["loyalty_earned"] == 298, (
        f"expected loyalty_earned 298, got {completed['loyalty_earned']}"
    )
    assert completed["used_package_credit"] is False


def test_loyalty_earn_single_floor_not_sum_then_round(api):
    """PRD §2.8: "where a step divides — applying a basis-point discount or computing
    loyalty — the result is floored to a whole cent or whole point at that step, before
    the next step runs. Rounding is therefore per-step, never sum-then-round."

    Design: Difficulty/combinatorial_formula/loyalty_earn_floor_rounding_order_pinned
    """
    # final 5975 -> 5975/100 = 59.75 dollars; * 500bps/100 = 298.75 points; a single
    # floor at this step yields 298, distinct from any sum-then-round artefact.
    s = th.setup_divergence_visit(tier="GOLD", package_eligible=False, loyalty_earn_rate_bps=500)
    completed = th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    assert completed["final_total_cents"] == 5975
    assert completed["loyalty_earned"] == 298


# ===========================================================================
# Difficulty A: combinatorial_formula / estimate_evaluation_order_pinned_credit_before_discount
# ===========================================================================
def test_pinned_order_discount_applies_only_to_addon_after_credit(api):
    """PRD §3.6: "Third, the membership discount is applied to whatever service-plus-
    add-on remains chargeable after the credit decision: if a package is set and
    `ACTIVE`, the discount in cents is the chargeable service part plus the add-on part,
    multiplied by the package's `discount_bps`, divided by ten thousand, with the
    quotient floored to a whole cent."

    Design: Difficulty/combinatorial_formula/estimate_evaluation_order_pinned_credit_before_discount
    """
    # With the SILVER credit drawn the service line is free, so discount applies only to
    # the addon part (1500), giving 150 not 350; final = 0 + 1500 - 150 + 3000 = 4350.
    s = th.setup_divergence_visit(tier="SILVER", package_eligible=True)
    completed = th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    assert completed["final_total_cents"] == 4350, (
        f"expected final 4350 (credit-before-discount), got {completed['final_total_cents']}"
    )


def test_credit_decision_pinned_before_discount_sets_used_credit(api):
    """PRD §3.6: "Second comes the credit decision, evaluated before the discount: if
    the visit carries a `membership_package_id`, the package is `ACTIVE`, the visit's
    service is `package_eligible`, and the package's `credits_remaining` is greater than
    zero, then `used_package_credit` is set true, the service line is charged at zero
    because the credit covers it in full."

    Design: Difficulty/combinatorial_formula/estimate_evaluation_order_pinned_credit_before_discount
    """
    # The credit fires first (used_package_credit true, service charged 0), so the
    # subsequent discount can only see the addon part -> the pinned 4350 result.
    s = th.setup_divergence_visit(tier="SILVER", package_eligible=True)
    completed = th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    assert completed["used_package_credit"] is True
    assert completed["final_total_cents"] == 4350


# ===========================================================================
# Difficulty A: non_linear_state_machine / visit_parallel_service_payment_dimensions
# ===========================================================================
def test_visit_completes_then_settles_on_independent_dimensions(api):
    """PRD §3.7: "The payment status of a visit begins `UNPAID` and may advance to
    `SETTLED` ... it advances independently of the service dimension except for one
    cross-dimension guard: a visit may only be settled once its `service_status` is
    `COMPLETED`."

    Design: Difficulty/non_linear_state_machine/visit_parallel_service_payment_dimensions
    """
    s = th.setup_seated_visit()  # no package, service base 2000
    completed = th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    assert completed["service_status"] == "COMPLETED"
    assert completed["payment_status"] == "UNPAID"
    settled = th.settle_visit(s["visit"]["id"])
    assert settled["service_status"] == "COMPLETED"
    assert settled["payment_status"] == "SETTLED"
    assert settled["final_total_cents"] == 2000


def test_completed_visit_stays_unpaid_until_settle(api):
    """PRD §3.6: "Completion is performed by the `Technician` (or a `FrontDeskAgent`),
    moving the visit's `service_status` from `IN_SERVICE` to `COMPLETED`."
    PRD §3.7: "A `FrontDeskAgent` or `SalonManager` settles a completed visit, moving
    `payment_status` from `UNPAID` to `SETTLED`."

    Design: Difficulty/non_linear_state_machine/visit_parallel_service_payment_dimensions
    """
    s = th.setup_seated_visit()
    completed = th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    # Service dimension advanced; payment dimension untouched.
    assert completed["service_status"] == "COMPLETED"
    assert completed["payment_status"] == "UNPAID"


# ===========================================================================
# Difficulty A: boundary_precision_check / settle_redeem_equals_full_balance_zero_floor
# ===========================================================================
def test_settle_redeem_full_balance_succeeds(api):
    """PRD §3.7: "The points redeemed must not exceed the member's current
    `loyalty_balance`; a request to redeem more than the balance is refused with
    `ERR_INSUFFICIENT_LOYALTY`."
    PRD §3.7: "This earn is computed before any settle-time redemption: a redemption
    reduces the cash a guest owes at settle, never the points they earn from the visit."

    Design: Difficulty/boundary_precision_check/settle_redeem_equals_full_balance_zero_floor
    """
    s = th.setup_seated_visit(loyalty_earn_rate_bps=500)
    member = s["member"]
    # Grant exactly 300 points via a manager ADJUSTMENT.
    validate_success(
        api.create_loyalty_adjustment(
            member["id"], th.create_loyalty_adjustment_payload(300), MANAGER
        ),
        201,
    )
    th.complete_visit(s["visit"]["id"], s["tech"]["id"])  # final 2000, earn 100
    settled = th.settle_visit(s["visit"]["id"], redeem_points=300)
    assert settled["payment_status"] == "SETTLED"
    reread = validate_success(api.get_member(member["id"], FRONT_DESK))
    # 300 granted - 300 redeemed + 100 earned = 100.
    assert reread["loyalty_balance"] == 100, (
        f"expected balance 100, got {reread['loyalty_balance']}"
    )


def test_settle_redeem_over_balance_rejected(api):
    """PRD §3.7: "The points redeemed must not exceed the member's current
    `loyalty_balance`; a request to redeem more than the balance is refused with
    `ERR_INSUFFICIENT_LOYALTY`."

    Design: Difficulty/boundary_precision_check/settle_redeem_equals_full_balance_zero_floor
    """
    s = th.setup_seated_visit(loyalty_earn_rate_bps=500)
    member = s["member"]
    validate_success(
        api.create_loyalty_adjustment(
            member["id"], th.create_loyalty_adjustment_payload(300), MANAGER
        ),
        201,
    )
    th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    resp = api.settle_service_visit(
        s["visit"]["id"], FRONT_DESK, {"redeem_points": 301}
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_LOYALTY.value, expected_status=402)


# ===========================================================================
# Corner B: calculations / visit_no_package_full_price_final
# ===========================================================================
def test_visit_no_package_full_price_final(api):
    """PRD §3.6: "otherwise `used_package_credit` is false and the service line is
    charged at its full `base_price_cents`."
    PRD §3.6: "if no active package applies, the discount is zero."

    Design: Corner/calculations/visit_no_package_full_price_final
    """
    s = th.setup_seated_visit(loyalty_earn_rate_bps=500)  # no package
    completed = th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    assert completed["final_total_cents"] == 2000
    assert completed["loyalty_earned"] == 100  # floor(2000/100 * 500/100) = 100
    assert completed["used_package_credit"] is False


# ===========================================================================
# Corner B: calculations / estimate_recomputes_on_line_void
# ===========================================================================
def test_estimate_recomputes_on_line_void(api):
    """PRD §3.5: "The provisional `estimate_total_cents` ... recomputed whenever an
    `ACTIVE` line is added or voided while the visit is `IN_SERVICE`."
    PRD §3.5: "the void moves the line from `ACTIVE` to `VOIDED`, excludes it from the
    recomputed estimate, and, if the line was `RETAIL`, restores its `quantity` back to
    the product's `stock_qty`."

    Design: Corner/calculations/estimate_recomputes_on_line_void
    """
    s = th.setup_seated_visit()  # service base 2000
    salon, visit = s["salon"], s["visit"]
    serum = th.add_retail_product(salon["id"], unit_price_cents=3000, initial_stock_qty=10)
    line = th.add_retail_line(visit["id"], serum["id"], quantity=1)
    seeded = validate_success(api.get_service_visit(visit["id"], FRONT_DESK))
    assert seeded["estimate_total_cents"] == 5000  # 2000 + 3000
    voided = validate_success(api.void_line_item(line["id"], FRONT_DESK))
    assert voided["status"] == "VOIDED"
    after = validate_success(api.get_service_visit(visit["id"], FRONT_DESK))
    assert after["estimate_total_cents"] == 2000  # retail line excluded
    prod = validate_success(api.get_retail_product(serum["id"], MANAGER))
    assert prod["stock_qty"] == 10  # restored


# ===========================================================================
# Corner B: calculations / line_item_unit_price_snapshot
# ===========================================================================
def test_line_item_unit_price_snapshot(api):
    """PRD §3.5: "Each line records an immutable `unit_price_cents` snapshot of the
    referenced item's price at the moment it was added, and a derived `line_total_cents`
    equal to that snapshot multiplied by `quantity`."

    Design: Corner/calculations/line_item_unit_price_snapshot
    """
    s = th.setup_seated_visit(certified_addon_codes=["TINT"])
    salon, visit, tech = s["salon"], s["visit"], s["tech"]
    tint = th.add_add_on(salon["id"], code="TINT", price_cents=1500, requires_certification=True)
    line = th.add_addon_line(visit["id"], tint["id"], tech["id"], quantity=1)
    assert line["unit_price_cents"] == 1500
    assert line["line_total_cents"] == 1500


# ===========================================================================
# Corner B: state_machines / complete_already_completed_visit_invalid_from
# ===========================================================================
def test_complete_already_completed_visit_rejected(api):
    """PRD §3.6: "the visit must be `IN_SERVICE` to complete, else
    `ERR_VISIT_NOT_IN_SERVICE`."

    Design: Corner/state_machines/complete_already_completed_visit_invalid_from
    """
    s = th.setup_seated_visit()
    th.complete_visit(s["visit"]["id"], s["tech"]["id"])
    resp = api.complete_service_visit(
        s["visit"]["id"], make_technician_headers(s["tech"]["id"])
    )
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_IN_SERVICE.value, expected_status=409)


# ===========================================================================
# Corner B: state_machines / settle_before_complete_rejected_cross_dimension_guard
# ===========================================================================
def test_settle_before_complete_rejected(api):
    """PRD §3.7: "Settling a visit whose service is not yet `COMPLETED` is rejected with
    `ERR_VISIT_NOT_COMPLETED`."

    Design: Corner/state_machines/settle_before_complete_rejected_cross_dimension_guard
    """
    s = th.setup_seated_visit()  # IN_SERVICE / UNPAID
    resp = api.settle_service_visit(s["visit"]["id"], FRONT_DESK, {})
    validate_error(resp, ApiErrorId.ERR_VISIT_NOT_COMPLETED.value, expected_status=409)


# ===========================================================================
# Corner B: validations / addon_requires_certified_technician
# ===========================================================================
def test_addon_requires_certified_technician(api):
    """PRD §3.5: "when the referenced add-on's `requires_certification` is true, the
    visit's assigned technician must list that add-on's `code` among their
    `certified_addon_codes`, otherwise the line is refused with `ERR_TECH_NOT_CERTIFIED`."

    Design: Corner/validations/addon_requires_certified_technician
    """
    s = th.setup_seated_visit(certified_addon_codes=[])  # technician NOT certified
    salon, visit, tech = s["salon"], s["visit"], s["tech"]
    tint = th.add_add_on(salon["id"], code="TINT", price_cents=1500, requires_certification=True)
    resp = api.add_line_item(
        visit["id"],
        th.create_line_item_payload("ADDON", tint["id"], quantity=1),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_TECH_NOT_CERTIFIED.value, expected_status=409)


# ===========================================================================
# Corner B: validations / retail_line_exceeds_stock_rejected
# ===========================================================================
def test_retail_line_exceeds_stock_rejected(api):
    """PRD §3.5: "A `RETAIL` line may have a quantity greater than one, but it must not
    exceed the product's on-hand `stock_qty`; a request for more units than are in stock
    is rejected with `ERR_INSUFFICIENT_STOCK`."

    Design: Corner/validations/retail_line_exceeds_stock_rejected
    """
    s = th.setup_seated_visit()
    salon, visit = s["salon"], s["visit"]
    serum = th.add_retail_product(salon["id"], unit_price_cents=3000, initial_stock_qty=3)
    resp = api.add_line_item(
        visit["id"], th.create_line_item_payload("RETAIL", serum["id"], quantity=5), FRONT_DESK
    )
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value, expected_status=409)
    prod = validate_success(api.get_retail_product(serum["id"], MANAGER))
    assert prod["stock_qty"] == 3  # unchanged


# ===========================================================================
# Corner B: validations / addon_quantity_not_one_rejected
# ===========================================================================
def test_addon_quantity_not_one_rejected(api):
    """PRD §3.5: "An `ADDON` line must have a quantity of exactly one; any other add-on
    quantity, or any quantity below one, is rejected with `ERR_INVALID_LINE_QUANTITY`."

    Design: Corner/validations/addon_quantity_not_one_rejected
    """
    s = th.setup_seated_visit(certified_addon_codes=["TINT"])
    salon, visit, tech = s["salon"], s["visit"], s["tech"]
    tint = th.add_add_on(salon["id"], code="TINT", price_cents=1500, requires_certification=True)
    resp = api.add_line_item(
        visit["id"],
        th.create_line_item_payload("ADDON", tint["id"], quantity=2),
        make_technician_headers(tech["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_LINE_QUANTITY.value, expected_status=409)


# ===========================================================================
# Corner B: validations / line_type_mismatch_rejected
# ===========================================================================
def test_line_type_mismatch_rejected(api):
    """PRD §3.5: "If the `line_type` does not match the kind of entity the `item_ref_id`
    actually resolves to, the line is rejected with `ERR_LINE_TYPE_MISMATCH`."

    Design: Corner/validations/line_type_mismatch_rejected
    """
    s = th.setup_seated_visit()
    salon, visit = s["salon"], s["visit"]
    serum = th.add_retail_product(salon["id"], unit_price_cents=3000, initial_stock_qty=10)
    # line_type ADDON but item_ref_id points at a RetailProduct.
    resp = api.add_line_item(
        visit["id"], th.create_line_item_payload("ADDON", serum["id"], quantity=1), FRONT_DESK
    )
    validate_error(resp, ApiErrorId.ERR_LINE_TYPE_MISMATCH.value, expected_status=409)
