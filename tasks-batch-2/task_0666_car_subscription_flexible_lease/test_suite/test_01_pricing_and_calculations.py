"""Pricing engine: tiered mileage overage, swap proration, early-cancel fee divergence,
eligibility scoring, and deposit waterfall — depth instances plus their corner siblings.

Each test rebuilds its own state from scratch (the server restarts before every test).
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_member_headers,
    fixtures as fx,
)


# =========================================================================== #
# dual_variant_calc                                                           #
# =========================================================================== #
def test_early_cancel_forward_quote_charges_half_of_remaining_months(api):
    """PRD §3.12: "The fee is the remaining full months multiplied by the plan's
    `monthly_fee_cents` multiplied by 0.50 (a fifty-percent penalty on the projected
    unfulfilled months), rounded half-up to whole cents."
    PRD §3.12: "The forward-looking mode reproduces the fee charged on an actual
    early cancellation."

    Design: Difficulty/dual_variant_calc/early_cancel_forward_vs_chronological_diverge
    """
    ctx = fx.setup_active_subscription()  # PLUS monthly 80000, min_term 6; ACTIVE since 2026-04-01
    fx.set_clock("2026-04-11T00:00:00Z")  # 10 days in; 0 full months elapsed
    sub_id = ctx["subscription"]["id"]
    appl_id = ctx["applicant"]["id"]

    resp = api.cancel_quote(sub_id, TEST_USERS["billing_admin_headers"], params={"mode": "FORWARD"})
    data = validate_success(resp)
    # remaining 6 months * 80000 * 0.50 = 240000
    assert data["fee_cents"] == 240000, f"expected forward fee 240000, got {data['fee_cents']}"


def test_early_cancel_forward_and_chronological_quotes_differ(api):
    """PRD §3.12: "For the very same subscription state the two modes deliberately
    produce different numbers, because one prices the unfulfilled future at half-fee
    while the other prices the unbilled remainder of the current cycle."

    Design: Difficulty/dual_variant_calc/early_cancel_forward_vs_chronological_diverge
    """
    ctx = fx.setup_active_subscription()
    fx.set_clock("2026-04-11T00:00:00Z")
    sub_id = ctx["subscription"]["id"]

    fwd = validate_success(api.cancel_quote(
        sub_id, TEST_USERS["billing_admin_headers"], params={"mode": "FORWARD"}))
    chrono = validate_success(api.cancel_quote(
        sub_id, TEST_USERS["billing_admin_headers"], params={"mode": "CHRONOLOGICAL"}))
    assert fwd["fee_cents"] != chrono["fee_cents"], (
        f"forward {fwd['fee_cents']} must differ from chronological {chrono['fee_cents']} "
        "for identical subscription state"
    )


def test_fleet_utilization_canonical_counts_reserved_and_assigned(api):
    """PRD §2.5: "so a fleet of four vehicles holding one `RESERVED` and one `ASSIGNED`
    reads `0.5000`."

    Design: Difficulty/dual_variant_calc/fleet_utilization_reservation_inclusive_vs_assignment_only
    """
    fleet = _build_fleet_one_reserved_one_assigned(api)
    data = validate_success(api.get_fleet(fleet["id"], TEST_USERS["fleet_operator_headers"]))
    assert data["utilization_pct"] == 0.5, f"expected 0.5, got {data['utilization_pct']}"


def test_fleet_utilization_assigned_only_basis_differs_from_canonical(api):
    """PRD §3.7: "Under the assignment-only basis, only `ASSIGNED` vehicles count, so
    the identical fleet reads `0.2500` — a different number for the same physical state."

    Design: Difficulty/dual_variant_calc/fleet_utilization_reservation_inclusive_vs_assignment_only
    """
    fleet = _build_fleet_one_reserved_one_assigned(api)
    canonical = validate_success(api.get_fleet(fleet["id"], TEST_USERS["fleet_operator_headers"]))
    proj = validate_success(api.get_fleet_utilization(
        fleet["id"], TEST_USERS["fleet_operator_headers"], params={"basis": "ASSIGNED_ONLY"}))
    assert proj["utilization_pct"] == 0.25, f"expected 0.25 assigned-only, got {proj['utilization_pct']}"
    assert canonical["utilization_pct"] != proj["utilization_pct"], (
        "canonical (0.5) must differ from ASSIGNED_ONLY projection (0.25)"
    )


def _build_fleet_one_reserved_one_assigned(api):
    """4-vehicle fleet: v1 RESERVED (a DRAFT sub assigned it), v2 ASSIGNED (an ACTIVE
    sub), v3/v4 AVAILABLE. Returns the fleet creation record."""
    fx.set_clock()
    plan = fx.create_plan()
    fleet = fx.create_fleet()
    v1 = fx.create_vehicle(fleet["id"], plan["id"])
    v2 = fx.create_vehicle(fleet["id"], plan["id"])
    fx.create_vehicle(fleet["id"], plan["id"])
    fx.create_vehicle(fleet["id"], plan["id"])
    ap1 = fx.create_applicant_eligible(plan["id"])
    ap2 = fx.create_applicant_eligible(plan["id"])
    # v2 -> ASSIGNED via a full activation
    sub2 = fx.create_subscription(ap2["id"], plan["id"])
    fx.assign_vehicle(sub2["id"], v2)
    courier = fx.create_courier(fleet["id"])
    fx.create_delivery_slot(courier["id"], sub2["id"])
    get_success_data(api.activate_subscription(sub2["id"], TEST_USERS["fleet_operator_headers"]))
    # v1 -> RESERVED only (DRAFT sub assigned, not activated)
    sub1 = fx.create_subscription(ap1["id"], plan["id"])
    fx.assign_vehicle(sub1["id"], v1)
    return fleet


# =========================================================================== #
# combinatorial_formula                                                       #
# =========================================================================== #
def test_mileage_overage_two_tier_selection_on_close(api):
    """PRD §3.6: "The overage is the tier-one miles multiplied by the plan's
    `overage_tier1_rate_cents` plus the tier-two miles multiplied by the plan's
    `overage_tier2_rate_cents`, rounded half-up to whole cents and stored as the
    cycle's `overage_cents`."

    Design: Difficulty/combinatorial_formula/mileage_overage_tiered_selection_mode_a
    """
    ctx = fx.setup_active_subscription(vehicle_overrides={"odometer_miles": 5000})
    cycle_id = fx.open_billing_cycle_id(ctx["subscription"]["id"])
    # delta 1500 -> billable 450 -> tier1 200*25 + tier2 250*38 = 5000 + 9500 = 14500
    data = validate_success(api.close_billing_cycle(
        cycle_id, {"odometer_end_miles": 6500}, TEST_USERS["billing_admin_headers"]))
    assert data["overage_cents"] == 14500, f"expected 14500, got {data['overage_cents']}"


def test_mileage_overage_close_posts_cycle_invoice_with_fee_plus_overage(api):
    """PRD §3.6: "Closing the cycle posts a `CYCLE` invoice whose amount is the plan's
    monthly fee plus this overage, adds that amount to the subscription's
    `lifetime_billed_cents`, and writes the reported reading back to the vehicle's
    `odometer_miles`."

    Design: Difficulty/combinatorial_formula/mileage_overage_tiered_selection_mode_a
    """
    ctx = fx.setup_active_subscription(vehicle_overrides={"odometer_miles": 5000})
    sub_id = ctx["subscription"]["id"]
    cycle_id = fx.open_billing_cycle_id(sub_id)
    get_success_data(api.close_billing_cycle(
        cycle_id, {"odometer_end_miles": 6500}, TEST_USERS["billing_admin_headers"]))
    invs, _ = fx._list(api.list_subscription_invoices(
        sub_id, TEST_USERS["billing_admin_headers"], params={"source_kind": "CYCLE"}))
    assert len(invs) == 1, f"expected exactly one CYCLE invoice, got {len(invs)}"
    # monthly_fee 80000 + overage 14500 == 94500
    assert invs[0]["amount_cents"] == 94500, f"expected 94500, got {invs[0]['amount_cents']}"


def test_swap_net_adjustment_fee_gated_on_swaps_used_before_increment(api):
    """PRD §3.9: "If the subscription's `swaps_used` is greater than or equal to the
    originating plan's `included_swaps_per_term`, the `swap_fee_applied_cents` is 7500
    cents; otherwise the swap is within the included allowance and `swap_fee_applied_cents`
    is 0."

    Design: Difficulty/combinatorial_formula/swap_net_adjustment_eval_order_mode_c
    """
    ctx = _setup_second_chargeable_swap(api)
    # second swap completed at 2026-04-19; swaps_used was 1 >= included 1 -> fee 7500
    sw = validate_success(api.complete_swap(ctx["sw2_id"], TEST_USERS["fleet_operator_headers"]))
    assert sw["swap_fee_applied_cents"] == 7500, (
        f"expected swap fee 7500 (swaps_used 1 >= included 1 before increment), "
        f"got {sw['swap_fee_applied_cents']}"
    )


def test_swap_net_adjustment_combines_proration_legs_and_fee(api):
    """PRD §3.9: "The `net_adjustment_cents` is the new-vehicle charge minus the
    old-vehicle credit plus the swap fee."

    Design: Difficulty/combinatorial_formula/swap_net_adjustment_eval_order_mode_c
    """
    ctx = _setup_second_chargeable_swap(api)
    sw = validate_success(api.complete_swap(ctx["sw2_id"], TEST_USERS["fleet_operator_headers"]))
    # remaining 12/30 of April; charge 95000*12/30=38000; credit 80000*12/30=32000; +7500
    assert sw["net_adjustment_cents"] == 13500, (
        f"expected net 13500 (38000 - 32000 + 7500), got {sw['net_adjustment_cents']}"
    )


def test_swap_completion_increments_swaps_used(api):
    """PRD §3.8: "The subscription's `active_vehicle_id` is set to the target, its
    `plan_id` is updated to the target vehicle's `plan_id`, and its `swaps_used`
    increases by one."

    Design: Difficulty/combinatorial_formula/swap_net_adjustment_eval_order_mode_c
    """
    ctx = _setup_second_chargeable_swap(api)
    get_success_data(api.complete_swap(ctx["sw2_id"], TEST_USERS["fleet_operator_headers"]))
    sub = validate_success(api.get_subscription(
        ctx["sub_id"], make_member_headers(ctx["appl_id"])))
    assert sub["swaps_used"] == 2, f"expected swaps_used 2 after two swaps, got {sub['swaps_used']}"


def _setup_second_chargeable_swap(api):
    """ACTIVE PLUS sub; one prior free swap done (swaps_used=1); a PREMIUM target
    reserved (approved) at clock 2026-04-19, ready to complete (chargeable)."""
    fx.set_clock()
    plus = fx.create_plan()
    prem = fx.create_premium_plan()
    fleet = fx.create_fleet()
    vA = fx.create_vehicle(fleet["id"], plus["id"])
    vB = fx.create_vehicle(fleet["id"], plus["id"])
    vC = fx.create_vehicle(fleet["id"], prem["id"])
    appl = fx.create_applicant_eligible(plus["id"])
    sub = fx.create_subscription(appl["id"], plus["id"])
    fx.assign_vehicle(sub["id"], vA)
    courier = fx.create_courier(fleet["id"])
    fx.create_delivery_slot(courier["id"], sub["id"])
    get_success_data(api.activate_subscription(sub["id"], TEST_USERS["fleet_operator_headers"]))
    # first free swap into vB (PLUS->PLUS); swaps_used 0 -> 1
    fx.perform_full_swap(sub["id"], appl["id"], vB["id"])
    # second swap into vC (PREMIUM) approved, completion at 2026-04-19
    sw2 = fx.request_swap(sub["id"], appl["id"], vC["id"])
    fx.approve_swap(sw2["id"], vC["id"])
    fx.set_clock("2026-04-19T00:00:00Z")
    return {"sub_id": sub["id"], "appl_id": appl["id"], "sw2_id": sw2["id"]}


# =========================================================================== #
# boundary_precision_check                                                    #
# =========================================================================== #
def test_mileage_overage_zero_at_included_plus_buffer_exact(api):
    """PRD §3.6: "The boundary is exact: a delta equal to the included allowance plus
    the buffer produces zero billable miles and zero overage, while a delta one mile
    larger bills exactly one mile."

    Design: Difficulty/boundary_precision_check/mileage_overage_zero_at_included_plus_buffer_exact
    """
    ctx = fx.setup_active_subscription(vehicle_overrides={"odometer_miles": 5000})
    cycle_id = fx.open_billing_cycle_id(ctx["subscription"]["id"])
    # delta exactly 1050 == included 1000 + buffer 50 -> 0 overage
    data = validate_success(api.close_billing_cycle(
        cycle_id, {"odometer_end_miles": 6050}, TEST_USERS["billing_admin_headers"]))
    assert data["overage_cents"] == 0, f"expected 0 overage at delta 1050, got {data['overage_cents']}"


def test_mileage_overage_zero_boundary_posts_monthly_fee_only_invoice(api):
    """PRD §3.6: "Closing the cycle posts a `CYCLE` invoice whose amount is the plan's
    monthly fee plus this overage, adds that amount to the subscription's
    `lifetime_billed_cents`, and writes the reported reading back to the vehicle's
    `odometer_miles`."

    Design: Difficulty/boundary_precision_check/mileage_overage_zero_at_included_plus_buffer_exact
    """
    ctx = fx.setup_active_subscription(vehicle_overrides={"odometer_miles": 5000})
    sub_id = ctx["subscription"]["id"]
    cycle_id = fx.open_billing_cycle_id(sub_id)
    get_success_data(api.close_billing_cycle(
        cycle_id, {"odometer_end_miles": 6050}, TEST_USERS["billing_admin_headers"]))
    invs, _ = fx._list(api.list_subscription_invoices(
        sub_id, TEST_USERS["billing_admin_headers"], params={"source_kind": "CYCLE"}))
    assert invs[0]["amount_cents"] == 80000, (
        f"expected 80000 (monthly fee only, no overage), got {invs[0]['amount_cents']}"
    )


def test_empty_fleet_utilization_reads_zero(api):
    """PRD §2.5: "A fleet's utilization is the fraction of its vehicles currently in use;
    when a fleet has no vehicles at all, its utilization is exactly 0 rather than an error
    or null, to avoid dividing by zero."

    Design: Difficulty/boundary_precision_check/empty_fleet_utilization_zero_not_divide_by_zero
    """
    fx.set_clock()
    fleet = fx.create_fleet(name="Empty", region_code="NV")
    data = validate_success(api.get_fleet(fleet["id"], TEST_USERS["fleet_operator_headers"]))
    assert data["total_vehicles"] == 0, f"expected 0 vehicles, got {data['total_vehicles']}"
    assert data["utilization_pct"] == 0, f"expected utilization 0, got {data['utilization_pct']}"


def test_empty_fleet_utilization_total_vehicles_zero(api):
    """PRD §3.1: "On creation a fleet's derived `total_vehicles`, `in_use_count`, and
    `utilization_pct` all initialize to 0."

    Design: Difficulty/boundary_precision_check/empty_fleet_utilization_zero_not_divide_by_zero
    """
    fx.set_clock()
    fleet = fx.create_fleet(name="Empty2", region_code="NV")
    data = validate_success(api.get_fleet(fleet["id"], TEST_USERS["fleet_operator_headers"]))
    assert data["in_use_count"] == 0
    assert data["total_vehicles"] == 0


# =========================================================================== #
# Corner: calculations                                                        #
# =========================================================================== #
def test_eligibility_approved_at_080_or_above_one_times_deposit(api):
    """PRD §3.3: "A score of at least 0.80 yields `APPROVED`, and the required deposit
    is the plan's `deposit_base_cents` multiplied by one."

    Design: Corner/calculations/eligibility_approved_boundary_at_080_inclusive
    """
    fx.set_clock()
    plan = fx.create_plan()  # PLUS monthly 80000, deposit_base 80000
    appl = fx.create_applicant(credit_score=720, monthly_income_cents=480000, history_flag="CLEAN")
    data = validate_success(api.decide_eligibility(
        appl["id"], {"plan_id": plan["id"]}, TEST_USERS["billing_admin_headers"]))
    assert data["eligibility_score"] == 0.8818, f"expected score 0.8818, got {data['eligibility_score']}"
    assert data["eligibility_status"] == "APPROVED"
    assert data["required_deposit_cents"] == 80000, f"expected 80000 (1x), got {data['required_deposit_cents']}"


def test_eligibility_conditional_at_060_boundary_two_times_deposit(api):
    """PRD §3.3: "A score from 0.60 up to but not including 0.80 yields `CONDITIONAL`,
    and the required deposit is `deposit_base_cents` multiplied by two."

    Design: Corner/calculations/eligibility_conditional_at_060_boundary_2x_deposit
    """
    fx.set_clock()
    plan = fx.create_plan()
    appl = fx.create_applicant(credit_score=410, monthly_income_cents=480000, history_flag="CLEAN")
    data = validate_success(api.decide_eligibility(
        appl["id"], {"plan_id": plan["id"]}, TEST_USERS["billing_admin_headers"]))
    assert data["eligibility_score"] == 0.6, f"expected score 0.6, got {data['eligibility_score']}"
    assert data["eligibility_status"] == "CONDITIONAL"
    assert data["required_deposit_cents"] == 160000, f"expected 160000 (2x), got {data['required_deposit_cents']}"


def test_mileage_overage_one_mile_over_buffer_bills_one_tier1_mile(api):
    """PRD §3.6: "The boundary is exact: a delta equal to the included allowance plus
    the buffer produces zero billable miles and zero overage, while a delta one mile
    larger bills exactly one mile."

    Design: Corner/calculations/mileage_overage_one_mile_over_buffer_bills_25c
    """
    ctx = fx.setup_active_subscription(vehicle_overrides={"odometer_miles": 5000})
    cycle_id = fx.open_billing_cycle_id(ctx["subscription"]["id"])
    # delta 1051 -> 1 billable mile at tier1 25c -> 25
    data = validate_success(api.close_billing_cycle(
        cycle_id, {"odometer_end_miles": 6051}, TEST_USERS["billing_admin_headers"]))
    assert data["overage_cents"] == 25, f"expected 25 (1 mile tier1), got {data['overage_cents']}"


def test_deposit_waterfall_outstanding_exceeds_deposit(api):
    """PRD §3.11: "The `deposit_applied_cents` is the lesser of the subscription's
    `deposit_held_cents` and that outstanding amount. The `deposit_refunded_cents` is
    the held deposit minus the applied portion. The `balance_due_cents` is the
    outstanding amount minus the applied portion, and it is exactly this still-owed
    remainder that becomes the `RETURN_SETTLEMENT` invoice's amount."

    Design: Corner/calculations/deposit_waterfall_outstanding_exceeds_deposit_full_apply_balance_due
    """
    ctx = fx.setup_assessed_inspection(
        damage_items=[("SEVERE", 90000)], reported_odometer_miles=10)
    insp = validate_success(api.settle_inspection(
        ctx["inspection"]["id"], TEST_USERS["billing_admin_headers"]))
    # deposit 80000 vs outstanding 90000 -> applied 80000, refunded 0, balance 10000
    assert insp["deposit_applied_cents"] == 80000, f"got {insp['deposit_applied_cents']}"
    assert insp["deposit_refunded_cents"] == 0, f"got {insp['deposit_refunded_cents']}"
    assert insp["balance_due_cents"] == 10000, f"got {insp['balance_due_cents']}"
