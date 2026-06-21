"""Direct-store-delivery receiving, the inventory-lot lifecycle (quarantine,
release, pull, expire), and the optimistic-concurrency guard on receiving and
price-plan creation.

Translates difficulty instances (queue A: non_linear_state_machine,
cross_entity_state_dependency, resource_temporal_overlap) and corner instances
(queue B: state_machines, cross_cutting_complexity_layers).
"""
from test_helpers import (
    validate_success, validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    fixtures,
)
from test_helpers.api_client import api_client

SM = TEST_USERS["store_manager_headers"]
PM = TEST_USERS["price_manager_headers"]
RC = TEST_USERS["receiving_clerk_headers"]
CSH = TEST_USERS["cashier_headers"]
AUD = TEST_USERS["inventory_auditor_headers"]


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine / lot_quarantine_release_cycle
# ---------------------------------------------------------------------------
def test_lot_quarantine_then_release_cycles_status(api):
    """PRD §3.3: "Quarantining moves a lot from `ACTIVE` to `QUARANTINED` and requires it to be `ACTIVE`, else `ERR_LOT_NOT_ACTIVE`."
    PRD §3.3: "Releasing moves a lot from `QUARANTINED` back to `ACTIVE`, requires it to be `QUARANTINED`, else `ERR_LOT_NOT_QUARANTINED`, and restores its FEFO eligibility."

    Design: Difficulty/non_linear_state_machine/lot_quarantine_release_cycle
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Beans", unit_price_cents=99,
                                      reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 10, unit_cost_cents=100)
    lot = fixtures.get_single_lot(product["id"])

    q = validate_success(api.quarantine_lot(lot["id"], AUD))
    assert q["status"] == "QUARANTINED"
    r = validate_success(api.release_lot(lot["id"], AUD))
    assert r["status"] == "ACTIVE"


def test_lot_quarantine_release_cycle_keeps_on_hand_unchanged(api):
    """PRD §3.3: "A quarantined lot still counts toward the product's
    `on_hand_qty` and its book value is unchanged — quarantine writes off nothing —
    but it is skipped by FEFO sale depletion while quarantined."

    Design: Difficulty/non_linear_state_machine/lot_quarantine_release_cycle
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Beans", unit_price_cents=99,
                                      reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 10, unit_cost_cents=100)
    lot = fixtures.get_single_lot(product["id"])

    api.quarantine_lot(lot["id"], AUD)
    after_q = get_success_data(api.get_product(product["id"], PM))
    assert after_q["on_hand_qty"] == 10
    api.release_lot(lot["id"], AUD)
    after_r = get_success_data(api.get_product(product["id"], PM))
    assert after_r["on_hand_qty"] == 10


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency / receive_blocked_when_product_discontinued
# ---------------------------------------------------------------------------
def test_receive_blocked_when_product_discontinued(api):
    """PRD §3.2: "Completing the receipt requires the shipment to be in `RECEIVING`, else `ERR_SHIPMENT_NOT_RECEIVING`, and requires that every referenced product be `ACTIVE`, else `ERR_PRODUCT_DISCONTINUED`."

    Design: Difficulty/cross_entity_state_dependency/receive_blocked_when_product_discontinued
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Old SKU", unit_price_cents=99,
                                      reorder_point_qty=0)
    ship = get_success_data(api.create_shipment(
        {"vendor_name": "V", "reference_code": "REF-K1", "expected_total_cents": 500}, RC))
    get_success_data(api.add_shipment_line(
        ship["id"], {"product_id": product["id"], "ordered_qty": 5,
                     "accepted_qty": 5, "unit_cost_cents": 100}, RC))
    get_success_data(api.start_receiving(ship["id"], RC))
    disc = get_success_data(api.discontinue_product(product["id"], SM))
    resp = api.receive_shipment(
        ship["id"], {"expected_product_version": disc["version"],
                     "override_variance": True}, SM)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)


def test_discontinue_already_discontinued_product_rejected(api):
    """PRD §3.1: "Discontinuing a product that is already discontinued, or attempting to receive a shipment line that targets a discontinued product, is rejected with `ERR_PRODUCT_DISCONTINUED`."

    Design: Difficulty/cross_entity_state_dependency/receive_blocked_when_product_discontinued
    """
    product = fixtures.create_product(name="Twice", unit_price_cents=99,
                                      reorder_point_qty=0)
    get_success_data(api.discontinue_product(product["id"], SM))
    resp = api.discontinue_product(product["id"], SM)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_DISCONTINUED.value)


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap / lot_expiry_inclusive_at_exact_expiration_instant
# ---------------------------------------------------------------------------
def test_lot_expirable_at_exact_expiration_instant(api):
    """PRD §3.3: "A lot may be expired from either `ACTIVE` or `QUARANTINED`, else `ERR_LOT_NOT_EXPIRABLE`, and only when its `expiration_date` is non-null and at or before the current clock ..."
    PRD §3.3: "A successful expiry drives the lot to `EXPIRED`, writes `remaining_qty` to 0, records the expired value as shrink ..."

    Design: Difficulty/resource_temporal_overlap/lot_expiry_inclusive_at_exact_expiration_instant
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Milk", unit_price_cents=99,
                                      is_perishable=True, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100,
                         expiration_date="2026-06-10T00:00:00Z")
    lot = fixtures.get_single_lot(product["id"])
    fixtures.advance_clock("2026-06-10T00:00:00Z")  # clock == expiration_date
    expired = validate_success(api.expire_lot(lot["id"], AUD))
    assert expired["status"] == "EXPIRED"
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["on_hand_qty"] == 0


