"""Pricing, estimated & final settlement, claim settlement, driver risk.

Difficulty rules dual_variant_calc, combinatorial_formula, and the mileage
boundary; corner calculation instances. All expected values are copied verbatim
from the design indices and are floor-truncated integer cents (PRD §2.6, §3).
"""
from test_helpers import (
    validate_success, get_success_data,
    make_host_headers, make_guest_headers, make_admin_headers,
    register_host, register_verified_guest, create_plan, create_vehicle,
    add_active_pricing_rule, book_trip,
    setup_requested_trip, setup_checked_out_trip, setup_completed_trip,
    setup_claim_under_review, file_claim,
)

ADMIN = make_admin_headers()


# ---------------------------------------------------- Corner: length discount
def test_monthly_discount_wins_over_weekly(api):
    """PRD §3.4: "if `nights` is at least 28 the monthly discount fraction
    applies; otherwise if `nights` is at least 7 the weekly discount fraction
    applies; otherwise the discount is zero."

    Design: Corner/calculations/monthly_discount_selected_over_weekly
    """
    ctx = setup_requested_trip(api, start_date="2026-06-01", end_date="2026-06-29")
    trip = ctx["trip"]
    assert trip["nights"] == 28
    assert trip["discounted_subtotal_cents"] == 210000
    assert trip["protection_premium_cents"] == 70000
    assert trip["estimated_total_cents"] == 280000


def test_pricing_rule_override_applied_to_covered_nights(api):
    """PRD §3.2: "if an `ACTIVE` pricing rule on the vehicle has a closed
    interval containing that date, the rule's `daily_price_cents` applies for
    that night; otherwise the vehicle's `base_daily_price_cents` applies."

    Design: Corner/calculations/pricing_rule_override_applied_to_nights
    """
    host = register_host(api, name="Host CB", email="hcb@x.com")
    guest = register_verified_guest(api, license_number="DL-26", name="Guest CB", email="gcb@x.com")
    plan = create_plan(api)
    vehicle = create_vehicle(api, host["id"])
    add_active_pricing_rule(api, host["id"], vehicle["id"], "2026-06-01", "2026-06-03", 20000)
    api.list_vehicle(vehicle["id"], make_host_headers(host["id"]))
    trip = book_trip(api, vehicle["id"], guest["id"], plan["id"], "2026-06-01", "2026-06-04")
    assert trip["nights"] == 3
    assert trip["discounted_subtotal_cents"] == 60000
    assert trip["estimated_total_cents"] == 67500


# ------------------------------------------------------ Corner: late fee, claim
def test_late_return_fee_and_counter(api):
    """PRD §3.6: "The `late_fee_cents` is `late_days` multiplied by the floor of
    the vehicle's `base_daily_price_cents` times a late-fee multiplier of 1.5."
    PRD §3.6: "If `late_days` is greater than zero, the guest's
    `late_return_count` increases by one at check-out."

    Design: Corner/calculations/late_return_fee_applied
    """
    ctx = setup_checked_out_trip(api, checkout_odometer=10500, checkout_fuel_pct=100,
                                 checkout_clock="2026-06-10T12:00:00Z")
    trip = ctx["trip"]
    assert trip["late_days"] == 2
    assert trip["late_fee_cents"] == 30000
    assert trip["final_total_cents"] == 110500
    guest = get_success_data(api.get_guest(ctx["guest"]["id"], ADMIN))
    assert guest["late_return_count"] == 1


def test_claim_coverage_cap_and_uncovered_remainder(api):
    """PRD §3.8: "`covered_amount_cents` is the smaller of the assessed
    `damage_amount_cents` and the plan's `coverage_limit_cents`;
    `guest_deductible_cents` is the smaller of the plan's `deductible_cents` and
    the `covered_amount_cents`; `host_recovery_cents` equals the
    `covered_amount_cents`; and `uncovered_cents` is the larger of zero and the
    assessed `damage_amount_cents` minus the `covered_amount_cents`."

    Design: Corner/calculations/claim_coverage_cap_uncovered_remainder
    """
    ctx = setup_claim_under_review(api, damage_amount_cents=2000000)
    claim = get_success_data(api.approve_claim(ctx["claim"]["id"], ADMIN, {"resolution_note": "capped"}))
    assert claim["covered_amount_cents"] == 1500000
    assert claim["host_recovery_cents"] == 1500000
    assert claim["guest_deductible_cents"] == 100000
    assert claim["uncovered_cents"] == 500000


