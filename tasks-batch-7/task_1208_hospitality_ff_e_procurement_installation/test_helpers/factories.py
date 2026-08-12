"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "PROJECT_NAME": "Test Project",
    "HOTEL_NAME": "Hotel Test",
    "BRAND_PROGRAM": "MARQUEE_SELECT",
    "TOTAL_BUDGET_CENTS": 10_000_000,
    "CATEGORY": "FURNITURE",
    "BUDGETED_CENTS": 8_000_000,
    "SPEC_DESCRIPTION": "Guest chair",
    "BRAND_STANDARD_REF": "MS-GR-01",
    "QUANTITY_PER_ROOM": 2,
    "ROOM_COUNT": 20,
    "UNIT_BUDGET_CENTS": 15000,
    "VENDOR_NAME": "VENDA",
    "UNIT_PRICE_CENTS": 15000,
    "FREIGHT_ESTIMATE_CENTS": 0,
    "LEAD_TIME_DAYS": 14,
    "QUANTITY_ORDERED": 40,
    "DECLARED_CUBE_M3": 10,
    "CARRIER_NAME": "CARR",
    "ROOM_NUMBER": "R-101",
    "ROOM_TYPE": "GUEST_KING",
    "FLOOR_NUMBER": 1,
    "START_DATE": "2026-07-01",
    "END_DATE": "2026-07-05",
    "CREW_COUNT": 1,
    "TASK_QUANTITY": 1,
    "CO_TITLE": "Owner change order",
    "CLAIMED_CREDIT_CENTS": 10000,
}


def create_project_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROJECT_NAME"],
        "hotel_name": DEFAULTS["HOTEL_NAME"],
        "brand_program": DEFAULTS["BRAND_PROGRAM"],
        "total_budget_cents": DEFAULTS["TOTAL_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_budget_line_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "category": DEFAULTS["CATEGORY"],
        "budgeted_cents": DEFAULTS["BUDGETED_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_spec_item_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "category": DEFAULTS["CATEGORY"],
        "description": DEFAULTS["SPEC_DESCRIPTION"],
        "brand_standard_ref": DEFAULTS["BRAND_STANDARD_REF"],
        "quantity_per_room": DEFAULTS["QUANTITY_PER_ROOM"],
        "room_count": DEFAULTS["ROOM_COUNT"],
        "unit_budget_cents": DEFAULTS["UNIT_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(spec_item_id: str, **overrides) -> dict:
    defaults = {
        "spec_item_id": spec_item_id,
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"],
        "freight_estimate_cents": DEFAULTS["FREIGHT_ESTIMATE_CENTS"],
        "lead_time_days": DEFAULTS["LEAD_TIME_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_purchase_order_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "vendor_name": DEFAULTS["VENDOR_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_po_line_payload(spec_item_id: str, **overrides) -> dict:
    defaults = {
        "spec_item_id": spec_item_id,
        "quantity_ordered": DEFAULTS["QUANTITY_ORDERED"],
        "declared_cube_m3": DEFAULTS["DECLARED_CUBE_M3"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "carrier_name": DEFAULTS["CARRIER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_receiving_event_payload(shipment_id: str, lines: list, **overrides) -> dict:
    """lines: list of {"po_line_id": ..., "qty_received": ..., "qty_damaged": ...}."""
    defaults = {
        "shipment_id": shipment_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_damage_claim_payload(po_line_id: str, **overrides) -> dict:
    defaults = {
        "po_line_id": po_line_id,
        "claim_type": "DAMAGE",
        "quantity": 1,
        "claimed_credit_cents": DEFAULTS["CLAIMED_CREDIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "floor_number": DEFAULTS["FLOOR_NUMBER"],
        "room_number": DEFAULTS["ROOM_NUMBER"],
        "room_type": DEFAULTS["ROOM_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_installation_window_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "floor_number": DEFAULTS["FLOOR_NUMBER"],
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
        "crew_count": DEFAULTS["CREW_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_installation_task_payload(
    window_id: str, room_id: str, po_line_id: str, **overrides
) -> dict:
    defaults = {
        "window_id": window_id,
        "room_id": room_id,
        "po_line_id": po_line_id,
        "quantity": DEFAULTS["TASK_QUANTITY"],
    }
    defaults.update(overrides)
    return defaults


def create_change_order_payload(project_id: str, adjustments: list, **overrides) -> dict:
    """adjustments: list of {"budget_line_id": ..., "delta_cents": ...}."""
    defaults = {
        "project_id": project_id,
        "title": DEFAULTS["CO_TITLE"],
        "adjustments": adjustments,
    }
    defaults.update(overrides)
    return defaults


def create_attic_transfer_payload(po_line_version: int, **overrides) -> dict:
    defaults = {
        "direction": "IN",
        "quantity": 1,
        "expected_po_line_version": po_line_version,
    }
    defaults.update(overrides)
    return defaults
