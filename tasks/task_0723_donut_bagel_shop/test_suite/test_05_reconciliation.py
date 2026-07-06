"""Day reconciliation: the dual-variant pool computation, OCC version guard, and the
reconcile preconditions."""
import pytest

from test_helpers import (
    api_client as _ac,
    validate_success, validate_error,
    ApiErrorId,
    TEST_USERS,
    line_item,
    create_product, create_production_day,
    create_planned_batch, create_cart, create_paid_order,
    setup_cutoff_day_one_swept_batch,
    setup_selling_day_with_baked_batch,
)

ADMIN = TEST_USERS["shop_admin_headers"]
BAKER = TEST_USERS["bake_manager_headers"]
CASHIER = TEST_USERS["cashier_headers"]


# =====================================================================
# Difficulty/dual_variant_calc/reconcile_expected_forward_vs_actual_chronological (2)
# GLAZED baked 30; 20 full-price (2700) PAID; markdown batch; 3 marked_down (270) PAID;
# sweep (wasted 7). expected=4500, gross=2970, markdown_loss=180, waste=315, variance=1035.
# =====================================================================
def _build_reconcile_scenario():
    glazed = create_product("GLAZED")
    day = create_production_day()
    batch = create_planned_batch(day["id"], glazed["id"], par_qty=30)
    validate_success(_ac.start_baking(day["id"], BAKER))
    validate_success(_ac.bake_batch(day["id"], batch["id"], {"baked_qty": 30}, BAKER))
    validate_success(_ac.open_sales(day["id"], BAKER))
    # Order A: 20 GLAZED full price PAID (1*1500 + 8*150 = 2700).
    create_paid_order(day["id"], [line_item(glazed["id"], 20)])
    # Mark batch down.
    validate_success(_ac.markdown_batch(day["id"], batch["id"], CASHIER))
    # Order B: 3 GLAZED marked_down PAID (3 * round_half_up(150*0.6)=90 => 270).
    create_paid_order(day["id"], [line_item(glazed["id"], 3, marked_down=True)])
    # Sweep remaining (30 - 23 = 7 wasted).
    validate_success(_ac.sweep_batch(day["id"], batch["id"], BAKER))
    validate_success(_ac.close_cutoff(day["id"], ADMIN))
    day_now = validate_success(_ac.get_production_day(day["id"], BAKER))
    reconciled = validate_success(_ac.reconcile_day(
        day["id"], {"expected_production_day_version": day_now["version"]}, BAKER))
    return reconciled


def test_reconcile_freezes_expected_forward_value(api):
    """PRD §3.9: "The expected full value (expected_full_value_cents) is the
    forward-looking baseline: summed over every bake batch on the day, each batch's
    baked_qty multiplied by its product's unit_price_cents — what the day would have
    grossed had every baked unit sold at full price."

    Design: Difficulty/dual_variant_calc/reconcile_expected_forward_vs_actual_chronological
    """
    reconciled = _build_reconcile_scenario()
    assert reconciled["status"] == "RECONCILED"
    assert reconciled["expected_full_value_cents"] == 4500, (
        f"30 baked * 150 unit price = 4500; got {reconciled['expected_full_value_cents']}")


def test_reconcile_freezes_actual_pools_and_variance(api):
    """PRD §3.9: "the reconciliation variance (reconciliation_variance_cents) is the
    forward baseline minus the three realized components: expected_full_value_cents minus
    gross_sales_cents minus markdown_loss_cents minus waste_cost_cents."

    Design: Difficulty/dual_variant_calc/reconcile_expected_forward_vs_actual_chronological
    """
    r = _build_reconcile_scenario()
    assert r["gross_sales_cents"] == 2970, f"got {r['gross_sales_cents']}"
    assert r["markdown_loss_cents"] == 180, f"got {r['markdown_loss_cents']}"
    assert r["waste_cost_cents"] == 315, f"got {r['waste_cost_cents']}"
    assert r["reconciliation_variance_cents"] == 1035, (
        f"4500 - 2970 - 180 - 315 = 1035; got {r['reconciliation_variance_cents']}")


