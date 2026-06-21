"""Calculation correctness: exercise spread, SAFE/note conversion, vesting,
fully-diluted dilution. Each test pins a literal expected value derived from a
verbatim PRD formula.
"""
import math

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_board_approver_headers,
    setup_active_vested_grant,
    setup_outstanding_safe_with_target,
    create_cap_table,
    create_security_class,
    create_shareholder,
    create_effective_valuation,
    create_option_pool,
    create_active_grant,
    set_clock,
    issue_shares,
    create_outstanding_note,
)

ADMIN = TEST_USERS["administrator_headers"]
APPROVER = TEST_USERS["board_approver_headers"]


# ============================================================================
# Difficulty/dual_variant_calc/exercise_spread_in_the_money_vs_underwater
# ============================================================================

def test_exercise_spread_underwater_floored_to_zero(api):
    """PRD §3.8: "Settlement also computes the exercise's `spread_cents` — the
    taxable bargain element — as the per-share difference between the grant's
    valuation `fmv_per_share_cents` and the grant's `strike_price_cents`, floored
    at zero, multiplied by the exercise's `share_count`, in exact cents."

    fmv=500, strike=800 → max(0, 500-800)*1000 == 0.

    Design: Difficulty/dual_variant_calc/exercise_spread_in_the_money_vs_underwater
    """
    env = setup_active_vested_grant(fmv_per_share_cents=500, strike_price_cents=800,
                                    share_count=1000, clock="2026-06-01T00:00:00Z")
    ex = get_success_data(api.create_exercise({
        "cap_table_id": env["ct"]["id"], "option_grant_id": env["grant"]["id"],
        "share_count": 1000,
    }, ADMIN))
    data = validate_success(api.settle_exercise(ex["id"], ADMIN), 200)
    assert data["spread_cents"] == 0, f"expected 0 (underwater floored), got {data['spread_cents']}"


# ============================================================================
# Difficulty/combinatorial_formula/conversion_shares_min_of_cap_and_discount_price
# Corner/calculations/note_conversion_discount_binds_no_cap
# ============================================================================

def test_conversion_cap_price_binds_min_of_two_prices(api):
    """PRD §3.10: "If `valuation_cap_cents` is greater than zero, a cap price is
    computed as `valuation_cap_cents` divided by the cap table's current
    `fully_diluted_shares`, and the effective conversion price is the lesser of
    the discount price and the cap price; if there is no cap, the discount price
    governs. The `converted_share_count` is the invested base divided by the
    effective price, floored to whole shares."

    fd=1,000,000; discount_price=1000*(1-0.20)=800; cap_price=600,000,000/1,000,000=600;
    cap binds → floor(2,000,000/600) == 3333.

    Design: Difficulty/combinatorial_formula/conversion_shares_min_of_cap_and_discount_price
    """
    env = setup_outstanding_safe_with_target(
        principal_cents=2_000_000, discount_pct=0.20, valuation_cap_cents=600_000_000,
        target_pps_cents=1000, issued_common=1_000_000, common_oip_cents=100,
    )
    data = validate_success(api.convert_safe_note(env["note"]["id"], {
        "target_class_id": env["pref"]["id"],
        "expected_note_version": env["note_version"],
    }, APPROVER), 200)
    assert data["converted_share_count"] == 3333, (
        f"expected 3333 (cap binds), got {data['converted_share_count']}"
    )
    assert data["status"] == "CONVERTED"


def test_conversion_sets_converted_into_class_and_mints_shares(api):
    """PRD §3.10: "On conversion, `converted_into_class_id` is set to the target
    class, that class's `shares_outstanding` rises by `converted_share_count`,
    the cap table's `issued_shares` and `fully_diluted_shares` are recomputed, the
    note moves `OUTSTANDING → CONVERTED`, and the note's `version` is incremented."

    After the cap-binding conversion (3333 shares), the target class's
    shares_outstanding rises by 3333 and converted_into_class_id points at it.

    Design: Difficulty/combinatorial_formula/conversion_shares_min_of_cap_and_discount_price
    """
    env = setup_outstanding_safe_with_target(
        principal_cents=2_000_000, discount_pct=0.20, valuation_cap_cents=600_000_000,
        target_pps_cents=1000, issued_common=1_000_000, common_oip_cents=100,
    )
    data = validate_success(api.convert_safe_note(env["note"]["id"], {
        "target_class_id": env["pref"]["id"],
        "expected_note_version": env["note_version"],
    }, APPROVER), 200)
    assert data["converted_into_class_id"] == env["pref"]["id"], (
        f"expected converted_into_class_id == target, got {data['converted_into_class_id']}"
    )
    pref_after = validate_success(api.get_security_class(env["pref"]["id"], APPROVER), 200)
    assert pref_after["shares_outstanding"] == 3333, (
        f"expected target class shares_outstanding 3333, got {pref_after['shares_outstanding']}"
    )


