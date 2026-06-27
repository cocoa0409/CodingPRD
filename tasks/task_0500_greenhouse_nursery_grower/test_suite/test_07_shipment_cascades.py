"""Dispatch / void / cull cascades and compensating invariants across batch, zone,
order, broker, and availability.

Queue A (difficulty) — non_linear_state_machine, transitive_cascade,
compensating_invariant.
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_multi_line_order, setup_published_lot, create_shipment, confirm_order,
)

SC = TEST_USERS["sales_coordinator_headers"]
PT = TEST_USERS["production_tech_headers"]


# ─── A6: dispatch then compensating void on the shipment branch ──────────
def test_dispatch_deducts_live_count(api):
    """PRD 3.14: "the drawn-on batch's `shipped_count` is increased by that quantity,
    and the batch's `live_count` is reduced by that quantity."

    Design: Difficulty/non_linear_state_machine/shipment_dispatch_then_void_compensation_branch
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 100, "started": 500, "unit_price_cents": 300}],
        ship_to_state="NY", footprint=1, confirm=True, cultivar_code="VERF1")
    line_id = s["lines"][0]["id"]
    ship = create_shipment(api, s["order"]["id"], [{"order_line_id": line_id, "quantity": 60}])
    dispatched = validate_success(api.dispatch_shipment(ship["id"], SC))
    assert dispatched["status"] == "DISPATCHED"
    batch = validate_success(api.get_batch(s["batches"][0]["id"], PT))
    assert batch["live_count"] == 440, f"500 - 60 dispatched, got {batch['live_count']}"


def test_void_restores_live_count(api):
    """PRD 3.14: "for each line the `shipped_quantity` is reduced by the dispatched
    quantity, the batch's `shipped_count` is reduced by that quantity, and the
    batch's `live_count` is restored by that quantity."

    Design: Difficulty/non_linear_state_machine/shipment_dispatch_then_void_compensation_branch
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 100, "started": 500, "unit_price_cents": 300}],
        ship_to_state="NY", footprint=1, confirm=True, cultivar_code="VERF2")
    line_id = s["lines"][0]["id"]
    ship = create_shipment(api, s["order"]["id"], [{"order_line_id": line_id, "quantity": 60}])
    validate_success(api.dispatch_shipment(ship["id"], SC))
    voided = validate_success(api.void_shipment(ship["id"], SC))
    assert voided["status"] == "VOIDED"
    batch = validate_success(api.get_batch(s["batches"][0]["id"], PT))
    assert batch["live_count"] == 500, f"void must restore live to 500, got {batch['live_count']}"
    assert batch["shipped_count"] == 0


# ─── A7: depth-3 cascade dispatch -> order SHIPPED -> broker ledger ───────
def test_full_dispatch_zeroes_batch_live_and_marks_shipped(api):
    """PRD 3.14: "once every `COMMITTED` line has its `shipped_quantity` equal to its
    `quantity` the order is automatically driven to the terminal `SHIPPED` state".

    Design: Difficulty/transitive_cascade/dispatch_cascade_batch_order_broker_depth3
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 200, "started": 200, "unit_price_cents": 400}],
        ship_to_state="OR", credit_limit_cents=1000000, confirm=True, cultivar_code="SALG1")
    line_id = s["lines"][0]["id"]
    ship = create_shipment(api, s["order"]["id"], [{"order_line_id": line_id, "quantity": 200}])
    validate_success(api.dispatch_shipment(ship["id"], SC))
    batch = validate_success(api.get_batch(s["batches"][0]["id"], PT))
    assert batch["live_count"] == 0 and batch["shipped_count"] == 200
    order = validate_success(api.get_order(s["order"]["id"], SC))
    assert order["status"] == "SHIPPED"


