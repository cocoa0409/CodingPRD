"""Payload factories — one per entity, input fields only."""
import itertools

_tag_counter = itertools.count(1)
_truck_counter = itertools.count(1)


def unique_asset_tag(prefix="T") -> str:
    return f"{prefix}-{next(_tag_counter):05d}"


def unique_truck_code(prefix="TRK") -> str:
    return f"{prefix}{next(_truck_counter):05d}"


def create_container_type_payload(**overrides) -> dict:
    defaults = {
        "size_code": "YD30",
        "base_rate_cents": 50000,
        "included_days": 7,
        "overage_day_cents": 1500,
        "included_tonnage_lbs": 4000,
        "overage_rate_cents_per_lb": 9,
    }
    defaults.update(overrides)
    return defaults


def create_contractor_account_payload(**overrides) -> dict:
    defaults = {
        "business_name": "Test Contractor",
        "credit_limit_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_container_payload(container_type_id, **overrides) -> dict:
    defaults = {
        "container_type_id": container_type_id,
        "asset_tag": unique_asset_tag(),
        "yard_code": "Y1",
    }
    defaults.update(overrides)
    return defaults


def create_rental_order_payload(account_id, container_type_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "container_type_id": container_type_id,
        "site_address": "1 Main St",
        "requested_delivery_date": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "service_date": "2026-06-01",
        "truck_code": unique_truck_code(),
        "capacity_stops": 5,
    }
    defaults.update(overrides)
    return defaults


def create_street_permit_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "municipality": "Springfield",
        "permit_fee_cents": 10000,
        "valid_from": "2026-06-01",
        "valid_until": "2026-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_weigh_ticket_payload(order_id, service_stop_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "service_stop_id": service_stop_id,
        "gross_weight_lbs": 13000,
        "tare_weight_lbs": 10000,
    }
    defaults.update(overrides)
    return defaults


def append_stop_payload(service_stop_id, expected_route_version, **overrides) -> dict:
    defaults = {
        "service_stop_id": service_stop_id,
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults


def dispatch_delivery_payload(container_id, expected_container_version, **overrides) -> dict:
    defaults = {
        "container_id": container_id,
        "expected_container_version": expected_container_version,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(current_date) -> dict:
    return {"current_date": current_date}