def test_lot_not_expirable_before_due(api):
    """PRD §3.3: "an attempt to expire a lot whose expiration date is still in the future relative to the clock is rejected with `ERR_LOT_NOT_EXPIRED_YET`."

    Design: Difficulty/resource_temporal_overlap/lot_expiry_inclusive_at_exact_expiration_instant
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Milk2", unit_price_cents=99,
                                      is_perishable=True, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100,
                         expiration_date="2026-06-20T00:00:00Z")
    lot = fixtures.get_single_lot(product["id"])
    resp = api.expire_lot(lot["id"], AUD)  # clock 2026-06-05 < expiration
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_EXPIRED_YET.value)


# ---------------------------------------------------------------------------
# Corner: state_machines
# ---------------------------------------------------------------------------
def test_quarantine_already_quarantined_lot_returns_not_active(api):
    """PRD §3.3: "Quarantining moves a lot from `ACTIVE` to `QUARANTINED` and requires it to be `ACTIVE`, else `ERR_LOT_NOT_ACTIVE`."

    Design: Corner/state_machines/quarantine_already_quarantined_lot_returns_not_active
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Q", unit_price_cents=99, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    lot = fixtures.get_single_lot(product["id"])
    get_success_data(api.quarantine_lot(lot["id"], AUD))
    resp = api.quarantine_lot(lot["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_ACTIVE.value)


def test_new_shipment_initial_state_pending(api):
    """PRD §3.2: "A fresh shipment is in `PENDING`."

    Design: Corner/state_machines/new_shipment_initial_state_pending
    """
    resp = api.create_shipment(
        {"vendor_name": "V", "reference_code": "REF-INIT", "expected_total_cents": 100}, RC)
    data = validate_success(resp, 201)
    assert data["status"] == "PENDING"


def test_terminal_received_shipment_cannot_reject(api):
    """PRD §3.2: "Rejecting a receipt instead moves the shipment from `RECEIVING` to `REJECTED`, requires the shipment to be in `RECEIVING` (else `ERR_SHIPMENT_NOT_RECEIVING`) ..."

    Design: Corner/state_machines/terminal_received_shipment_cannot_reject
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="T", unit_price_cents=99, reorder_point_qty=0)
    ship, _ = fixtures.receive_lot(product["id"], 5, unit_cost_cents=100,
                                   expected_total_cents=500)
    resp = api.reject_shipment(ship["id"], RC)
    validate_error(resp, ApiErrorId.ERR_SHIPMENT_NOT_RECEIVING.value)


def test_pull_lot_writeoff_drops_on_hand_to_zero(api):
    """PRD §3.3: "A pull is permitted from either `ACTIVE` or `QUARANTINED` ... it drives the lot to `PULLED`, writes its `remaining_qty` down to 0 ... The pull then triggers the product inventory rollup and the cascading reorder-flag recompute ..."

    Design: Corner/state_machines/pull_lot_writeoff_drops_on_hand_to_zero
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Pull", unit_price_cents=99, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100)
    lot = fixtures.get_single_lot(product["id"])
    pulled = validate_success(api.pull_lot(lot["id"], AUD))
    assert pulled["status"] == "PULLED"
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["on_hand_qty"] == 0
    assert prod["on_hand_value_cents"] == 0


def test_expire_lot_before_due_returns_not_expired_yet(api):
    """PRD §3.3: "an attempt to expire a lot whose expiration date is still in the future relative to the clock is rejected with `ERR_LOT_NOT_EXPIRED_YET`."

    Design: Corner/state_machines/expire_lot_before_due_returns_not_expired_yet
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="Yogurt", unit_price_cents=99,
                                      is_perishable=True, reorder_point_qty=0)
    fixtures.receive_lot(product["id"], 5, unit_cost_cents=100,
                         expiration_date="2026-06-20T00:00:00Z")
    lot = fixtures.get_single_lot(product["id"])
    resp = api.expire_lot(lot["id"], AUD)
    validate_error(resp, ApiErrorId.ERR_LOT_NOT_EXPIRED_YET.value)


# ---------------------------------------------------------------------------
# Corner: cross_cutting_complexity_layers — OCC
# ---------------------------------------------------------------------------
def test_occ_stale_product_version_on_receive(api):
    """PRD §2.7: "If `expected_product_version` does not equal that product's current `version`, the receive is rejected with `ERR_STALE_PRODUCT_VERSION` (HTTP 412) before any lot is created or any value is bumped."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_product_version_on_receive
    """
    fixtures.advance_clock("2026-06-05T00:00:00Z")
    product = fixtures.create_product(name="OCC", unit_price_cents=100, reorder_point_qty=0)
    pv1 = product["version"]
    ship = get_success_data(api.create_shipment(
        {"vendor_name": "V", "reference_code": "REF-OCC", "expected_total_cents": 500}, RC))
    get_success_data(api.add_shipment_line(
        ship["id"], {"product_id": product["id"], "ordered_qty": 5,
                     "accepted_qty": 5, "unit_cost_cents": 100}, RC))
    get_success_data(api.start_receiving(ship["id"], RC))
    # A price-plan create advances the product's version, making pv1 stale.
    fixtures.create_price_plan(product["id"], 90, "2026-06-01T00:00:00Z",
                               "2026-06-30T00:00:00Z", expected_product_version=pv1)
    resp = api.receive_shipment(
        ship["id"], {"expected_product_version": pv1, "override_variance": True}, SM)
    validate_error(resp, ApiErrorId.ERR_STALE_PRODUCT_VERSION.value)


def test_occ_correct_product_version_on_priceplan_succeeds(api):
    """PRD §2.7: "Creating a price plan must include `expected_product_version` carrying the `version` the price manager last observed for the target product."
    PRD §3.5: "the create carries the optimistic-concurrency `expected_product_version` of §2.7, advancing the product's `version` on success."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_product_version_on_priceplan_succeeds
    """
    product = fixtures.create_product(name="OCC2", unit_price_cents=200, reorder_point_qty=0)
    pv1 = product["version"]
    resp = api.create_price_plan(
        {"product_id": product["id"], "ad_price_cents": 150,
         "effective_start": "2026-07-01T00:00:00Z",
         "effective_end": "2026-07-08T00:00:00Z",
         "expected_product_version": pv1}, PM)
    plan = validate_success(resp, 201)
    assert plan["status"] == "SCHEDULED"
    prod = get_success_data(api.get_product(product["id"], PM))
    assert prod["version"] == pv1 + 1
