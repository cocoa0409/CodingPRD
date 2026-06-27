"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def register_customer_payload(**overrides) -> dict:
    defaults = {
        "email": "buyer@example.com",
        "full_name": "Test Buyer",
        "date_of_birth": "2000-01-01",
        "ship_state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def id_scan_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "id_state_code": "CA",
        "id_expiry_date": "2030-01-01",
        "scanned_dob": "2000-01-01",
    }
    defaults.update(overrides)
    return defaults


def product_payload(**overrides) -> dict:
    defaults = {
        "sku": "TEST-SKU-1",
        "name": "Test Product",
        "category": "WINE",
        "container_type": "BOTTLE",
        "bottle_volume_ml": 750,
        "abv_pct": 13.00,
    }
    defaults.update(overrides)
    return defaults


def vintage_payload(**overrides) -> dict:
    defaults = {
        "vintage_year": 2020,
        "list_price_cents": 3000,
        "case_pack_size": 6,
    }
    defaults.update(overrides)
    return defaults


def lot_payload(**overrides) -> dict:
    defaults = {
        "tax_status": "TAXED",
        "qty_on_hand": 10,
        "excise_band_cents_per_unit": 0,
    }
    defaults.update(overrides)
    return defaults


def state_rule_payload(state_code: str, **overrides) -> dict:
    defaults = {
        "state_code": state_code,
        "ship_allowed": True,
        "growler_keg_allowed": True,
        "requires_adult_signature": False,
    }
    defaults.update(overrides)
    return defaults


def order_payload(customer_id: str, channel: str = "POS", **overrides) -> dict:
    defaults = {"customer_id": customer_id, "channel": channel}
    defaults.update(overrides)
    return defaults


def order_line_payload(vintage_id: str, qty: int = 1, **overrides) -> dict:
    defaults = {"vintage_id": vintage_id, "qty": qty}
    defaults.update(overrides)
    return defaults


def membership_payload(customer_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def special_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "description": "rare item",
        "requested_qty": 1,
    }
    defaults.update(overrides)
    return defaults


def shipment_payload(carrier: str = "LICENSED_COMMON_CARRIER", **overrides) -> dict:
    defaults = {"carrier": carrier}
    defaults.update(overrides)
    return defaults
