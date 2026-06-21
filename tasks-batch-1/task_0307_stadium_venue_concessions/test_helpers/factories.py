"""Payload factories — one per entity, input fields only (PRD §3.x)."""


# ---------------------------------------------------------------------------
# Venue (PRD §3.1): name, venue_share_pct, service_fee_pct required;
#                   share_basis, spoilage_valuation optional (defaults GROSS/FIFO).
# ---------------------------------------------------------------------------
def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Coliseum",
        "venue_share_pct": 10,
        "service_fee_pct": 0,
        "share_basis": "GROSS",
        "spoilage_valuation": "FIFO",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Product (PRD §3.1): venue_id, sku, name, base_price_cents, unit_cost_cents
#                     required; perishable optional (default false).
# ---------------------------------------------------------------------------
def create_product_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "sku": "HOTDOG",
        "name": "Hot Dog",
        "base_price_cents": 1000,
        "unit_cost_cents": 200,
        "perishable": False,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Event (PRD §3.2): venue_id, name, doors_time, end_time required;
#                   event_multiplier_pct optional (default 100).
# ---------------------------------------------------------------------------
def create_event_payload(venue_id, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "name": "Test Event",
        "doors_time": "2026-09-01T18:00:00.000Z",
        "end_time": "2026-09-01T23:00:00.000Z",
        "event_multiplier_pct": 100,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Stand (PRD §3.2): event_id, name required;
#                   demand_tier (default MID), expected_orders_per_hour (default 0) optional.
# ---------------------------------------------------------------------------
def create_stand_payload(event_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "name": "Test Stand",
        "demand_tier": "MID",
        "expected_orders_per_hour": 40,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# MenuItem (PRD §3.4): stand_id, product_id required; available optional (default true).
# ---------------------------------------------------------------------------
def create_menu_item_payload(stand_id, product_id, **overrides) -> dict:
    defaults = {
        "stand_id": stand_id,
        "product_id": product_id,
        "available": True,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# InventoryLot (PRD §3.5): stand_id, product_id, received_qty, par_level,
#                          reorder_point required; unit_cost_cents, expires_at optional.
# ---------------------------------------------------------------------------
def create_inventory_lot_payload(stand_id, product_id, **overrides) -> dict:
    defaults = {
        "stand_id": stand_id,
        "product_id": product_id,
        "received_qty": 50,
        "unit_cost_cents": 30,
        "par_level": 50,
        "reorder_point": 10,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Replenishment (PRD §3.5): stand_id, product_id, requested_qty required.
# ---------------------------------------------------------------------------
def create_replenishment_payload(stand_id, product_id, **overrides) -> dict:
    defaults = {
        "stand_id": stand_id,
        "product_id": product_id,
        "requested_qty": 40,
    }
    defaults.update(overrides)
    return defaults


# Delivery body (PRD §3.5): par_level + reorder_point for the new lot.
def deliver_replenishment_payload(**overrides) -> dict:
    defaults = {"par_level": 60, "reorder_point": 10}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Transfer (PRD §3.5): from_stand_id, to_stand_id, product_id, qty required.
# ---------------------------------------------------------------------------
def create_transfer_payload(from_stand_id, to_stand_id, product_id, **overrides) -> dict:
    defaults = {
        "from_stand_id": from_stand_id,
        "to_stand_id": to_stand_id,
        "product_id": product_id,
        "qty": 10,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# WasteRecord (PRD §3.6): stand_id, product_id, reason, qty required; lot_id optional.
# ---------------------------------------------------------------------------
def create_waste_record_payload(stand_id, product_id, reason, qty, **overrides) -> dict:
    defaults = {
        "stand_id": stand_id,
        "product_id": product_id,
        "reason": reason,
        "qty": qty,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Order (PRD §3.8): event_id, stand_id, patron_id required.
# ---------------------------------------------------------------------------
def create_order_payload(event_id, stand_id, patron_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "stand_id": stand_id,
        "patron_id": patron_id,
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# OrderLine (PRD §3.8): menu_item_id, qty required.
# ---------------------------------------------------------------------------
def create_order_line_payload(menu_item_id, qty, **overrides) -> dict:
    defaults = {"menu_item_id": menu_item_id, "qty": qty}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Patron (PRD §3.8): display_name required.
# ---------------------------------------------------------------------------
def create_patron_payload(**overrides) -> dict:
    defaults = {"display_name": "Test Patron"}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# StaffShift (PRD §3.7): stand_id, worker_name, shift_start, shift_end required.
# ---------------------------------------------------------------------------
def create_staff_shift_payload(stand_id, **overrides) -> dict:
    defaults = {
        "stand_id": stand_id,
        "worker_name": "Test Worker",
        "shift_start": "2026-09-01T18:00:00.000Z",
        "shift_end": "2026-09-01T23:00:00.000Z",
    }
    defaults.update(overrides)
    return defaults
