"""Mitigation fee variants, rounding order, zero-count edge, the conserved mitigation
invariant, and replacement-planting canopy reconciliation."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    setup_approved_removal_permit, outstanding_mitigation_cents,
    TEST_USERS,
)

ADMIN = TEST_USERS["forestry_admin_headers"]
STAFF = TEST_USERS["forestry_staff_headers"]
INSPECTOR = TEST_USERS["inspector_headers"]


# ── dual_variant_calc: REPLACEMENT_COST vs APPRAISED_VALUE ───────────────
def test_replacement_cost_fee_for_dbh_twenty(api):
    """PRD §3.5: "the server first computes the per-tree cost in cents by taking the
    species' `base_replacement_value_dollars`, multiplying by the replacement site factor
    of 1.075, and multiplying by 100 to convert dollars to cents, then rounding that
    per-tree result half-up to a whole number of cents; the fee is that rounded per-tree
    cent amount multiplied by the `required_replacement_count`."

    Design: Difficulty/dual_variant_calc/mitigation_replacement_vs_appraised_diverge
    """
    ctx = setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0)
    assert ctx["permit"]["required_replacement_count"] == 2
    assert ctx["permit"]["mitigation_fee_cents"] == 40312


def test_appraised_value_fee_differs_from_replacement_cost(api):
    """PRD §3.5: "the basal trunk area in square inches is 0.5454 multiplied by the square
    of the tree's `dbh_inches`; a condition factor is selected from the tree's
    `condition_class` — 1.0 for `GOOD`, 0.75 for `FAIR`, 0.5 for `POOR`, and 0.25 for
    `DEAD`; and the fee is the species' `base_appraisal_value_per_sqin` multiplied by that
    trunk area, multiplied by the condition factor, multiplied by 100, with a single
    half-up rounding to a whole number of cents applied at the very end."

    Design: Difficulty/dual_variant_calc/mitigation_replacement_vs_appraised_diverge
    """
    ctx = setup_approved_removal_permit(mitigation_method="APPRAISED_VALUE",
                                        dbh=20.0, condition_class="GOOD")
    # 27.00 * (0.5454 * 400) * 1.0 * 100 = 589032 cents.
    assert ctx["permit"]["mitigation_fee_cents"] == 589032
    assert ctx["permit"]["mitigation_fee_cents"] != 40312


# ── combinatorial_formula: per-tree-then-sum rounding order ──────────────
def test_replacement_cost_rounds_per_tree_before_summing(api):
    """PRD §3.5: "The rounding must be applied to each tree individually before multiplying
    by the count — the unrounded per-tree dollar figures must not be summed and rounded
    once."

    Design: Difficulty/combinatorial_formula/mitigation_rounding_order_pinned
    """
    ctx = setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0)
    # per-tree round_half_up(187.50*1.075*100)=20156; *2 = 40312 (not 40313 from sum-then-round).
    assert ctx["permit"]["mitigation_fee_cents"] == 40312
    assert ctx["permit"]["mitigation_fee_cents"] != 40313


def test_replacement_cost_fee_is_rounded_per_tree_times_count(api):
    """PRD §3.5: "the fee is that rounded per-tree cent amount multiplied by the
    `required_replacement_count`."

    Design: Difficulty/combinatorial_formula/mitigation_rounding_order_pinned
    """
    ctx = setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0)
    count = ctx["permit"]["required_replacement_count"]
    assert count == 2
    assert ctx["permit"]["mitigation_fee_cents"] == 20156 * count


# ── boundary_precision_check: zero-count small protected species ─────────
def test_small_protected_species_requires_zero_replacements(api):
    """PRD §3.5: "The `required_replacement_count` is tiered by the governed tree's
    `dbh_inches` with inclusive lower bounds: a tree under 8.0 inches requires 0
    replacements (it is protected, if at all, only by species, and carries no size-based
    replacement)".

    Design: Difficulty/boundary_precision_check/zero_replacement_count_for_small_protected_species
    """
    ctx = setup_approved_removal_permit(
        mitigation_method="REPLACEMENT_COST", dbh=6.0,
        species_overrides={"name": "Heritage", "is_protected_species": True,
                           "mature_canopy_sqm": 10.0, "base_replacement_value_dollars": 100.00,
                           "base_appraisal_value_per_sqin": 10.00, "min_spacing_m": 3.0})
    assert ctx["permit"]["required_replacement_count"] == 0


def test_small_protected_species_fee_is_zero(api):
    """PRD §3.5: "the fee is that rounded per-tree cent amount multiplied by the
    `required_replacement_count`."

    Design: Difficulty/boundary_precision_check/zero_replacement_count_for_small_protected_species
    """
    ctx = setup_approved_removal_permit(
        mitigation_method="REPLACEMENT_COST", dbh=6.0,
        species_overrides={"name": "Heritage", "is_protected_species": True,
                           "mature_canopy_sqm": 10.0, "base_replacement_value_dollars": 100.00,
                           "base_appraisal_value_per_sqin": 10.00, "min_spacing_m": 3.0})
    assert ctx["permit"]["mitigation_fee_cents"] == 0


# ── compensating_invariant: approve then revoke conserves outstanding ────
def test_revoke_restores_outstanding_mitigation_total(api):
    """PRD §2.9: "Approving a removal permit adds that permit's `mitigation_fee_cents` to
    the outstanding total; closing the permit (when its removal work is completed)
    subtracts the same amount; and revoking the permit subtracts it as a compensating
    action."

    Design: Difficulty/compensating_invariant/approve_then_revoke_conserves_outstanding_mitigation
    """
    base = setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=10.0)
    assert base["permit"]["mitigation_fee_cents"] == 20156
    second = setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0)
    assert second["permit"]["mitigation_fee_cents"] == 40312
    assert outstanding_mitigation_cents() == 20156 + 40312

    validate_success(api.revoke_permit(second["permit"]["id"], {"reason": "withdrawn"}, ADMIN), 200)
    assert outstanding_mitigation_cents() == 20156


def test_revoked_permit_row_retained_but_excluded_from_outstanding(api):
    """PRD §3.4: "Revocation subtracts the permit's `mitigation_fee_cents` from the
    outstanding mitigation total as a compensating action for the approve-time debit — but
    only if that amount had not already been subtracted when the permit closed. Any
    replacement-planting rows created at approval are not deleted, but because the permit
    is now `REVOKED` they no longer count toward outstanding mitigation."

    Design: Difficulty/compensating_invariant/approve_then_revoke_conserves_outstanding_mitigation
    """
    setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=10.0)  # baseline live
    second = setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0)
    revoked = validate_success(
        api.revoke_permit(second["permit"]["id"], {"reason": "withdrawn"}, ADMIN), 200)
    assert revoked["status"] == "REVOKED"
    assert revoked["mitigation_fee_cents"] == 40312
    assert outstanding_mitigation_cents() == 20156


# ── Corner: replacement establish reconciles zone canopy ─────────────────
def test_establishing_replacement_adds_species_canopy_to_zone(api):
    """PRD §3.5: "An `Inspector` then **establishes** a planted one (`PLANTED →
    ESTABLISHED`), allowed only from `PLANTED`; establishing adds the planting species'
    `mature_canopy_sqm` to the `live_canopy_sqm` of its `target_zone_id` and recomputes
    that zone's `current_canopy_pct` and `canopy_status`."

    Design: Corner/cross_cutting_complexity_layers/replacement_establish_adds_zone_canopy
    """
    ctx = setup_approved_removal_permit(mitigation_method="REPLACEMENT_COST", dbh=20.0)
    plantings = get_success_data(
        api.list_permit_plantings(ctx["permit"]["id"], STAFF, params={"limit": 100, "offset": 0}))
    assert len(plantings) == 2
    rp0 = plantings[0]
    api.plant_replacement(rp0["id"], STAFF)
    established = validate_success(api.establish_replacement(rp0["id"], INSPECTOR), 200)
    assert established["status"] == "ESTABLISHED"
    zone = validate_success(api.get_zone(ctx["zone"]["id"], ADMIN), 200)
    # 50 (standing Oak) + 50 (established replacement Oak) = 100.
    assert zone["live_canopy_sqm"] == pytest.approx(100, abs=0.005)