def test_order_shipped_releases_broker_balance(api):
    """PRD 3.14: "When the order reaches `SHIPPED`, the broker's `open_balance_cents`
    is reduced by the order's `order_total_cents`, releasing that credit — a cascade
    onto the broker."

    Design: Difficulty/transitive_cascade/dispatch_cascade_batch_order_broker_depth3
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 200, "started": 200, "unit_price_cents": 400}],
        ship_to_state="OR", credit_limit_cents=1000000, confirm=True, cultivar_code="SALG2")
    line_id = s["lines"][0]["id"]
    ship = create_shipment(api, s["order"]["id"], [{"order_line_id": line_id, "quantity": 200}])
    validate_success(api.dispatch_shipment(ship["id"], SC))
    broker = validate_success(api.get_broker(s["broker"]["id"], SC))
    assert broker["open_balance_cents"] == 0, \
        f"shipped order releases the full balance, got {broker['open_balance_cents']}"


# ─── A8: cull a SALEABLE batch -> close availability -> release zone ──────
def test_saleable_cull_closes_availability_entry(api):
    """PRD 3.7: "When the batch is culled from `SALEABLE`, there is an additional
    cascade: any `OPEN` availability entry for this batch is moved to `CLOSED` and
    its `published_quantity` is set to 0."

    Design: Difficulty/transitive_cascade/saleable_cull_closes_availability_releases_zone_depth2
    """
    lot = setup_published_lot(api, footprint=2, sourced=150, started=150,
                              unit_price_cents=350, cultivar_code="LOBH1")
    culled = validate_success(api.cull_batch(lot["batch"]["id"], {"loss_basis": "STANDARD"}, PT))
    assert culled["status"] == "CULLED" and culled["live_count"] == 0
    entry = validate_success(api.get_availability(lot["entry"]["id"], SC))
    assert entry["status"] == "CLOSED"
    assert entry["published_quantity"] == 0


def test_saleable_cull_releases_zone_occupancy(api):
    """PRD 3.7: "the zone's `occupied_units` is reduced by the released footprint,
    its `free_units` and `fill_state` are recomputed, and its `version` is
    incremented by one."

    Design: Difficulty/transitive_cascade/saleable_cull_closes_availability_releases_zone_depth2
    """
    lot = setup_published_lot(api, footprint=2, sourced=150, started=150,
                              unit_price_cents=350, cultivar_code="LOBH2")
    validate_success(api.cull_batch(lot["batch"]["id"], {"loss_basis": "STANDARD"}, PT))
    zone = validate_success(api.get_zone(lot["zone"]["id"], SC))
    assert zone["occupied_units"] == 0, f"culled footprint must release, got {zone['occupied_units']}"


# ─── A17: dispatch/void conserves zone footprint ─────────────────────────
def test_dispatch_reduces_zone_occupancy(api):
    """PRD 3.14: "The freed footprint cascades onto the zone — the zone's
    `occupied_units` is reduced by the shipped footprint".

    Design: Difficulty/compensating_invariant/dispatch_void_conserves_zone_footprint_and_live_count
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 100, "started": 100, "unit_price_cents": 300}],
        ship_to_state="OR", footprint=2, confirm=True, cultivar_code="HOSS1")
    line_id = s["lines"][0]["id"]
    ship = create_shipment(api, s["order"]["id"], [{"order_line_id": line_id, "quantity": 40}])
    validate_success(api.dispatch_shipment(ship["id"], SC))
    zone = validate_success(api.get_zone(s["zone"]["id"], SC))
    assert zone["occupied_units"] == 120, f"200 - 40*2 footprint, got {zone['occupied_units']}"


def test_void_restores_zone_footprint_to_pre_dispatch(api):
    """PRD 3.14: "The restored footprint cascades onto the zone — the zone's
    `occupied_units` is increased by the restored footprint".

    Design: Difficulty/compensating_invariant/dispatch_void_conserves_zone_footprint_and_live_count
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 100, "started": 100, "unit_price_cents": 300}],
        ship_to_state="OR", footprint=2, confirm=True, cultivar_code="HOSS2")
    zone_before = validate_success(api.get_zone(s["zone"]["id"], SC))["occupied_units"]
    assert zone_before == 200
    line_id = s["lines"][0]["id"]
    ship = create_shipment(api, s["order"]["id"], [{"order_line_id": line_id, "quantity": 40}])
    validate_success(api.dispatch_shipment(ship["id"], SC))
    validate_success(api.void_shipment(ship["id"], SC))
    zone_after = validate_success(api.get_zone(s["zone"]["id"], SC))["occupied_units"]
    assert zone_after == 200, f"occupied after void must equal pre-dispatch 200, got {zone_after}"


# ─── A18: confirm/cancel conserves broker balance + committed quantity ───
def test_confirm_charges_balance_and_commits_quantity(api):
    """PRD 3.11: "the drawn-on availability entry has its `committed_quantity`
    increased by the line's `quantity` and its `available_quantity` recomputed — a
    cascade onto the entry."

    Design: Difficulty/compensating_invariant/confirm_cancel_conserves_open_balance_and_committed_quantity
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 200, "started": 200, "unit_price_cents": 500}],
        ship_to_state="OR", confirm=False, cultivar_code="YART1")
    confirm_order(api, s["order"]["id"])
    broker = validate_success(api.get_broker(s["broker"]["id"], SC))
    assert broker["open_balance_cents"] == 104900, f"got {broker['open_balance_cents']}"
    entry = validate_success(api.get_availability(s["entries"][0]["id"], SC))
    assert entry["committed_quantity"] == 200


def test_cancel_restores_balance_and_committed_quantity(api):
    """PRD 3.12: "every drawn-on availability entry has its `committed_quantity`
    reduced by that line's `quantity` and its `available_quantity` recomputed (a
    cascade onto the entry), the broker's `open_balance_cents` is reduced by the
    order's `order_total_cents` (a cascade onto the broker, reversing the confirm)".

    Design: Difficulty/compensating_invariant/confirm_cancel_conserves_open_balance_and_committed_quantity
    """
    s = setup_multi_line_order(
        line_specs=[{"quantity": 200, "started": 200, "unit_price_cents": 500}],
        ship_to_state="OR", confirm=False, cultivar_code="YART2")
    confirm_order(api, s["order"]["id"])
    validate_success(api.cancel_order(s["order"]["id"], SC))
    broker = validate_success(api.get_broker(s["broker"]["id"], SC))
    assert broker["open_balance_cents"] == 0, f"cancel must restore balance to 0, got {broker['open_balance_cents']}"
    entry = validate_success(api.get_availability(s["entries"][0]["id"], SC))
    assert entry["committed_quantity"] == 0
    assert entry["available_quantity"] == 200
