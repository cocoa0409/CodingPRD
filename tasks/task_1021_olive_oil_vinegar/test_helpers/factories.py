"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_member_payload(**overrides) -> dict:
    payload = {
        "email": _uniq("member") + "@x.com",
        "full_name": "Test Member",
    }
    payload.update(overrides)
    return payload


def create_product_payload(product_type="BOTTLE", **overrides) -> dict:
    payload = {
        "sku": _uniq("SKU"),
        "name": "Test Product",
        "product_type": product_type,
    }
    payload.update(overrides)
    return payload


def create_bulk_product_payload(**overrides) -> dict:
    payload = create_product_payload(
        product_type="BULK_OIL",
        price_per_ml_cents=0.30,
        shelf_life_days=540,
    )
    payload.update(overrides)
    return payload


def create_fusti_payload(product_id, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "capacity_ml": 10000,
        "initial_volume_ml": 10000,
        "reorder_point_ml": 2000,
        "harvest_date": "2026-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_wholesale_account_payload(**overrides) -> dict:
    payload = {
        "business_name": "Test Trattoria",
        "tax_id": _uniq("TX"),
    }
    payload.update(overrides)
    return payload


def unit_line(product_id, quantity=1) -> dict:
    return {"line_type": "UNIT", "product_id": product_id, "quantity": quantity}


def refill_line(product_id, volume_ml, quantity=1) -> dict:
    return {"line_type": "REFILL", "product_id": product_id,
            "quantity": quantity, "volume_ml": volume_ml}


def bundle_line(product_id, quantity=1) -> dict:
    return {"line_type": "BUNDLE", "product_id": product_id, "quantity": quantity}


def create_order_payload(lines, **overrides) -> dict:
    payload = {"lines": lines}
    payload.update(overrides)
    return payload


def create_subscription_payload(product_id, cadence_days, expected_member_version, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "cadence_days": cadence_days,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload


def create_station_payload(**overrides) -> dict:
    payload = {"name": "Test Bar"}
    payload.update(overrides)
    return payload


def create_session_payload(station_id, start_at, end_at, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    payload.update(overrides)
    return payload