# ------------------------------- Difficulty: discount rounding order (sum first)
def test_discount_rounding_order_sums_before_floor(api):
    """PRD §3.4: "the discount is applied to the already-summed subtotal, not to
    each night individually: `discounted_subtotal_cents` is the floor of the
    rental subtotal multiplied by one minus the chosen discount fraction."

    Design: Difficulty/combinatorial_formula/estimate_discount_rounding_order_sum_first
    """
    ctx = setup_requested_trip(api, vehicle_overrides={"base_daily_price_cents": 333})
    assert ctx["trip"]["discounted_subtotal_cents"] == 2097


def test_discount_rounding_order_flows_to_total_and_earnings(api):
    """PRD §3.4: "The provisional guest charge, `estimated_total_cents`, is
    `discounted_subtotal_cents` plus `protection_premium_cents`. The provisional
    host earnings, `estimated_host_earnings_cents`, is the floor of
    `discounted_subtotal_cents` times the plan's `host_earnings_pct`."

    Design: Difficulty/combinatorial_formula/estimate_discount_rounding_order_sum_first
    """
    ctx = setup_requested_trip(api, vehicle_overrides={"base_daily_price_cents": 333})
    trip = ctx["trip"]
    assert trip["estimated_total_cents"] == 19597
    assert trip["estimated_host_earnings_cents"] == 1677


# -------------------------- Difficulty: nested min/max claim settlement formula
def test_claim_settlement_nested_min_covered_and_recovery(api):
    """PRD §3.8: "`covered_amount_cents` is the smaller of the assessed
    `damage_amount_cents` and the plan's `coverage_limit_cents` ...
    `host_recovery_cents` equals the `covered_amount_cents`"

    Design: Difficulty/combinatorial_formula/claim_settlement_nested_min_max
    """
    ctx = setup_claim_under_review(api, damage_amount_cents=200000)
    claim = get_success_data(api.approve_claim(ctx["claim"]["id"], ADMIN, {"resolution_note": "approved"}))
    assert claim["covered_amount_cents"] == 200000
    assert claim["host_recovery_cents"] == 200000


def test_claim_settlement_nested_min_deductible_and_uncovered(api):
    """PRD §3.8: "`guest_deductible_cents` is the smaller of the plan's
    `deductible_cents` and the `covered_amount_cents` ... and `uncovered_cents`
    is the larger of zero and the assessed `damage_amount_cents` minus the
    `covered_amount_cents`."

    Design: Difficulty/combinatorial_formula/claim_settlement_nested_min_max
    """
    ctx = setup_claim_under_review(api, damage_amount_cents=200000)
    claim = get_success_data(api.approve_claim(ctx["claim"]["id"], ADMIN, {"resolution_note": "approved"}))
    assert claim["guest_deductible_cents"] == 100000
    assert claim["uncovered_cents"] == 0


# ------------------------- Difficulty: estimate vs final diverge (dual variant)
def test_estimate_and_final_totals_diverge(api):
    """PRD §3.6: "The guest's actual charge, `final_total_cents`, is
    `discounted_subtotal_cents` plus `protection_premium_cents` plus
    `mileage_fee_cents` plus `fuel_fee_cents` plus `late_fee_cents`."

    Design: Difficulty/dual_variant_calc/trip_cost_estimate_vs_final_diverge
    """
    ctx = setup_checked_out_trip(api, checkout_odometer=11600, checkout_fuel_pct=80)
    trip = ctx["trip"]
    assert trip["estimated_total_cents"] == 80500
    assert trip["final_total_cents"] == 100500