def test_conversion_discount_binds_when_no_cap(api):
    """PRD §3.10: "If `valuation_cap_cents` is greater than zero, a cap price is
    computed as `valuation_cap_cents` divided by the cap table's current
    `fully_diluted_shares`, and the effective conversion price is the lesser of
    the discount price and the cap price; if there is no cap, the discount price
    governs. The `converted_share_count` is the invested base divided by the
    effective price, floored to whole shares."

    No cap (valuation_cap_cents=0) → effective = discount_price = 1000*(1-0.20)=800;
    floor(2,000,000/800) == 2500.

    Design: Corner/calculations/note_conversion_discount_binds_no_cap
    """
    env = setup_outstanding_safe_with_target(
        principal_cents=2_000_000, discount_pct=0.20, valuation_cap_cents=0,
        target_pps_cents=1000, issued_common=0, common_oip_cents=0,
    )
    data = validate_success(api.convert_safe_note(env["note"]["id"], {
        "target_class_id": env["pref"]["id"],
        "expected_note_version": env["note_version"],
    }, APPROVER), 200)
    assert data["converted_share_count"] == 2500, (
        f"expected 2500 (discount binds, no cap), got {data['converted_share_count']}"
    )


# ============================================================================
# Difficulty/boundary_precision_check/vesting_cliff_boundary_11_vs_12_months
# Corner/calculations/vested_cliff_only_step_function
# ============================================================================

def _build_grant_for_vesting(vesting_style, share_count=48000):
    """grant_date 2024-01-01, cliff 12, vesting 48; returns (ct_id, grant_id)."""
    set_clock("2024-01-01T00:00:00Z")
    ct = create_cap_table(authorized_shares=10_000_000)
    common = create_security_class(ct["id"], name="Common", class_type="COMMON",
                                   original_issue_price_cents=0)
    sh = create_shareholder(ct["id"], legal_name="Emp", holder_type="EMPLOYEE",
                            email="vest@test.com")
    val = create_effective_valuation(ct["id"], fmv_per_share_cents=100,
                                     valuation_date="2023-06-01T00:00:00Z",
                                     expires_at="2030-06-01T00:00:00Z")
    pool = create_option_pool(ct["id"], authorized_shares=100_000)
    grant = create_active_grant(
        ct["id"], pool["id"], sh["id"], common["id"], val["id"],
        share_count=share_count, strike_price_cents=100,
        grant_date="2024-01-01T00:00:00Z", vesting_months=48, cliff_months=12,
        vesting_style=vesting_style,
    )
    return ct["id"], grant["id"]


def test_graded_vesting_zero_just_below_cliff(api):
    """PRD §3.7: "If that elapsed-month count is below `cliff_months`, nothing
    has vested and `vested_shares` is zero."

    11 whole months elapsed (2024-12-01) < 12-month cliff → vested_shares == 0.

    Design: Difficulty/boundary_precision_check/vesting_cliff_boundary_11_vs_12_months
    """
    ct_id, grant_id = _build_grant_for_vesting("GRADED")
    set_clock("2024-12-01T00:00:00Z")
    data = validate_success(api.get_option_grant(grant_id, ADMIN), 200)
    assert data["vested_shares"] == 0, f"expected 0 at 11mo, got {data['vested_shares']}"


def test_graded_vesting_jumps_at_exact_cliff(api):
    """PRD §3.7: "A `GRADED` grant accrues linearly — the vested figure is the
    grant's `share_count` multiplied by the lesser of the elapsed whole-months
    and `vesting_months`, divided by `vesting_months`, with the result floored to
    whole shares."

    Exactly 12 months (2025-01-01) → floor(48000*12/48) == 12000.

    Design: Difficulty/boundary_precision_check/vesting_cliff_boundary_11_vs_12_months
    """
    ct_id, grant_id = _build_grant_for_vesting("GRADED")
    set_clock("2025-01-01T00:00:00Z")
    data = validate_success(api.get_option_grant(grant_id, ADMIN), 200)
    assert data["vested_shares"] == 12000, f"expected 12000 at 12mo, got {data['vested_shares']}"


def test_cliff_only_steps_to_full_share_count_at_cliff(api):
    """PRD §3.7: "a `CLIFF_ONLY` grant vests its entire `share_count` in a single
    step at the cliff and holds there."

    CLIFF_ONLY, 48000 shares, 12-month cliff: at exactly 12 months vested == 48000.

    Design: Corner/calculations/vested_cliff_only_step_function
    """
    ct_id, grant_id = _build_grant_for_vesting("CLIFF_ONLY", share_count=48000)
    set_clock("2025-01-01T00:00:00Z")
    data = validate_success(api.get_option_grant(grant_id, ADMIN), 200)
    assert data["vested_shares"] == 48000, (
        f"expected 48000 (CLIFF_ONLY full step), got {data['vested_shares']}"
    )
