"""Payload factories — one per entity, input fields only."""


def create_sku_payload(**overrides) -> dict:
    defaults = {
        "sku_code": "SKU-TEST-01",
        "category": "DECOR",
        "unit_price_cents": 500,
    }
    defaults.update(overrides)
    return defaults


def create_bundle_payload(**overrides) -> dict:
    defaults = {
        "bundle_code": "BUNDLE-TEST-01",
        "theme_tag": "GENERIC",
        "bundle_price_cents": 1000,
        "lines": [],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": "test-customer@example.com",
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, channel="IN_STORE", lines=None, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "channel": channel,
        "lines": lines or [],
    }
    defaults.update(overrides)
    return defaults


def create_helium_tank_payload(**overrides) -> dict:
    defaults = {
        "tank_code": "TANK-TEST-01",
        "capacity_cubic_ft": 100,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_slot_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2026-06-15T10:00:00Z",
        "window_end": "2026-06-15T12:00:00Z",
        "van_id": "V1",
    }
    defaults.update(overrides)
    return defaults


def create_rental_contract_payload(order_id, sku_id, qty=1,
                                    rental_start="2026-06-20T00:00:00Z",
                                    rental_end="2026-06-22T00:00:00Z",
                                    **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "sku_id": sku_id,
        "qty": qty,
        "rental_start": rental_start,
        "rental_end": rental_end,
    }
    defaults.update(overrides)
    return defaults


def create_custom_print_payload(**overrides) -> dict:
    defaults = {
        "art_reference": "https://art.example/design",
        "banner_length_ft": 5,
    }
    defaults.update(overrides)
    return defaults


def create_event_package_payload(**overrides) -> dict:
    defaults = {
        "package_code": "PKG-TEST-01",
        "base_price_cents": 20000,
        "deposit_pct": 0.30,
        "min_lead_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_event_booking_payload(order_id, event_package_id,
                                  event_date="2026-08-01T18:00:00Z",
                                  **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "event_package_id": event_package_id,
        "event_date": event_date,
    }
    defaults.update(overrides)
    return defaults


def create_helium_payload(latex_count=0, foil_count=0) -> dict:
    return {"latex_count": latex_count, "foil_count": foil_count}
