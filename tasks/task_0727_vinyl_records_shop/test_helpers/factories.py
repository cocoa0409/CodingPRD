"""Payload factories — one per entity, input fields only."""


def create_customer_payload(**overrides) -> dict:
    defaults = {"email": "buyer@example.com", "full_name": "Test Buyer"}
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "artist": "Test Artist",
        "title": "Test Title",
        "format": "VINYL",
        "base_price_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(**overrides) -> dict:
    defaults = {
        "allocation_total": 1,
        "window_open_at": "2026-03-01T00:00:00Z",
        "window_close_at": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_inventory_item_payload(**overrides) -> dict:
    defaults = {"is_used": False, "condition_grade": "NM"}
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {"channel": "ONLINE"}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(**overrides) -> dict:
    defaults = {"payout_method": "CREDIT"}
    defaults.update(overrides)
    return defaults


def create_trade_in_line_payload(**overrides) -> dict:
    defaults = {"format": "VINYL", "claimed_grade": "NM", "base_value_cents": 1000}
    defaults.update(overrides)
    return defaults


def create_preorder_payload(**overrides) -> dict:
    defaults = {
        "pickup_window_start": "2026-04-01T09:00:00Z",
        "pickup_window_end": "2026-04-01T17:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_display_slot_payload(**overrides) -> dict:
    defaults = {"slot_label": "Front Window A"}
    defaults.update(overrides)
    return defaults


def create_consignment_payload(**overrides) -> dict:
    defaults = {"list_price_cents": 5000, "condition_grade": "VG"}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {"claimed_grade": "VG_PLUS"}
    defaults.update(overrides)
    return defaults


def create_special_order_payload(**overrides) -> dict:
    defaults = {"description": "rare pressing", "deposit_cents": 0}
    defaults.update(overrides)
    return defaults
