"""Payload factories — one per entity, input fields only."""
from .constants import STANDARD_PLAN, BASIC_PLAN


def create_service_plan_payload(**overrides) -> dict:
    """Input fields for POST /service-plans. Defaults to the STANDARD rate card."""
    payload = dict(STANDARD_PLAN)
    payload.update(overrides)
    return payload


def basic_plan_payload(**overrides) -> dict:
    payload = dict(BASIC_PLAN)
    payload.update(overrides)
    return payload


def create_collection_zone_payload(**overrides) -> dict:
    defaults = {
        "name": "North 12",
        "base_pickup_weekday": 0,        # Monday
        "recycling_week_parity": "EVEN",
    }
    defaults.update(overrides)
    return defaults


def create_holiday_payload(**overrides) -> dict:
    defaults = {
        "holiday_date": "2026-12-25T00:00:00Z",
        "shift_direction": "DELAY_ONE_DAY",
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(plan_id, zone_id, **overrides) -> dict:
    defaults = {
        "plan_id": plan_id,
        "zone_id": zone_id,
        "service_address": "10 Oak St",
        "holder_name": "Pat R",
    }
    defaults.update(overrides)
    return defaults


def create_cart_payload(cart_type="TRASH", size_gallons=65, **overrides) -> dict:
    defaults = {"cart_type": cart_type, "size_gallons": size_gallons}
    defaults.update(overrides)
    return defaults


def create_extra_pickup_payload(requested_date, bulk_item_count=0, **overrides) -> dict:
    defaults = {"requested_date": requested_date, "bulk_item_count": bulk_item_count}
    defaults.update(overrides)
    return defaults


def report_event_payload(outcome, reported_at, **overrides) -> dict:
    defaults = {"outcome": outcome, "reported_at": reported_at}
    defaults.update(overrides)
    return defaults


def generate_invoice_payload(expected_account_version, period_start, period_end,
                             due_date, **overrides) -> dict:
    defaults = {
        "expected_account_version": expected_account_version,
        "period_start": period_start,
        "period_end": period_end,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def pay_invoice_payload(amount_cents, method="MANUAL", **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "method": method}
    defaults.update(overrides)
    return defaults


def transfer_out_payload(expected_account_version, new_service_address, new_zone_id,
                         **overrides) -> dict:
    defaults = {
        "expected_account_version": expected_account_version,
        "new_service_address": new_service_address,
        "new_zone_id": new_zone_id,
    }
    defaults.update(overrides)
    return defaults
