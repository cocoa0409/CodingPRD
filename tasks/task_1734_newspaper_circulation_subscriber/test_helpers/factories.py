"""Payload factories — one per entity, input fields only (PRD §4)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_subscription_plan_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Plan"),
        "plan_type": "PRINT",
        "issues_per_week": 7,
        "base_weekly_rate_cents": TEST_DEFAULTS["BASE_WEEKLY_RATE_CENTS"],
        "proration_method": "PER_DAY",
        "min_weekly_rate_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_subscriber_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "display_name": f"Subscriber-{n}",
        "email": f"sub{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(subscriber_id: str, plan_id: str, **overrides) -> dict:
    defaults = {
        "subscriber_id": subscriber_id,
        "plan_id": plan_id,
        "start_date": "2026-08-03",
    }
    defaults.update(overrides)
    return defaults


def create_vacation_hold_payload(**overrides) -> dict:
    defaults = {
        "start_date": "2026-08-10",
        "end_date": "2026-08-14",
        "resolution": "CREDIT",
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(subscription_id: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "service_date": "2026-08-03",
        "complaint_type": "MISSED",
    }
    defaults.update(overrides)
    return defaults


def create_credit_memo_payload(subscriber_id: str, **overrides) -> dict:
    defaults = {
        "subscriber_id": subscriber_id,
        "amount_cents": 300,
        "reason": "goodwill",
    }
    defaults.update(overrides)
    return defaults


def create_save_offer_payload(expected_subscription_version: int, **overrides) -> dict:
    defaults = {
        "discount_pct": 0.3,
        "duration_weeks": 8,
        "expected_subscription_version": expected_subscription_version,
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "route_code": _uniq("R"),
        "max_stops": TEST_DEFAULTS["MAX_STOPS"],
    }
    defaults.update(overrides)
    return defaults


def create_carrier_payload(**overrides) -> dict:
    defaults = {
        "display_name": _uniq("Carrier"),
        "compensation_model": "PER_COPY_GROSS",
        "per_copy_rate_cents": TEST_DEFAULTS["PER_COPY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_route_assignment_payload(subscription_id: str, route_id: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "route_id": route_id,
        "start_date": "2026-08-03",
    }
    defaults.update(overrides)
    return defaults


def create_rack_location_payload(**overrides) -> dict:
    defaults = {
        "location_name": _uniq("Rack"),
        "address": "1 Rt 9",
        "price_per_copy_cents": TEST_DEFAULTS["PRICE_PER_COPY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rack_sales_report_payload(rack_location_id: str, **overrides) -> dict:
    defaults = {
        "rack_location_id": rack_location_id,
        "week_start_date": "2026-08-03",
        "copies_delivered": 50,
        "copies_returned": 8,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(subscriber_id: str, **overrides) -> dict:
    defaults = {
        "subscriber_id": subscriber_id,
        "amount_cents": 600,
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def create_audit_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-08-01",
        "period_end": "2026-08-31",
    }
    defaults.update(overrides)
    return defaults
