"""Dual-variant calculations: AGREED_VALUE vs REPLACEMENT_COST settlement, and
SIMPLE vs COMPOUND inflation-guard revaluation. Plus the in-network deductible halving.

Design queue A: dual_variant_calc.
Design queue B: calculations (in-network halving).
"""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    set_clock,
    create_risk_zone,
    create_policyholder,
    create_policy,
    create_scheduled_item,
    bind_policy,
    pay_premium,
    file_claim,
    setup_active_inflation_policy,
    setup_repair_order_assigned,
)

_UW = TEST_USERS["underwriter_headers"]
_CA = TEST_USERS["claims_adjuster_headers"]


def _build_total_loss_ready_policy(valuation_basis, email):
    """ACTIVE+PAID SIMPLE-0.05 policy, RING scheduled 1,000,000, clock advanced 24 months
    so revaluation_epoch == 2 and current_value_cents == 1,100,000. Returns (policy, item, ph)."""
    ph = create_policyholder(email=email, residence_zip="10001")
    policy = create_policy(ph["id"], coverage_type="ALL_RISK",
                           valuation_basis=valuation_basis, deductible_option="STANDARD",
                           inflation_guard_mode="SIMPLE", inflation_guard_pct=0.05)
    item = create_scheduled_item(policy["id"], description="Solitaire ring", category="RING",
                                 location_zip="10001", scheduled_value_cents=1000000)
    bind_policy(policy["id"])
    pay_premium(policy["id"], ph["id"])
    return policy, item, ph


# ─────────────────────────────────────────────────────────────────────────
# Queue A: dual_variant_calc — settlement (AGREED_VALUE vs REPLACEMENT_COST)
# ─────────────────────────────────────────────────────────────────────────

def test_total_loss_settlement_agreed_vs_replacement_diverge(api):
    """PRD §3.12: "Under AGREED_VALUE, the gross is the item's current_value_cents in full,
    with no depreciation — the agreed value is paid regardless of market movement or how many
    revaluation epochs have passed."
    PRD §3.12: "Under REPLACEMENT_COST, the gross is computed by depreciating the replacement
    figure: take the lesser of the item's current_value_cents and its original
    scheduled_value_cents (the replacement cap factor is one, so replacement gross never
    exceeds the scheduled value), multiply by one minus the product of five percent and the
    item's revaluation_epoch, and round the result half up to whole cents."
    PRD §3.12: "The settlement_cents is then the greater of zero and the gross minus the
    effective deductible"

    Design: Difficulty/dual_variant_calc/settlement_agreed_vs_replacement_total_loss
    """
    set_clock("2026-02-01T00:00:00Z")
    create_risk_zone(zip_prefix="100", risk_band="MODERATE", rate_per_thousand_cents=300)

    pol_ag, it_ag, ph_ag = _build_total_loss_ready_policy("AGREED_VALUE", "ag@x.com")
    pol_rc, it_rc, ph_rc = _build_total_loss_ready_policy("REPLACEMENT_COST", "rc@x.com")

    set_clock("2028-02-01T00:00:00Z")  # 24 months -> epoch 2 -> current_value 1,100,000

    claim_ag = file_claim(pol_ag["id"], it_ag["id"], peril="THEFT",
                          loss_type="TOTAL_LOSS", claimed_amount_cents=1100000)
    rev_ag = get_success_data(api.start_review_claim(pol_ag["id"], claim_ag["id"], _CA))
    claim_rc = file_claim(pol_rc["id"], it_rc["id"], peril="THEFT",
                          loss_type="TOTAL_LOSS", claimed_amount_cents=1100000)
    rev_rc = get_success_data(api.start_review_claim(pol_rc["id"], claim_rc["id"], _CA))

    approved_ag = validate_success(
        api.approve_claim(pol_ag["id"], claim_ag["id"],
                          {"expected_claim_version": rev_ag["version"]}, _CA), 200)
    approved_rc = validate_success(
        api.approve_claim(pol_rc["id"], claim_rc["id"],
                          {"expected_claim_version": rev_rc["version"]}, _CA), 200)

    assert approved_ag["settlement_cents"] == 1050000
    assert approved_rc["settlement_cents"] == 850000