def test_final_settlement_incidental_fees_and_host_earnings(api):
    """PRD §3.6: "The host's actual earnings, `final_host_earnings_cents`, is
    `estimated_host_earnings_cents` plus those same three incidental fees — the
    host keeps the full mileage, fuel, and late charges on top of the locked
    base earnings."

    Design: Difficulty/dual_variant_calc/trip_cost_estimate_vs_final_diverge
    """
    ctx = setup_checked_out_trip(api, checkout_odometer=11600, checkout_fuel_pct=80)
    trip = ctx["trip"]
    assert trip["mileage_fee_cents"] == 10000
    assert trip["fuel_fee_cents"] == 10000
    assert trip["final_host_earnings_cents"] == 70400


# ---------------- Difficulty: driver risk provisional vs finalized (dual variant)
def test_driver_risk_finalized_after_at_fault_claim_settled(api):
    """PRD §3.8: "if the claim was filed by the host (`claimant` is `HOST`), the
    guest's `at_fault_claim_count` increases by one and the guest's
    `driver_risk_score` is recomputed in its finalized form."
    PRD §3.8: "The `driver_risk_score` is a 0-to-100 reputation figure equal to
    the smaller of 100 and the sum of the guest's `at_fault_claim_count` times
    20 plus the guest's `late_return_count` times 5."

    Design: Difficulty/dual_variant_calc/guest_risk_provisional_vs_finalized
    """
    ctx = setup_completed_trip(api)
    claim = file_claim(api, ctx, claimant="HOST", damage_amount_cents=200000)
    api.start_review_claim(claim["id"], ADMIN)
    api.approve_claim(claim["id"], ADMIN, {"resolution_note": "ok"})
    api.settle_claim(claim["id"], ADMIN)
    guest = get_success_data(api.get_guest(ctx["guest"]["id"], ADMIN))
    assert guest["at_fault_claim_count"] == 1
    assert guest["driver_risk_score"] == 20


def test_driver_risk_provisional_zero_at_booking(api):
    """PRD §3.8: "Read at booking time it is **provisional** — it reflects only
    outcomes from trips already `COMPLETED` and claims already `SETTLED` before
    this booking, excluding the in-flight trip."
    PRD §3.3: "begins with `verification_status` of `UNVERIFIED`, a
    `driver_risk_score` of 0"

    Design: Difficulty/dual_variant_calc/guest_risk_provisional_vs_finalized
    """
    ctx = setup_requested_trip(api)
    guest = get_success_data(api.get_guest(ctx["guest"]["id"], ADMIN))
    assert guest["driver_risk_score"] == 0


# ----------------------------- Difficulty: mileage overage boundary (exact / +1)
def test_mileage_fee_zero_at_exact_allowance(api):
    """PRD §3.6: "Overage miles is the larger of zero and miles driven minus
    allowed miles — only miles strictly beyond the allowance are charged — and
    `mileage_fee_cents` is those overage miles multiplied by 50 cents per mile."

    Design: Difficulty/boundary_precision_check/mileage_overage_at_exact_limit
    """
    ctx = setup_checked_out_trip(api, checkout_odometer=11400, checkout_fuel_pct=100)
    trip = ctx["trip"]
    assert trip["mileage_fee_cents"] == 0
    assert trip["fuel_fee_cents"] == 0
    assert trip["late_fee_cents"] == 0
    assert trip["final_total_cents"] == 80500


def test_mileage_fee_charged_one_mile_over_allowance(api):
    """PRD §3.6: "Overage miles is the larger of zero and miles driven minus
    allowed miles — only miles strictly beyond the allowance are charged — and
    `mileage_fee_cents` is those overage miles multiplied by 50 cents per mile."

    Design: Difficulty/boundary_precision_check/mileage_overage_at_exact_limit
    """
    ctx = setup_checked_out_trip(api, checkout_odometer=11401, checkout_fuel_pct=100)
    trip = ctx["trip"]
    assert trip["mileage_fee_cents"] == 50
    assert trip["final_total_cents"] == 80550
