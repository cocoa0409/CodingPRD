"""Settlement waterfall: nested min/max branches, pinned rounding order, and
the revenue-guarantee floor boundary."""
from test_helpers import (
    validate_success, TEST_USERS,
    create_active_lease, set_clock, create_settlement,
    create_and_issue_settlement, offer_and_accept_lane,
)

ADMIN = TEST_USERS["lease_admin_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]


def _scenario_with_lane(**lease_overrides):
    """ACTIVE lease plus an ACCEPTED lane covering 2026-08-03 .. 2026-10-26."""
    scenario = create_active_lease(**lease_overrides)
    lane = offer_and_accept_lane(scenario["lease"]["id"], scenario["operator"]["id"])
    scenario["lane"] = lane
    return scenario


# ─── Queue A: difficulty/combinatorial_formula ───────

def test_waterfall_nested_min_max_provisional_lines(api):
    """PRD section 3.4: "step four takes the escrow contribution as the smallest
    of the scheduled `escrow_weekly_contribution_cents`, the remaining room under
    the lease's `escrow_cap_cents` (the cap minus the escrow account's current
    balance, floored at zero), and the funds remaining after step three — this
    becomes `escrow_contribution_cents`; step five applies the lease payment as
    the lesser of `weekly_payment_cents` and the funds remaining after escrow,
    producing `lease_payment_applied_cents`." PRD section 3.5: "For an eligible
    week, `guarantee_top_up_cents` is the larger of zero and the guarantee floor
    minus the week's gross revenue".

    Design: Difficulty/combinatorial_formula/waterfall_nested_min_max_guarantee_escrow_lease
    """
    scenario = _scenario_with_lane(escrow_cap_cents=45000)
    set_clock("2026-08-12T00:00:00Z")

    st = create_settlement(
        scenario["lease"]["id"], "2026-08-03",
        gross_revenue_cents=100000, fuel_gallons=200,
        fuel_price_cents_per_gallon=350, insurance_weekly_cents=22000,
        miles_driven=2500, load_declined_flag=False)

    assert st["guarantee_top_up_cents"] == 50000, "max(0, 150000-100000)"
    assert st["maintenance_deduction_cents"] == 31250, "round_half_up(2500*12.5)"
    assert st["fuel_deduction_cents"] == 70000
    assert st["escrow_contribution_cents"] == 20000, "min(20000, cap room 45000, remaining 26750)"
    assert st["lease_payment_applied_cents"] == 6750, "min(65000, remaining 6750 after escrow)"
    assert st["net_pay_cents"] == 0


def test_waterfall_nested_min_max_short_flag_at_finalize(api):
    """PRD section 3.4: "The waterfall reruns on the final basis,
    `payment_short_flag` is set true when the applied lease payment is less than
    `weekly_payment_cents`". PRD section 3.4: "a short payment increments
    `missed_payment_count` by one and adds the shortfall (the scheduled weekly
    payment minus the applied amount) to `arrears_cents`".

    Design: Difficulty/combinatorial_formula/waterfall_nested_min_max_guarantee_escrow_lease
    """
    scenario = _scenario_with_lane(escrow_cap_cents=45000)
    lease_id = scenario["lease"]["id"]
    set_clock("2026-08-12T00:00:00Z")

    st = create_and_issue_settlement(
        lease_id, "2026-08-03",
        gross_revenue_cents=100000, fuel_gallons=200,
        fuel_price_cents_per_gallon=350, insurance_weekly_cents=22000,
        miles_driven=2500, load_declined_flag=False)
    finalized = validate_success(api.finalize_settlement(st["id"], CLERK), 200)

    # Final basis: no COMPLETED operator-billed work orders -> maintenance 0.
    assert finalized["maintenance_deduction_cents"] == 0
    # funds 150000 - fuel 70000 - insurance 22000 - maint 0 - escrow 20000 = 38000
    assert finalized["escrow_contribution_cents"] == 20000
    assert finalized["lease_payment_applied_cents"] == 38000
    assert finalized["payment_short_flag"] is True, "38000 < 65000 weekly payment"
    assert finalized["net_pay_cents"] == 0

    lease = validate_success(api.get_lease_agreement(lease_id, ADMIN), 200)
    assert lease["missed_payment_count"] == 1
    assert lease["arrears_cents"] == 27000, "shortfall 65000 - 38000"
    assert lease["total_payments_applied_cents"] == 38000


def test_per_line_rounding_order_pinned(api):
    """PRD section 2.6: "Critically, every deduction line on a settlement is
    rounded to whole cents individually before any summation takes place, and the
    settlement waterfall sums those already-rounded integer-cent lines; summing
    first and rounding the total is forbidden."

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_pinned
    """
    scenario = create_active_lease()
    set_clock("2026-08-12T00:00:00Z")

    st = create_settlement(
        scenario["lease"]["id"], "2026-08-03",
        gross_revenue_cents=250000, fuel_gallons=100.5,
        fuel_price_cents_per_gallon=333, insurance_weekly_cents=22000,
        miles_driven=1041, load_declined_flag=False)

    assert st["fuel_deduction_cents"] == 33467, "round_half_up(100.5*333 = 33466.5)"
    assert st["maintenance_deduction_cents"] == 13013, "round_half_up(1041*12.5 = 13012.5)"
    assert st["fuel_deduction_cents"] + st["maintenance_deduction_cents"] == 46480, (
        "round-per-line-then-sum; sum-then-round would give 46479")


def test_per_line_rounding_waterfall_uses_rounded_lines(api):
    """PRD section 2.6: "the settlement waterfall sums those already-rounded
    integer-cent lines; summing first and rounding the total is forbidden." PRD
    section 3.4: "Whatever survives step five is the operator's `net_pay_cents`,
    never below zero."

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_pinned
    """
    scenario = create_active_lease()
    set_clock("2026-08-12T00:00:00Z")

    st = create_settlement(
        scenario["lease"]["id"], "2026-08-03",
        gross_revenue_cents=250000, fuel_gallons=100.5,
        fuel_price_cents_per_gallon=333, insurance_weekly_cents=22000,
        miles_driven=1041, load_declined_flag=False)

    assert st["escrow_contribution_cents"] == 20000
    assert st["lease_payment_applied_cents"] == 65000
    # 250000 - 33467 - 22000 - 13013 - 20000 - 65000 = 96520
    assert st["net_pay_cents"] == 96520


# ─── Queue A: difficulty/boundary_precision_check ────

def _two_boundary_week_settlements(scenario):
    """W1 at exactly the guarantee floor; W2 one cent below it."""
    lease_id = scenario["lease"]["id"]
    set_clock("2026-08-19T00:00:00Z")
    st_a = create_settlement(
        lease_id, "2026-08-03",
        gross_revenue_cents=150000, fuel_gallons=0, fuel_price_cents_per_gallon=350,
        insurance_weekly_cents=0, miles_driven=0, load_declined_flag=False)
    st_b = create_settlement(
        lease_id, "2026-08-10",
        gross_revenue_cents=149999, fuel_gallons=0, fuel_price_cents_per_gallon=350,
        insurance_weekly_cents=0, miles_driven=0, load_declined_flag=False)
    return st_a, st_b


def test_guarantee_exact_gross_boundary_at_floor(api):
    """PRD section 3.5: "For an eligible week, `guarantee_top_up_cents` is the
    larger of zero and the guarantee floor minus the week's gross revenue; when
    gross revenue equals or exceeds `min_revenue_guarantee_weekly_cents`, the
    top-up is zero."

    Design: Difficulty/boundary_precision_check/guarantee_exact_gross_boundary
    """
    scenario = _scenario_with_lane()
    st_a, _ = _two_boundary_week_settlements(scenario)
    assert st_a["guarantee_top_up_cents"] == 0, "gross == floor: max(0, 150000-150000)"
    assert st_a["net_pay_cents"] == 65000, "150000 - 20000 escrow - 65000 lease"


def test_guarantee_one_cent_below_floor(api):
    """PRD section 3.5: "For an eligible week, `guarantee_top_up_cents` is the
    larger of zero and the guarantee floor minus the week's gross revenue; when
    gross revenue equals or exceeds `min_revenue_guarantee_weekly_cents`, the
    top-up is zero."

    Design: Difficulty/boundary_precision_check/guarantee_exact_gross_boundary
    """
    scenario = _scenario_with_lane()
    st_a, st_b = _two_boundary_week_settlements(scenario)
    assert st_b["guarantee_top_up_cents"] == 1, "gross one cent below floor: max(0, 1)"
    assert st_b["net_pay_cents"] == 65000, (
        "149999 + 1 - 20000 - 65000: identical net to the at-floor week, "
        "different composition")
    assert st_a["net_pay_cents"] == st_b["net_pay_cents"]


# ─── Queue B: corner/calculations ────────────────────

def test_declined_load_voids_guarantee(api):
    """PRD section 3.5: "A week is guarantee-eligible when three facts all hold:
    the lease is `ACTIVE` (a `DEFAULTED` lease forfeits the guarantee), the
    week's `load_declined_flag` is false (an operator who declined a dispatched
    load voids that week's guarantee), and at least one lane assignment of the
    lease is `ACCEPTED` with a window covering the `week_start_date`".

    Design: Corner/calculations/declined_load_voids_guarantee
    """
    scenario = _scenario_with_lane()
    lease_id = scenario["lease"]["id"]
    set_clock("2026-08-19T00:00:00Z")

    st_ok = create_settlement(
        lease_id, "2026-08-03",
        gross_revenue_cents=100000, fuel_gallons=0, fuel_price_cents_per_gallon=350,
        insurance_weekly_cents=0, miles_driven=0, load_declined_flag=False)
    st_declined = create_settlement(
        lease_id, "2026-08-10",
        gross_revenue_cents=100000, fuel_gallons=0, fuel_price_cents_per_gallon=350,
        insurance_weekly_cents=0, miles_driven=0, load_declined_flag=True)

    assert st_ok["guarantee_top_up_cents"] == 50000, "eligible week: max(0, 150000-100000)"
    assert st_declined["guarantee_top_up_cents"] == 0, "declined load voids the guarantee"