def test_total_loss_agreed_value_deductible_applied(api):
    """PRD §3.12: "deductible_applied_cents is the gross minus that settlement — the portion
    actually withheld, which never exceeds the deductible."
    PRD §3.3: "STANDARD to fifty thousand cents"

    Design: Difficulty/dual_variant_calc/settlement_agreed_vs_replacement_total_loss
    """
    set_clock("2026-02-01T00:00:00Z")
    create_risk_zone(zip_prefix="100", risk_band="MODERATE", rate_per_thousand_cents=300)
    pol_ag, it_ag, ph_ag = _build_total_loss_ready_policy("AGREED_VALUE", "ag2@x.com")
    set_clock("2028-02-01T00:00:00Z")

    claim_ag = file_claim(pol_ag["id"], it_ag["id"], peril="THEFT",
                          loss_type="TOTAL_LOSS", claimed_amount_cents=1100000)
    rev_ag = get_success_data(api.start_review_claim(pol_ag["id"], claim_ag["id"], _CA))
    approved_ag = validate_success(
        api.approve_claim(pol_ag["id"], claim_ag["id"],
                          {"expected_claim_version": rev_ag["version"]}, _CA), 200)
    assert approved_ag["settlement_cents"] == 1050000
    assert approved_ag["deductible_applied_cents"] == 50000


# ─────────────────────────────────────────────────────────────────────────
# Queue A: dual_variant_calc — revaluation (SIMPLE vs COMPOUND)
# ─────────────────────────────────────────────────────────────────────────

def test_revaluation_simple_vs_compound_diverge_after_three_epochs(api):
    """PRD §3.5: "Under SIMPLE mode the value is the item's original scheduled_value_cents
    multiplied by one plus the product of inflation_guard_pct and the epoch count — linear
    growth on the original scheduled value — with the result rounded half up to whole cents."
    PRD §3.5: "Under COMPOUND mode the value is the original scheduled_value_cents multiplied
    by the quantity one plus inflation_guard_pct, raised to the power of the epoch count —
    annual compounding — again rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/revaluation_simple_vs_compound_guard
    """
    simple = setup_active_inflation_policy(
        inflation_guard_mode="SIMPLE", inflation_guard_pct=0.05,
        scheduled_value_cents=1000000, clock="2026-02-01T00:00:00Z", email="s@x.com")
    compound = setup_active_inflation_policy(
        inflation_guard_mode="COMPOUND", inflation_guard_pct=0.05,
        scheduled_value_cents=1000000, clock=None, create_zone=False, email="c@x.com")

    set_clock("2029-02-01T00:00:00Z")  # 36 months -> 3 epochs

    item_s = validate_success(api.get_scheduled_item(simple["item"]["id"], _UW), 200)
    item_c = validate_success(api.get_scheduled_item(compound["item"]["id"], _UW), 200)
    assert item_s["current_value_cents"] == 1150000
    assert item_c["current_value_cents"] == 1157625


def test_revaluation_simple_epoch_count_recorded(api):
    """PRD §3.5: "the system computes the number of completed policy years since
    bound_at_iso — the count of whole twelve-month periods elapsed, floored to an integer —
    and treats that count as the item's new revaluation_epoch."

    Design: Difficulty/dual_variant_calc/revaluation_simple_vs_compound_guard
    """
    simple = setup_active_inflation_policy(
        inflation_guard_mode="SIMPLE", inflation_guard_pct=0.05,
        scheduled_value_cents=1000000, clock="2026-02-01T00:00:00Z", email="s2@x.com")
    set_clock("2029-02-01T00:00:00Z")  # 36 months -> 3 epochs

    item_s = validate_success(api.get_scheduled_item(simple["item"]["id"], _UW), 200)
    assert item_s["current_value_cents"] == 1150000
    assert item_s["revaluation_epoch"] == 3


# ─────────────────────────────────────────────────────────────────────────
# Queue B: calculations — in-network deductible halving
# ─────────────────────────────────────────────────────────────────────────

def test_partial_damage_in_network_halves_deductible(api):
    """PRD §3.12: "for a PARTIAL_DAMAGE claim whose repair is handled by an in-network shop
    (the assigned RepairShop has in_network true), the deductible is halved, taking the floor
    of dividing deductible_cents by two; in every other case the effective deductible is the
    full deductible_cents."
    PRD §3.14: "its authorized_amount_cents is set to the claim's settlement_cents — the cap
    the insurer authorizes for the repair."

    Design: Corner/calculations/partial_damage_in_network_deductible_halving
    """
    ctx = setup_repair_order_assigned(shop_in_network=True, claimed_amount_cents=300000)
    # RING cv 1,000,000, STANDARD ded 50,000 halved to 25,000, claimed 300,000
    # -> settlement 300,000 - 25,000 = 275,000.
    claim = validate_success(api.get_claim(ctx["claim"]["id"], _CA), 200)
    assert claim["settlement_cents"] == 275000
    assert ctx["repair_order"]["authorized_amount_cents"] == 275000
