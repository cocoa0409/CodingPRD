"""Seed inventory waterfall, planting validation, and compensating invariants
on void (seed conservation and plan-input-cost conservation).

Difficulty queue A: compensating_invariant (void planting restores seed inventory;
void confirmed application conserves plan input cost).
Corner queue B: calculations (insufficient seed inventory, no partial debit),
validations (planting with non-seed lot rejected).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    make_applicator_headers,
    set_clock, create_parcel, create_draft_plan, create_and_approve_plan,
    create_seed_product, create_input_product, create_input_lot, create_applicator,
    setup_growing_plan, record_planting, log_application,
)

FM = TEST_USERS["farm_manager_headers"]
AG = TEST_USERS["agronomist_headers"]


# ===========================================================================
# Difficulty: compensating_invariant — void_planting_restores_seed_inventory
# ===========================================================================
def test_void_planting_restores_seed_inventory(api):
    """PRD §3.3: "Voiding a planting reverses this: the consumed quantities are restored
    to the lots, lots that were `DEPLETED` may revert to `OPEN`, and the plan's
    `planted_acres` is recomputed."

    Design: Difficulty/compensating_invariant/void_planting_restores_seed_inventory_conserved
    """
    parcel = create_parcel(name="INVF", acreage=100.0)
    seed = create_seed_product(name="Seed Inv")
    lot_a = create_input_lot(seed["id"], lot_code="A", quantity_received=100.0)
    lot_b = create_input_lot(seed["id"], lot_code="B", quantity_received=400.0)
    plan, _ = create_and_approve_plan(parcel, crop="CORN", planned_acres=100.0)
    # need = 30 * 4 = 120 -> lot A (100) depleted, lot B at 380.
    pe = record_planting(plan["id"], lot_a["id"], acres_planted=30.0, seed_rate_per_acre=4.0)

    voided = validate_success(api.void_planting_event(pe["id"], AG))
    assert voided["status"] == "VOIDED", f"expected VOIDED, got {voided['status']}"

    a_after = validate_success(api.get_input_lot(lot_a["id"], FM))
    b_after = validate_success(api.get_input_lot(lot_b["id"], FM))
    assert a_after["quantity_remaining"] == 100, (
        f"lot A must restore to 100, got {a_after['quantity_remaining']}")
    assert b_after["quantity_remaining"] == 400, (
        f"lot B must restore to 400, got {b_after['quantity_remaining']}")
    assert a_after["status"] == "OPEN", f"lot A must revert OPEN, got {a_after['status']}"


def test_void_planting_recomputes_planted_acres_to_zero(api):
    """PRD §3.5: "Voiding a planting, also an `Agronomist` action, moves it to `VOIDED`,
    restores the debited quantities, and recomputes `planted_acres`."
    PRD §3.5: "recomputes the plan's `planted_acres` (the sum of `acres_planted` across
    the plan's non-voided plantings)."

    Design: Difficulty/compensating_invariant/void_planting_restores_seed_inventory_conserved
    """
    parcel = create_parcel(name="INVF2", acreage=100.0)
    seed = create_seed_product(name="Seed Inv2")
    lot = create_input_lot(seed["id"], lot_code="A", quantity_received=500.0)
    plan, _ = create_and_approve_plan(parcel, crop="CORN", planned_acres=100.0)
    pe = record_planting(plan["id"], lot["id"], acres_planted=30.0, seed_rate_per_acre=4.0)
    before = validate_success(api.get_crop_plan(plan["id"], FM))
    assert before["planted_acres"] == 30, f"planted_acres must be 30, got {before['planted_acres']}"
    validate_success(api.void_planting_event(pe["id"], AG))
    after = validate_success(api.get_crop_plan(plan["id"], FM))
    assert after["planted_acres"] == 0, (
        f"planted_acres must recompute to 0 after void, got {after['planted_acres']}")


# ===========================================================================
# Difficulty: compensating_invariant — void_confirmed_app_conserves_plan_input_cost
# ===========================================================================
def test_void_confirmed_application_conserves_plan_input_cost(api):
    """PRD §3.4: "Voiding a confirmed application moves it to `VOIDED`, drops it out of
    the plan's `actual_input_cost` (recomputed) and recomputes `provisional_cost_per_acre`."

    Design: Difficulty/compensating_invariant/void_confirmed_app_conserves_plan_input_cost
    """
    set_clock("2026-06-10T00:00:00Z")
    ctx = setup_growing_plan(crop="CORN", planned_acres=100.0, acreage=100.0)
    fert = create_input_product(name="Fert CF", category="FERTILIZER", unit="GAL", unit_cost=12.50)
    appl = create_applicator(full_name="A", license_no="RU-50", certified=True)
    rec = log_application(ctx["plan"]["id"], fert["id"], appl["id"],
                          rate_per_acre=2.0, acres_treated=40.0)
    validate_success(api.confirm_application(rec["id"], make_applicator_headers(appl["id"])))
    # 2 * 40 * 12.50 = 1000 added to actual_input_cost.
    after_confirm = validate_success(api.get_crop_plan(ctx["plan"]["id"], FM))
    assert after_confirm["actual_input_cost"] == 1000.00, (
        f"actual_input_cost must be 1000.00 after confirm, got {after_confirm['actual_input_cost']}")

    voided = validate_success(api.void_application(rec["id"], AG))
    assert voided["status"] == "VOIDED", f"expected VOIDED, got {voided['status']}"
    after_void = validate_success(api.get_crop_plan(ctx["plan"]["id"], FM))
    assert after_void["actual_input_cost"] == 0.00, (
        f"actual_input_cost must return to 0.00 after void, got {after_void['actual_input_cost']}")


def test_confirmed_application_adds_to_plan_input_cost(api):
    """PRD §3.4: "On a successful confirm, the system stamps `applied_at` from the server
    clock, recomputes `quantity_used` and `applied_cost`, and recomputes the plan's
    `actual_input_cost` and `provisional_cost_per_acre`."

    Design: Difficulty/compensating_invariant/void_confirmed_app_conserves_plan_input_cost
    """
    set_clock("2026-06-10T00:00:00Z")
    ctx = setup_growing_plan(crop="CORN", planned_acres=100.0, acreage=100.0)
    fert = create_input_product(name="Fert CF2", category="FERTILIZER", unit="GAL", unit_cost=12.50)
    appl = create_applicator(full_name="A2", license_no="RU-51", certified=True)
    rec = log_application(ctx["plan"]["id"], fert["id"], appl["id"],
                          rate_per_acre=2.0, acres_treated=40.0)
    confirmed = validate_success(api.confirm_application(rec["id"], make_applicator_headers(appl["id"])))
    assert confirmed["status"] == "CONFIRMED", f"expected CONFIRMED, got {confirmed['status']}"
    plan_after = validate_success(api.get_crop_plan(ctx["plan"]["id"], FM))
    assert plan_after["actual_input_cost"] == 1000.00, (
        f"actual_input_cost must be 1000.00, got {plan_after['actual_input_cost']}")


# ===========================================================================
# Corner: calculations / validations on inventory
# ===========================================================================
def test_insufficient_seed_inventory_no_partial_debit(api):
    """PRD §3.3: "If the candidate lots are exhausted and need still remains, the
    planting is rejected with `ERR_INSUFFICIENT_INVENTORY` and no partial debit is
    persisted — the inventory is left exactly as it was."

    Design: Corner/calculations/insufficient_seed_inventory_no_partial_debit
    """
    parcel = create_parcel(name="INS", acreage=200.0)
    seed = create_seed_product(name="Seed INS")
    lot_a = create_input_lot(seed["id"], lot_code="A", quantity_received=100.0)
    lot_b = create_input_lot(seed["id"], lot_code="B", quantity_received=400.0)
    plan, _ = create_and_approve_plan(parcel, crop="CORN", planned_acres=150.0)
    # need = 100 * 6 = 600 > 500 total.
    resp = api.create_planting_event({
        "crop_plan_id": plan["id"], "input_lot_id": lot_a["id"],
        "acres_planted": 100.0, "seed_rate_per_acre": 6.0}, AG)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)
    a_after = validate_success(api.get_input_lot(lot_a["id"], FM))
    b_after = validate_success(api.get_input_lot(lot_b["id"], FM))
    assert a_after["quantity_remaining"] == 100, (
        f"lot A must be unchanged at 100 (no partial debit), got {a_after['quantity_remaining']}")
    assert b_after["quantity_remaining"] == 400, (
        f"lot B must be unchanged at 400 (no partial debit), got {b_after['quantity_remaining']}")


def test_planting_with_nonseed_lot_rejected(api):
    """PRD §3.5: "The lot named by `input_lot_id` must stock a `SEED`-category product;
    if it does not, the planting is rejected with `ERR_PRODUCT_CATEGORY_MISMATCH`."

    Design: Corner/validations/planting_with_nonseed_lot_rejected
    """
    parcel = create_parcel(name="PC", acreage=100.0)
    fert = create_input_product(name="Fert NS", category="FERTILIZER", unit="GAL", unit_cost=5.0)
    fert_lot = create_input_lot(fert["id"], lot_code="FL", quantity_received=500.0)
    plan, _ = create_and_approve_plan(parcel, crop="CORN", planned_acres=50.0)
    resp = api.create_planting_event({
        "crop_plan_id": plan["id"], "input_lot_id": fert_lot["id"],
        "acres_planted": 40.0, "seed_rate_per_acre": 1.0}, AG)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_CATEGORY_MISMATCH.value)
