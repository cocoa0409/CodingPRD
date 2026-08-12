"""Payload factories — one per entity, input fields only."""
from .constants import DEFAULT_PERIOD_END, DEFAULT_PERIOD_START

_counter = {"n": 0}


def _uniq(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']}"


def create_zone_payload(**overrides) -> dict:
    defaults = {"name": _uniq("Zone"), "base_callout_fee_cents": 2500}
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Customer"),
        "email": f"{_uniq('user')}@example.com",
        "account_kind": "INDIVIDUAL",
    }
    defaults.update(overrides)
    return defaults


def create_bike_payload(customer_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "bike_type": "MECHANICAL"}
    defaults.update(overrides)
    return defaults


def create_mechanic_payload(home_zone_id, **overrides) -> dict:
    defaults = {
        "name": _uniq("Mechanic"),
        "ebike_certified": False,
        "home_zone_id": home_zone_id,
    }
    defaults.update(overrides)
    return defaults


def create_van_payload(zone_id, **overrides) -> dict:
    defaults = {
        "plate": _uniq("VAN"),
        "zone_id": zone_id,
        "max_stops_per_day": 8,
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "name": _uniq("Part"),
        "unit_price_cents": 1200,
        "warranty_days": 90,
    }
    defaults.update(overrides)
    return defaults


def create_service_tier_payload(**overrides) -> dict:
    defaults = {
        "code": "BASIC",
        "base_price_cents": 4900,
        "included_minutes": 45,
        "overage_rate_cents_per_min": 120,
        "labor_warranty_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "included_tunes_per_period": 4,
        "discount_pct": 0.10,
        "period_start": DEFAULT_PERIOD_START,
        "period_end": DEFAULT_PERIOD_END,
    }
    defaults.update(overrides)
    return defaults


def create_service_request_payload(customer_id, bike_id, zone_id, tier_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "bike_id": bike_id,
        "zone_id": zone_id,
        "tier_id": tier_id,
        "window_start": "2026-05-02T10:00:00Z",
        "window_end": "2026-05-02T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_route_day_payload(van_id, **overrides) -> dict:
    defaults = {"van_id": van_id, "date": "2026-05-02"}
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(service_request_id, planned_start, planned_end, **overrides) -> dict:
    defaults = {
        "service_request_id": service_request_id,
        "planned_start": planned_start,
        "planned_end": planned_end,
    }
    defaults.update(overrides)
    return defaults
