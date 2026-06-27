"""Inventory lot state machine, care log, and shrink valuation.

Difficulty: shrink_valuation_provisional_vs_final_on_lot, inventory_lot_quarantine_cycle.
Corner: release_already_available_lot_returns_invalid_state,
quarantine_lot_with_reservations_rejected.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    factories as F, fixtures as X,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INV = TEST_USERS["inventory_manager_headers"]
CLERK = TEST_USERS["sales_clerk_headers"]


# ---------------------------------------------------------------------------
# Difficulty: shrink_valuation_provisional_vs_final_on_lot
# ---------------------------------------------------------------------------
def _lot_with_two_shrink_units():
    """Released lot received_qty=10 @ 250, two SHRINK_LOSS entries totalling 2 lost."""
    X.set_clock("2026-05-01T08:00:00Z")
    nursery = X.create_nursery()
    product = X.create_live_plant(nursery["id"], sku="PL-1", name="Hosta",
                                  hardiness_min_zone=3, hardiness_max_zone=9,
                                  unit_price_cents=1200, warranty_days=30, warranty_pct=100)
    lot = X.create_released_lot(product["id"], received_qty=10, unit_cost_cents=250)
    api_client.create_care_log(lot["id"], F.create_care_log_payload(entry_type="SHRINK_LOSS", qty_lost=1, note="wilt"), INV)
    api_client.create_care_log(lot["id"], F.create_care_log_payload(entry_type="SHRINK_LOSS", qty_lost=1, note="wilt"), INV)
    return lot["id"]


def test_provisional_shrink_value_is_logged_qty_times_unit_cost(api):
    """PRD §3.2: "its **provisional** shrink valuation is computed as the lot's
    accumulated shrink quantity multiplied by its unit acquisition cost, and stored
    in `provisional_shrink_value_cents`."

    Design: Difficulty/dual_variant_calc/shrink_valuation_provisional_vs_final_on_lot
    """
    lot_id = _lot_with_two_shrink_units()
    data = validate_success(api.get_inventory_lot(lot_id, INV))
    assert data["shrink_qty"] == 2
    assert data["provisional_shrink_value_cents"] == 500, "2 lost * 250 unit_cost"


def test_final_shrink_valuation_at_depletion_exceeds_provisional(api):
    """PRD §3.2: "When a lot reaches `DEPLETED`, a **final** shrink valuation is
    taken instead: every unit that was never sold is treated as loss, so the final
    shrink value is the received quantity minus the sold quantity, multiplied by the
    unit acquisition cost."

    Design: Difficulty/dual_variant_calc/shrink_valuation_provisional_vs_final_on_lot
    """
    lot_id = _lot_with_two_shrink_units()
    # Lose the remaining 8 units -> qty_on_hand 0 -> DEPLETED, nothing ever sold.
    api.create_care_log(lot_id, F.create_care_log_payload(entry_type="SHRINK_LOSS", qty_lost=8, note="total loss"), INV)
    data = validate_success(api.get_inventory_lot(lot_id, INV))
    assert data["status"] == "DEPLETED"
    # final = (received 10 - sold 0) * 250 = 2500, exceeding the provisional 500.
    assert data["qty_on_hand"] == 0
    assert data["sold_qty"] == 0
    assert data["provisional_shrink_value_cents"] == 2500


# ---------------------------------------------------------------------------
# Difficulty: inventory_lot_quarantine_cycle
# ---------------------------------------------------------------------------
def test_lot_cycles_quarantine_available_quarantine_available(api):
    """PRD §3.2: "A lot may bounce between `AVAILABLE` and `QUARANTINE` any number
    of times while it still holds stock".

    Design: Difficulty/non_linear_state_machine/inventory_lot_quarantine_cycle
    """
    nursery = X.create_nursery()
    product = X.create_live_plant(nursery["id"], sku="PL-Q", name="Ivy",
                                  hardiness_min_zone=3, hardiness_max_zone=9, unit_price_cents=600)
    lot = X.create_lot(product["id"], received_qty=5, unit_cost_cents=200)
    validate_success(api.release_lot(lot["id"], INV))      # QUARANTINE -> AVAILABLE
    validate_success(api.quarantine_lot(lot["id"], INV))   # AVAILABLE -> QUARANTINE
    final = validate_success(api.release_lot(lot["id"], INV))  # QUARANTINE -> AVAILABLE
    assert final["status"] == "AVAILABLE"


def test_lot_version_increments_once_per_transition(api):
    """PRD §3.2: "each release and each quarantine increments the lot's `version`
    by one."

    Design: Difficulty/non_linear_state_machine/inventory_lot_quarantine_cycle
    """
    nursery = X.create_nursery()
    product = X.create_live_plant(nursery["id"], sku="PL-Q2", name="Ivy2",
                                  hardiness_min_zone=3, hardiness_max_zone=9, unit_price_cents=600)
    lot = X.create_lot(product["id"], received_qty=5, unit_cost_cents=200)
    v0 = validate_success(api.get_inventory_lot(lot["id"], INV))["version"]
    validate_success(api.release_lot(lot["id"], INV))
    validate_success(api.quarantine_lot(lot["id"], INV))
    final = validate_success(api.release_lot(lot["id"], INV))
    assert final["version"] == v0 + 3, "three transitions => +3 versions"


# ---------------------------------------------------------------------------
# Corner: invalid / precondition transitions
# ---------------------------------------------------------------------------
def test_release_already_available_lot_rejected(api):
    """PRD §3.2: "Releasing a lot, which advances it from `QUARANTINE` to
    `AVAILABLE`, ... requires that the lot currently be in `QUARANTINE` (otherwise
    `ERR_LOT_NOT_QUARANTINED`)".

    Design: Corner/state_machines/release_already_available_lot_returns_invalid_state
    """
    nursery = X.create_nursery()
    product = X.create_live_plant(nursery["id"], sku="PL-R", name="Rose",
                                  hardiness_min_zone=4, hardiness_max_zone=9, unit_price_cents=900)
    lot = X.create_released_lot(product["id"], received_qty=3, unit_cost_cents=300)
    resp = api.release_lot(lot["id"], INV)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_QUARANTINED.value)


def test_quarantine_lot_with_reservations_rejected(api):
    """PRD §3.2: "from `AVAILABLE` to `QUARANTINE`, provided the lot is currently
    `AVAILABLE` ... and holds no reservations, meaning its reserved quantity is 0
    (otherwise `ERR_LOT_HAS_RESERVATIONS`)."

    Design: Corner/state_machines/quarantine_lot_with_reservations_rejected
    """
    nursery = X.create_nursery()
    account = X.create_account(nursery["id"])
    product = X.create_product(nursery["id"], sku="DG-R", name="Rake", unit_price_cents=1200)
    lot = X.create_released_lot(product["id"], received_qty=5, unit_cost_cents=400)
    order = X.create_order(account["id"])
    X.add_line(order["id"], product["id"], qty=5)
    c = X.confirm(order["id"], order["version"])
    X.allocate(order["id"], c["version"])  # reserves 5 on the lot
    resp = api.quarantine_lot(lot["id"], INV)
    validate_error(resp, ApiErrorId.ERR_LOT_HAS_RESERVATIONS.value)
