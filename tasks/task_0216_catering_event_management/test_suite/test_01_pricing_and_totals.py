"""Pricing-engine tests: marginal headcount charge, the pinned grand-total assembly,
round-per-component rounding, tax/gratuity input filtering, deposit tiers, the guarantee
floor, change fees, and per-head-scaled staffing.

Each test drives an order to the lifecycle point where a computed total becomes observable
and asserts the literal cents the PRD's pinned formula produces.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    TEST_USERS,
    make_client_headers,
    create_package_payload,
    create_venue_payload,
    create_client_payload,
    create_order_payload,
    create_add_on_payload,
)
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["admin_headers"]
COORD = TEST_USERS["coordinator_headers"]


# =====================================================================
# Queue A — Rule 1: dual-variant calculation
# =====================================================================
def test_provisional_and_final_totals_diverge_on_guarantee_floor(api):
    """PRD §3.4: "The provisional pass uses the order's `booked_headcount`. The final pass
    uses the effective headcount, which embodies the final-count guarantee: the client is
    billed for at least 90 percent of the headcount booked at confirmation even if they
    guarantee fewer guests."
    PRD §3.4: "The effective headcount is the larger of the guaranteed headcount and a floor
    equal to the booked headcount multiplied by 90 percent and rounded up to the next whole guest."

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final_diverge_on_guarantee_floor
    """
    ctx = fx.setup_guaranteed_order(
        guaranteed_headcount=60, clock="2026-07-01T00:00:00Z", booked_headcount=80,
    )
    order = ctx["order"]
    assert order["provisional_total_cents"] == 587000

    invoiced = validate_success(
        api.invoice_order(order["id"], {"expected_order_version": order["version"]}, COORD)
    )
    assert invoiced["final_total_cents"] == 528300
    assert invoiced["final_total_cents"] != invoiced["provisional_total_cents"]


def test_cancellation_full_refund_nets_deposit_ledger_to_zero(api):
    """PRD §3.9: "if hours-out is at least 168, the fraction is 1.00 (full deposit returned)".
    PRD §3.9: "When the refund fraction is greater than zero, `settlement_status` moves from
    `DEPOSIT_HELD` to `REFUNDED`: a `REFUND` ledger entry is appended with `amount_cents` equal
    to the negative of the refunded amount, and when the forfeited amount is greater than zero
    a `FORFEIT` ledger entry is appended with `amount_cents` equal to the positive forfeited amount."

    Design: Difficulty/dual_variant_calc/cancellation_refund_vs_forfeit_on_deposit_ledger
    """
    # Clock 2026-06-01 vs event 2026-09-01 → well past 168h → full refund.
    ctx = fx.setup_confirmed_order(clock="2026-06-01T00:00:00Z", booked_headcount=80)
    order = ctx["order"]
    cancelled = validate_success(
        api.cancel_order(order["id"], {"expected_order_version": order["version"]},
                         ctx["client_headers"])
    )
    assert cancelled["settlement_status"] == "REFUNDED"
    assert cancelled["lifecycle_status"] == "CANCELLED"

    entries, _ = _ledger(api, order["id"])
    assert sum(int(e["amount_cents"]) for e in entries) == 0, "HOLD +d then REFUND -d nets to 0"
    types = [e["entry_type"] for e in entries]
    assert "REFUND" in types
    assert "FORFEIT" not in types, "full refund writes no forfeit entry"


# =====================================================================
# Queue A — Rule 2: combinatorial formula
# =====================================================================
def test_guarantee_at_or_above_floor_bills_the_guarantee(api):
    """PRD §3.4: "The effective headcount is the larger of the guaranteed headcount and a floor
    equal to the booked headcount multiplied by 90 percent and rounded up to the next whole guest."
    PRD §3.4: "a guarantee exactly equal to the floor bills the guarantee".

    Design: Difficulty/dual_variant_calc/order_total_provisional_vs_final_diverge_on_guarantee_floor
    """
    # booked 80 → floor ceil(72) = 72. Guarantee exactly 72 → effective 72; same as below-floor
    # case but reached via the guarantee branch (max(72,72)=72), confirming the floor boundary.
    ctx = fx.setup_guaranteed_order(
        guaranteed_headcount=72, clock="2026-07-01T00:00:00Z", booked_headcount=80,
    )
    order = ctx["order"]
    invoiced = validate_success(
        api.invoice_order(order["id"], {"expected_order_version": order["version"]}, COORD)
    )
    # effective 72 → final food 360000 → grand 528300
    assert invoiced["final_total_cents"] == 528300


def test_cancellation_full_forfeit_inside_window_sets_forfeited(api):
    """PRD §3.9: "otherwise (inside 72 hours) the fraction is 0.00 (full forfeit)."
    PRD §3.9: "When the refund fraction is zero, `settlement_status` moves from `DEPOSIT_HELD`
    to `FORFEITED` and a single `FORFEIT` entry is appended with `amount_cents` equal to the
    positive full `deposit_due_cents`."

    Design: Difficulty/dual_variant_calc/cancellation_refund_vs_forfeit_on_deposit_ledger
    """
    # Clock 2026-08-30T17:00 vs event 2026-09-01T17:00 → 48h out (< 72h) → full forfeit.
    ctx = fx.setup_confirmed_order(clock="2026-08-30T17:00:00Z", booked_headcount=80)
    order = ctx["order"]
    deposit = order["deposit_due_cents"]
    cancelled = validate_success(
        api.cancel_order(order["id"], {"expected_order_version": order["version"]},
                         ctx["client_headers"])
    )
    assert cancelled["settlement_status"] == "FORFEITED"
    entries, _ = _ledger(api, order["id"])
    forfeit = sum(int(e["amount_cents"]) for e in entries if e["entry_type"] == "FORFEIT")
    assert forfeit == deposit
    assert "REFUND" not in [e["entry_type"] for e in entries], "full forfeit writes no refund"


def test_grand_total_rounds_each_component_independently(api):
    """PRD §2.7: "when several rounded components are summed into a grand total, each component
    is rounded to whole cents independently first and only then added together — the system
    never sums raw fractional components and rounds once at the end."
    PRD §3.3: "Each of the service fee, tax, and gratuity is rounded to whole cents independently
    before this final summation."

    Design: Difficulty/combinatorial_formula/grand_total_round_per_component_not_sum_then_round
    """
    ctx = fx.setup_confirmed_order(
        clock="2026-07-01T00:00:00Z", booked_headcount=3,
        package_overrides={"name": "Tiny", "per_head_cents": 3334},
    )
    assert ctx["order"]["provisional_total_cents"] == 14677


def test_grand_total_pinned_eval_order_selects_large_gratuity_tier(api):
    """PRD §3.4: "When the subtotal is at least 5,000,000 cents (that is, fifty thousand dollars),
    the large gratuity rate of 2200 basis points (22 percent) applies; below that threshold the
    base gratuity rate of 1800 basis points (18 percent) applies."
    PRD §3.3: "the service fee, tax, and gratuity all key off the same food-plus-add-on subtotal
    and must see the same number."

    Design: Difficulty/combinatorial_formula/grand_total_pinned_eval_order_subtotal_then_fees
    """
    ctx = fx.setup_confirmed_order(
        clock="2026-07-01T00:00:00Z", booked_headcount=1102,
        package_overrides={"name": "Mega", "per_head_cents": 5000,
                           "volume_tiers": [{"min_headcount": 100, "per_head_cents": 4500}]},
    )
    assert ctx["order"]["provisional_total_cents"] == 7550314


def test_grand_total_components_assembled_from_subtotal(api):
    """PRD §3.3: "the subtotal is the food charge plus the add-on sum. Fourth, the service fee is
    the subtotal multiplied by the venue's `service_fee_bps`, divided by 10000, rounded half-up to
    whole cents."
    PRD §2.7: "each component is rounded to whole cents independently first and only then added
    together".

    Design: Difficulty/combinatorial_formula/grand_total_round_per_component_not_sum_then_round
    """
    # base 3334, headcount 6 → food 20004. svc=rhu(20004*0.2)=4001; tax=rhu(20004*0.0875)=1750;
    # grat=rhu(20004*0.18)=3601 → grand 20004+4001+1750+3601 = 29356.
    ctx = fx.setup_confirmed_order(
        clock="2026-07-01T00:00:00Z", booked_headcount=6,
        package_overrides={"name": "Tiny", "per_head_cents": 3334},
    )
    assert ctx["order"]["provisional_total_cents"] == 29356


def test_grand_total_below_tier_uses_base_gratuity(api):
    """PRD §3.4: "below that threshold the base gratuity rate of 1800 basis points (18 percent)
    applies. These bands are evaluated against the same subtotal the service fee and tax see."

    Design: Difficulty/combinatorial_formula/grand_total_pinned_eval_order_subtotal_then_fees
    """
    # base 5000, headcount 100 → food 500000 (< 5,000,000) → base gratuity 1800bps.
    # svc=rhu(500000*0.2)=100000; tax=rhu(500000*0.0875)=43750; grat=rhu(500000*0.18)=90000.
    # grand = 500000+100000+43750+90000 = 733750.
    ctx = fx.setup_confirmed_order(
        clock="2026-07-01T00:00:00Z", booked_headcount=100,
        package_overrides={"name": "Mid", "per_head_cents": 5000},
    )
    assert ctx["order"]["provisional_total_cents"] == 733750


# =====================================================================
# Queue B — calculations
# =====================================================================
def test_headcount_charge_crosses_volume_tier_marginally(api):
    """PRD §3.4: "for each guest counted from the first to the headcount-th (using a 1-based
    index), that guest is billed at the `per_head_cents` of the highest-`min_headcount` tier
    whose `min_headcount` is at most that guest's index; guests below the first explicit tier's
    breakpoint fall back to the base rate."

    Design: Corner/calculations/headcount_charge_crosses_volume_tier_marginal
    """
    ctx = fx.setup_confirmed_order(
        clock="2026-06-01T00:00:00Z", booked_headcount=120,
        package_overrides={"name": "Mega", "per_head_cents": 5000,
                           "volume_tiers": [{"min_headcount": 100, "per_head_cents": 4500}]},
        venue_overrides={"tax_rate_bps": 0, "service_fee_bps": 0},
        client_overrides={"gratuity_policy": "OPTIONAL"},
    )
    # 99*5000 + 21*4500 = 589500; no fees, no tax, no gratuity.
    assert ctx["order"]["provisional_total_cents"] == 589500


def test_tax_exempt_client_zeroes_tax_component(api):
    """PRD §3.3: "the tax is zero if the owning client is `tax_exempt`, and otherwise the
    subtotal multiplied by the venue's `tax_rate_bps`, divided by 10000, rounded half-up to
    whole cents; tax is levied on the subtotal only, never on the service fee or gratuity."

    Design: Corner/calculations/tax_exempt_client_zeroes_tax_component
    """
    ctx = fx.setup_confirmed_order(
        clock="2026-06-01T00:00:00Z", booked_headcount=3,
        package_overrides={"name": "Tiny", "per_head_cents": 3334},
        client_overrides={"company_name": "Exempt", "billing_email": "e@x.com", "tax_exempt": True},
    )
    # food 10002 + svc 2000 + tax 0 + gratuity 1800 = 13802
    assert ctx["order"]["provisional_total_cents"] == 13802


def test_optional_gratuity_client_zeroes_gratuity_component(api):
    """PRD §3.3: "the gratuity is zero if the client's `gratuity_policy` is `OPTIONAL`, and
    otherwise the subtotal multiplied by a gratuity rate in basis points, divided by 10000,
    rounded half-up to whole cents".

    Design: Corner/calculations/optional_gratuity_client_zeroes_gratuity_component
    """
    ctx = fx.setup_confirmed_order(
        clock="2026-06-01T00:00:00Z", booked_headcount=3,
        package_overrides={"name": "Tiny", "per_head_cents": 3334},
        client_overrides={"company_name": "NoTip", "billing_email": "n@x.com",
                          "gratuity_policy": "OPTIONAL"},
    )
    # food 10002 + svc 2000 + tax 875 + gratuity 0 = 12877
    assert ctx["order"]["provisional_total_cents"] == 12877


def test_rush_deposit_uses_50pct_inside_72_hours(api):
    """PRD §3.5: "if the whole hours from the current server time to `event_start` (floored)
    are fewer than 72, the deposit is instead the provisional total multiplied by 50 percent,
    rounded half-up."

    Design: Corner/calculations/rush_deposit_50pct_inside_72h_threshold
    """
    # Clock 2026-08-30T17:00 vs event 2026-09-01T17:00 → 48h out (< 72h). lead_time 24h passes.
    ctx = fx.setup_confirmed_order(clock="2026-08-30T17:00:00Z", booked_headcount=80)
    assert ctx["order"]["provisional_total_cents"] == 587000
    assert ctx["order"]["deposit_due_cents"] == 293500


def test_effective_headcount_below_floor_bills_the_floor(api):
    """PRD §3.4: "At the boundary, a guarantee exactly equal to the floor bills the guarantee,
    and a guarantee one guest below the floor bills the floor."

    Design: Corner/calculations/effective_headcount_guarantee_floor_below_floor_bills_floor
    """
    ctx = fx.setup_guaranteed_order(
        guaranteed_headcount=60, clock="2026-06-01T00:00:00Z", booked_headcount=80,
    )
    order = ctx["order"]
    invoiced = validate_success(
        api.invoice_order(order["id"], {"expected_order_version": order["version"]}, COORD)
    )
    # guaranteed 60 < floor 72 → bills 72 → final grand 528300
    assert invoiced["final_total_cents"] == 528300


def test_change_fee_applies_rush_multiplier_inside_72_hours(api):
    """PRD §3.10: "Otherwise (inside 72 hours, a rush change) the fee is that same
    base-plus-per-head amount multiplied by 1.5, rounded half-up to whole cents after the
    multiplier."

    Design: Corner/calculations/change_fee_rush_multiplier_inside_72h
    """
    # Clock 2026-08-31T17:00 vs event 2026-09-01T17:00 → 24h out (< 72h). lead_time 1h.
    ctx = fx.setup_confirmed_order(
        clock="2026-08-31T17:00:00Z", booked_headcount=80,
        package_overrides={"lead_time_hours": 1},
    )
    order = ctx["order"]
    cr = fx.open_change_request(order["id"], ctx["client_headers"], requested_headcount=90)
    accepted = validate_success(
        api.accept_change_request(cr["id"], {"expected_order_version": order["version"]}, COORD)
    )
    # delta 10 → round_half_up((5000+10*150)*1.5) = 9750
    assert accepted["change_fee_cents"] == 9750
    updated = validate_success(api.get_order(order["id"], COORD))
    assert updated["booked_headcount"] == 90


def test_per_head_scaled_staffing_recomputed_at_invoice(api):
    """PRD §3.3: "In the final pass, a `STAFFING` line whose `per_head_scaled` is true instead
    uses an effective quantity equal to the effective headcount divided by `staff_ratio`,
    rounded up to a whole number; all other lines and the entire provisional pass use the
    stored quantity."

    Design: Corner/calculations/staffing_per_head_scaled_recomputed_at_invoice
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    fx.set_staff_pool(50)
    ctx = fx.create_draft_order(
        booked_headcount=80,
        package_overrides={"per_head_cents": 5000},
        venue_overrides={"tax_rate_bps": 0, "service_fee_bps": 0},
        client_overrides={"gratuity_policy": "OPTIONAL"},
    )
    order = ctx["order"]
    validate_success(
        api.create_add_on(
            order["id"],
            create_add_on_payload("STAFFING", 8000, 2, per_head_scaled=True, staff_ratio=25),
            ctx["client_headers"],
        ),
        expected_status=201,
    )
    order = fx.confirm_order(order)
    order = fx.guarantee_order(order, 60)  # effective = max(60, ceil(80*0.9)=72) = 72
    invoiced = validate_success(
        api.invoice_order(order["id"], {"expected_order_version": order["version"]}, COORD)
    )
    # food eff72 base5000 = 360000; staffing ceil(72/25)=3 *8000 = 24000; no fees → 384000
    assert invoiced["final_total_cents"] == 384000


# ---- helper ----
def _ledger(api, order_id):
    from test_helpers import validate_paginated
    return validate_paginated(api.list_order_ledger(order_id, COORD))