# =====================================================================
# Corner/cross_cutting_complexity_layers/occ_correct_version_reconcile_succeeds  (1)
# =====================================================================
def test_reconcile_with_correct_version_succeeds(api):
    """PRD §2.9: "The reconcile operation on a production day requires a non-optional
    input field, expected_production_day_version, carrying the client's last observed
    version of that ProductionDay. The server compares it to the day's current version."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_version_reconcile_succeeds
    """
    day, _product, _batch = setup_cutoff_day_one_swept_batch(par_qty=10, baked_qty=10)
    current = validate_success(_ac.get_production_day(day["id"], BAKER))
    reconciled = validate_success(_ac.reconcile_day(
        day["id"], {"expected_production_day_version": current["version"]}, BAKER))
    assert reconciled["status"] == "RECONCILED"


# =====================================================================
# Corner/cross_cutting_complexity_layers/occ_stale_version_reconcile_rejected  (1)
# =====================================================================
def test_reconcile_with_stale_version_rejected(api):
    """PRD §2.9: "If another writer has advanced the day since the client last read it —
    a batch sweep that froze waste and bumped the day, or a competing reconcile attempt —
    the values will not match, and the reconcile is rejected with ERR_STALE_VERSION
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_version_reconcile_rejected
    """
    day, _product, _batch = setup_cutoff_day_one_swept_batch(par_qty=10, baked_qty=10)
    current = validate_success(_ac.get_production_day(day["id"], BAKER))
    stale = current["version"] - 1
    resp = _ac.reconcile_day(
        day["id"], {"expected_production_day_version": stale}, BAKER)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)


# =====================================================================
# Corner/state_machines/reconcile_with_unswept_batch_rejected  (1)
# =====================================================================
def test_reconcile_with_unswept_batch_rejected(api):
    """PRD §3.9: "Every bake batch on the day must be SWEPT (else ERR_BATCHES_NOT_SWEPT)."

    Design: Corner/state_machines/reconcile_with_unswept_batch_rejected
    """
    day, _product, _batch = setup_selling_day_with_baked_batch(par_qty=10, baked_qty=10)
    validate_success(_ac.close_cutoff(day["id"], ADMIN))
    current = validate_success(_ac.get_production_day(day["id"], BAKER))
    resp = _ac.reconcile_day(
        day["id"], {"expected_production_day_version": current["version"]}, BAKER)
    validate_error(resp, ApiErrorId.ERR_BATCHES_NOT_SWEPT.value)


# =====================================================================
# Corner/state_machines/reconcile_terminal_day_rejected  (1)
# =====================================================================
def test_reconcile_already_reconciled_day_rejected(api):
    """PRD §3.2: "The day advances through a fixed posture sequence ... OPEN -> BAKING
    -> SELLING -> CUTOFF -> RECONCILED, with RECONCILED terminal."
    PRD §3.9: "The day must be in CUTOFF (else ERR_DAY_INVALID_STATE)."

    Design: Corner/state_machines/reconcile_terminal_day_rejected
    """
    day, _product, _batch = setup_cutoff_day_one_swept_batch(par_qty=10, baked_qty=10)
    v1 = validate_success(_ac.get_production_day(day["id"], BAKER))
    validate_success(_ac.reconcile_day(
        day["id"], {"expected_production_day_version": v1["version"]}, BAKER))
    v2 = validate_success(_ac.get_production_day(day["id"], BAKER))
    resp = _ac.reconcile_day(
        day["id"], {"expected_production_day_version": v2["version"]}, BAKER)
    validate_error(resp, ApiErrorId.ERR_DAY_INVALID_STATE.value)


# =====================================================================
# Corner/cross_cutting_complexity_layers/version_increments_on_mutation  (1)
# =====================================================================
def test_version_increments_after_start_baking(api):
    """PRD §2.4: "version, an integer that begins at its initial value on creation and
    increments by one on every mutation that changes the resource."

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_mutation
    """
    glazed = create_product("GLAZED")
    day = validate_success(_ac.create_production_day(
        {"business_date": "2027-09-13", "delivery_cutoff_utc": "2027-09-13T20:00:00Z"},
        ADMIN), 201)
    assert day["version"] == 1, f"new day version starts at 1; got {day['version']}"
    create_planned_batch(day["id"], glazed["id"], par_qty=10)
    started = validate_success(_ac.start_baking(day["id"], BAKER))
    assert started["version"] == 2, (
        f"start-baking is a mutation -> version 2; got {started['version']}")
