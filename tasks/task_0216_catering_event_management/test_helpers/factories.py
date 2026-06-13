"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

# Default far-out event window (non-rush). Tests override event_start/event_end as needed.
DEFAULT_EVENT_START = "2026-09-01T17:00:00Z"
DEFAULT_EVENT_END = "2026-09-01T22:00:00Z"


def create_client_payload(**overrides) -> dict:
    """Required: company_name, billing_email. Optional: tax_exempt, gratuity_policy."""
    defaults = {
        "company_name": "Acme",
        "billing_email": "a@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(**overrides) -> dict:
    """Required: name, per_head_cents, min_headcount, lead_time_hours. Optional: volume_tiers, allergen_flags."""
    defaults = {
        "name": "Gala",
        "per_head_cents": TEST_DEFAULTS["PER_HEAD_CENTS"],
        "min_headcount": TEST_DEFAULTS["MIN_HEADCOUNT"],
        "lead_time_hours": TEST_DEFAULTS["LEAD_TIME_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    """Required: name, tax_rate_bps, service_fee_bps, max_overlapping_events."""
    defaults = {
        "name": "Hall",
        "tax_rate_bps": TEST_DEFAULTS["TAX_RATE_BPS"],
        "service_fee_bps": TEST_DEFAULTS["SERVICE_FEE_BPS"],
        "max_overlapping_events": TEST_DEFAULTS["MAX_OVERLAPPING_EVENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    """Required: route_date, vehicle_capacity_legs."""
    defaults = {
        "route_date": "2026-09-01T00:00:00Z",
        "vehicle_capacity_legs": TEST_DEFAULTS["VEHICLE_CAPACITY_LEGS"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(client_id, package_id, venue_id, **overrides) -> dict:
    """Required: client_id, package_id, venue_id, booked_headcount, event_start, event_end. Optional: dietary_counts."""
    defaults = {
        "client_id": client_id,
        "package_id": package_id,
        "venue_id": venue_id,
        "booked_headcount": TEST_DEFAULTS["BOOKED_HEADCOUNT"],
        "event_start": DEFAULT_EVENT_START,
        "event_end": DEFAULT_EVENT_END,
    }
    defaults.update(overrides)
    return defaults


def create_add_on_payload(kind, unit_cents, quantity, **overrides) -> dict:
    """Required: kind, unit_cents, quantity. Optional: per_head_scaled, staff_ratio."""
    defaults = {
        "kind": kind,
        "unit_cents": unit_cents,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_delivery_leg_payload(order_id, route_id, window_start, window_end, **overrides) -> dict:
    """Required: order_id, route_id, window_start, window_end. Optional: preceding_leg_id."""
    defaults = {
        "order_id": order_id,
        "route_id": route_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_change_request_payload(order_id, requested_headcount, requested_event_start, **overrides) -> dict:
    """Required: order_id, requested_headcount, requested_event_start."""
    defaults = {
        "order_id": order_id,
        "requested_headcount": requested_headcount,
        "requested_event_start": requested_event_start,
    }
    defaults.update(overrides)
    return defaults
