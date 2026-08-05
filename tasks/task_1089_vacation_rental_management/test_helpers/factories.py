"""Payload factories — one per entity, input fields only."""
from uuid import uuid4


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:8]}@x.com"


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Owner",
        "email": _email("owner"),
        "default_management_fee_pct": 20,
    }
    defaults.update(overrides)
    return defaults


def create_guest_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Guest",
        "email": _email("guest"),
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(vendor_type: str = "CLEANER", **overrides) -> dict:
    defaults = {
        "name": f"Test {vendor_type}",
        "vendor_type": vendor_type,
        "email": _email("vendor"),
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(owner_id: str, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "address": "1 Test St",
        "city": "Austin",
        "state_code": "TX",
        "jurisdiction_code": "TX-ATX",
        "base_nightly_rate_cents": 20000,
        "cleaning_fee_cents": 15000,
        "max_occupancy": 6,
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(property_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "permit_number": f"PN-{uuid4().hex[:6]}",
        "jurisdiction_code": "TX-ATX",
        "occupancy_tax_pct": 10,
        "issued_on": "2026-01-01T00:00:00Z",
        "expires_on": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_channel_listing_payload(property_id: str, channel: str = "AIRBNB", **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "channel": channel,
    }
    defaults.update(overrides)
    return defaults


def create_pricing_rule_payload(rule_type: str, priority: int, expected_property_version: int, **overrides) -> dict:
    defaults = {
        "rule_type": rule_type,
        "priority": priority,
        "expected_property_version": expected_property_version,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(property_id: str, guest_id: str, check_in: str, check_out: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "guest_id": guest_id,
        "check_in": check_in,
        "check_out": check_out,
    }
    defaults.update(overrides)
    return defaults


def create_turnover_task_payload(booking_id: str, property_id: str, assigned_vendor_id: str,
                                 scheduled_window_start: str, scheduled_window_end: str, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "property_id": property_id,
        "assigned_vendor_id": assigned_vendor_id,
        "scheduled_window_start": scheduled_window_start,
        "scheduled_window_end": scheduled_window_end,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(turnover_task_id: str, inspector_vendor_id: str, result: str, **overrides) -> dict:
    defaults = {
        "turnover_task_id": turnover_task_id,
        "inspector_vendor_id": inspector_vendor_id,
        "result": result,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(property_id: str, cost_cents: int, billable_to: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "description": "Test work order",
        "cost_cents": cost_cents,
        "billable_to": billable_to,
    }
    defaults.update(overrides)
    return defaults


def create_owner_statement_payload(owner_id: str, period_year: int = 2026, period_month: int = 6, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "period_year": period_year,
        "period_month": period_month,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(booking_id: str, property_id: str, rating: int = 5, author_role: str = "GUEST", **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "property_id": property_id,
        "rating": rating,
        "author_role": author_role,
    }
    defaults.update(overrides)
    return defaults
