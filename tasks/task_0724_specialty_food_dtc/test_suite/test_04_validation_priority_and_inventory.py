"""Validation precedence pairs, lot expiry/FEFO temporal semantics, label-gate cross-entity.

Difficulty queue: priority_pair_validation_conflict, resource_temporal_overlap (lot expiry),
cross_entity_state_dependency (activate requires label).
Corner queue: validations + calculations (FEFO) instances.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_order_payload, create_order_line_payload,
    create_lot_payload, release_lot_payload,
    create_active_sku_with_lot, create_draft_sku, create_quarantine_lot,
    create_customer, build_reserved_order, build_paid_reserved_order,
    make_customer_headers, TEST_USERS, ApiErrorId, NON_EXISTENT_UUID,
)

INV = TEST_USERS["inventory_manager_headers"]
COMP = TEST_USERS["compliance_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


# ───────────────────────── validation precedence ─────────────────────────

def test_reserve_already_reserved_returns_invalid_state_over_inventory(api):
    """PRD §2.9: "Only then is the OCC version check applied (ERR_STALE_VERSION), followed by
    the state-machine legality check that the target entity is in a permitted from-state for
    the requested transition (ERR_INVALID_STATE). Business-safety, temporal, and fiscal checks
    — described alongside the workflows they guard in §3 — are evaluated after all of the
    foregoing."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_inventory_on_reserve
    """
    # Order reserved consuming all 2 units (so a second reserve also has zero availability).
    sku, lot = create_active_sku_with_lot(name="Dual Sauce", category="HOT_SAUCE",
                                          storage_class="AMBIENT", unit_price_cents=1000,
                                          produced_units=2)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = build_reserved_order(cid, [(sku["id"], 2)])
    # Second reserve: illegal from-state (already RESERVED) AND no inventory left.
    res = api.reserve_order(order["id"], make_customer_headers(cid))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_reserve_shipped_order_returns_invalid_state_not_fiscal(api):
    """PRD §2.9: "followed by the state-machine legality check that the target entity is in a
    permitted from-state for the requested transition (ERR_INVALID_STATE). Business-safety,
    temporal, and fiscal checks ... are evaluated after all of the foregoing."

    Design: Difficulty/priority_pair_validation_conflict/priority_state_beats_fiscal_inventory_on_reserve
    """
    # Order shipped (committing all 2 units) -> SKU availability now 0; re-reserving is both an
    # illegal from-state (SHIPPED) and would lack inventory. State check (P8) must win.
    sku, lot = create_active_sku_with_lot(name="Dual2 Sauce", category="HOT_SAUCE",
                                          storage_class="AMBIENT", unit_price_cents=1000,
                                          produced_units=2)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = build_paid_reserved_order(cid, [(sku["id"], 2)])
    validate_success(api.ship_order(order["id"], INV), 200)
    res = api.reserve_order(order["id"], make_customer_headers(cid))
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)


def test_ship_nonexistent_order_returns_not_found_over_state(api):
    """PRD §2.9: "Next the system confirms that every resource named in the path or body
    exists — validated left-to-right, so that for a nested path the first missing identifier
    raises ERR_NOT_FOUND before any later one is examined."

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_beats_state_on_ship
    """
    res = api.ship_order(NON_EXISTENT_UUID, INV)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


def test_deliver_nonexistent_order_returns_not_found_over_state(api):
    """PRD §2.9: "Next the system confirms that every resource named in the path or body
    exists — validated left-to-right, so that for a nested path the first missing identifier
    raises ERR_NOT_FOUND before any later one is examined."

    Design: Difficulty/priority_pair_validation_conflict/priority_existence_beats_state_on_ship
    """
    # A non-existent order can be neither shipped nor delivered; existence (P4) precedes the
    # state-machine legality check (P8), so the error is ERR_NOT_FOUND, not ERR_INVALID_STATE.
    res = api.deliver_order(NON_EXISTENT_UUID, INV)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)


# ───────────────────────── lot expiry temporal upper bound ─────────────────────────

def test_reserve_excludes_expired_lot_at_expiry_instant(api):
    """PRD §3.3: "choosing among that SKU's lots that are RELEASED and whose expiry_iso is
    after the current clock, taking the earliest expiry_iso and breaking ties by earliest
    created_at"
    PRD §3.3: "a shortfall on any line is rejected with ERR_INSUFFICIENT_INVENTORY."

    Design: Difficulty/resource_temporal_overlap/temporal_lot_expiry_excludes_from_fefo
    """
    # Lot expires at 2026-04-01; clock advanced to exactly that instant -> excluded (half-open).
    sku, lot = create_active_sku_with_lot(name="Exp Coffee", category="COFFEE",
                                          storage_class="AMBIENT", unit_price_cents=1000,
                                          produced_units=5, expiry_iso="2026-04-01T00:00:00Z")
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    get_success_data(api.set_clock("2026-04-01T00:00:00Z", ADMIN))
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z1"), make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku["id"], 1), make_customer_headers(cid))
    res = api.reserve_order(order["id"], make_customer_headers(cid))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)


def test_reserve_insufficient_inventory_when_no_consumable_lot(api):
    """PRD §3.3: "and that for every line the SKU's available_units is at least the line
    quantity; a shortfall on any line is rejected with ERR_INSUFFICIENT_INVENTORY."
    PRD §3.2: "an expired lot is excluded both from the lot selector and from any SKU's
    available_units."

    Design: Difficulty/resource_temporal_overlap/temporal_lot_expiry_excludes_from_fefo
    """
    sku, lot = create_active_sku_with_lot(name="Exp2 Coffee", category="COFFEE",
                                          storage_class="AMBIENT", unit_price_cents=1000,
                                          produced_units=5, expiry_iso="2026-04-01T00:00:00Z")
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    get_success_data(api.set_clock("2026-05-01T00:00:00Z", ADMIN))  # well past expiry
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z1"), make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku["id"], 1), make_customer_headers(cid))
    res = api.reserve_order(order["id"], make_customer_headers(cid))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value)


# ───────────────────────── cross-entity: activate requires label approved ─────────────────────────

def test_activate_without_label_approval_rejected(api):
    """PRD §3.2: "Attempting to activate a SKU whose label is not approved is rejected with
    ERR_LABEL_NOT_APPROVED"

    Design: Difficulty/cross_entity_state_dependency/cross_entity_activate_requires_label_approved
    """
    sku = create_draft_sku(name="NoLabel Sauce", category="HOT_SAUCE",
                           storage_class="AMBIENT", unit_price_cents=1000)
    # A lot exists but is still QUARANTINE; label was never approved.
    create_quarantine_lot(sku["id"], produced_units=5)
    res = api.activate_sku(sku["id"], INV)
    validate_error(res, ApiErrorId.ERR_LABEL_NOT_APPROVED.value)


def test_activate_requires_label_before_any_other_check(api):
    """PRD §3.2: "Activation is then performed by an InventoryManager, moving the SKU
    DRAFT → ACTIVE, but only when two preconditions hold: label_approved is true, and the
    SKU has at least one lot in RELEASED status."

    Design: Difficulty/cross_entity_state_dependency/cross_entity_activate_requires_label_approved
    """
    sku = create_draft_sku(name="NoLabel2 Sauce", category="COFFEE",
                           storage_class="AMBIENT", unit_price_cents=1000)
    res = api.activate_sku(sku["id"], INV)
    validate_error(res, ApiErrorId.ERR_LABEL_NOT_APPROVED.value)


# ───────────────────────── FEFO selection (corner) ─────────────────────────

def test_fefo_selects_earliest_expiry_lot(api):
    """PRD §3.3: "the system runs a first-expiry-first-out (FEFO) selector to pick the lot,
    choosing among that SKU's lots that are RELEASED and whose expiry_iso is after the current
    clock, taking the earliest expiry_iso and breaking ties by earliest created_at; the chosen
    lot is recorded as the line's lot_id."

    Design: Corner/calculations/fefo_selects_earliest_expiry_lot
    """
    sku = create_draft_sku(name="FEFO Coffee", category="COFFEE",
                           storage_class="AMBIENT", unit_price_cents=1000)
    get_success_data(api.approve_label(sku["id"], COMP))
    # Create LATE lot first, then EARLY lot — FEFO must still pick EARLY.
    late = get_success_data(api.create_lot(
        create_lot_payload(sku["id"], lot_code="LATE", produced_units=5,
                           expiry_iso="2026-09-01T00:00:00Z"), INV))
    get_success_data(api.release_lot(late["id"], release_lot_payload(late["version"]), INV))
    early = get_success_data(api.create_lot(
        create_lot_payload(sku["id"], lot_code="EARLY", produced_units=5,
                           expiry_iso="2026-05-01T00:00:00Z"), INV))
    get_success_data(api.release_lot(early["id"], release_lot_payload(early["version"]), INV))
    get_success_data(api.activate_sku(sku["id"], INV))

    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = get_success_data(api.create_order(
        create_order_payload(cid, order_kind="ONE_TIME", ship_zone="Z1"), make_customer_headers(cid)))
    api.add_order_line(order["id"], create_order_line_payload(sku["id"], 1), make_customer_headers(cid))
    validate_success(api.reserve_order(order["id"], make_customer_headers(cid)), 200)
    lines, _meta = validate_paginated(api.list_order_lines(order["id"], make_customer_headers(cid)))
    assert lines[0]["lot_id"] == early["id"], "FEFO picks earliest expiry lot"


# ───────────────────────── ship lot understock (corner) ─────────────────────────

def test_ship_lot_understock_after_recall_rejected(api):
    """PRD §3.5: "a lot whose remaining_units is below the line quantity is rejected with
    ERR_LOT_UNDERSTOCK."

    Design: Corner/validations/ship_lot_understock_rejected
    """
    sku, lot = create_active_sku_with_lot(name="Us Sauce", category="HOT_SAUCE",
                                          storage_class="AMBIENT", unit_price_cents=1000,
                                          produced_units=5)
    cust = create_customer(home_zone="Z1")
    cid = cust["id"]
    order = build_paid_reserved_order(cid, [(sku["id"], 1)])
    # Recall the lot before ship -> remaining_units 0 -> understock at ship.
    validate_success(api.recall_lot(lot["id"], COMP), 200)
    res = api.ship_order(order["id"], INV)
    validate_error(res, ApiErrorId.ERR_LOT_UNDERSTOCK.value)


def test_lot_release_after_expiry_rejected(api):
    """PRD §3.2: "Releasing a lot moves it QUARANTINE → RELEASED and requires both that the
    lot's expiry_iso is strictly after the current clock and that the parent SKU's
    label_approved is true ... A release attempted on an expired lot is rejected with
    ERR_LOT_EXPIRED"

    Design: Corner/validations/lot_release_after_expiry_rejected
    """
    sku = create_draft_sku(name="ExpRel Coffee", category="COFFEE",
                           storage_class="AMBIENT", unit_price_cents=1000)
    get_success_data(api.approve_label(sku["id"], COMP))
    lot = get_success_data(api.create_lot(
        create_lot_payload(sku["id"], lot_code="LA", produced_units=5,
                           expiry_iso="2026-04-01T00:00:00Z"), INV))
    get_success_data(api.set_clock("2026-04-02T00:00:00Z", ADMIN))
    res = api.release_lot(lot["id"], release_lot_payload(lot["version"]), INV)
    validate_error(res, ApiErrorId.ERR_LOT_EXPIRED.value)
