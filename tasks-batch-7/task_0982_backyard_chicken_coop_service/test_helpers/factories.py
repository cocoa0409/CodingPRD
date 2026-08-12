"""Payload factories — one per creatable resource, client-supplied fields only.

Email uniqueness: emails must be unique across households (PRD §3.1), so the
default email embeds a per-process counter suffix.
"""
import itertools

_email_counter = itertools.count(1)


def _next_email(prefix: str = "household") -> str:
    return f"{prefix}-{next(_email_counter)}@test.example"


def create_household_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Household",
        "email": _next_email(),
        "address": "1 Hen Lane",
        "zone_code": "URBAN",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_code": f"PLAN-{next(_email_counter)}",
        "monthly_fee_cents": 2900,
        "included_cleanings_per_period": 0,
        "included_health_checks_per_period": 0,
        "supply_discount_pct": 0,
        "sitting_discount_pct": 0,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": f"SKU-{next(_email_counter)}",
        "name": "Layer Feed",
        "category": "FEED",
        "unit_price_cents": 333,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_seasonal_window_payload(**overrides) -> dict:
    defaults = {
        "window_code": f"WIN-{next(_email_counter)}",
        "zone_code": "RURAL",
        "start_md": "11-15",
        "end_md": "02-15",
        "visit_surcharge_pct": 0.25,
        "sitting_surcharge_pct": 0.20,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(household_id: str, plan_id: str, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "plan_id": plan_id,
        "current_period_start": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_coop_site_payload(household_id: str, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "site_label": "backyard north",
        "coop_capacity_hens": 6,
    }
    defaults.update(overrides)
    return defaults


def create_service_visit_payload(household_id: str, coop_site_id: str, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "coop_site_id": coop_site_id,
        "visit_type": "SETUP_INSTALL",
        "scheduled_start": "2026-06-10T09:00:00Z",
        "scheduled_end": "2026-06-10T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def assign_visit_payload(technician_id: str, **overrides) -> dict:
    defaults = {"technician_id": technician_id}
    defaults.update(overrides)
    return defaults


def complete_visit_payload(**overrides) -> dict:
    defaults = {
        "observed_flock_size": 6,
        "actual_duration_minutes": 180,
    }
    defaults.update(overrides)
    return defaults


def create_sitting_engagement_payload(household_id: str, coop_site_id: str, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "coop_site_id": coop_site_id,
        "start_date": "2026-07-10T00:00:00Z",
        "end_date": "2026-07-11T00:00:00Z",
        "daily_window_start": "08:00",
    }
    defaults.update(overrides)
    return defaults


def create_sitting_route_payload(**overrides) -> dict:
    defaults = {
        "technician_id": "tech-9",
        "route_date": "2026-07-10T00:00:00Z",
        "zone_code": "URBAN",
        "max_stops": 4,
    }
    defaults.update(overrides)
    return defaults


def add_route_stop_payload(engagement_id: str, expected_route_version: int, **overrides) -> dict:
    defaults = {
        "engagement_id": engagement_id,
        "planned_start": "2026-08-01T12:00:00Z",
        "planned_end": "2026-08-01T13:00:00Z",
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults


def create_supply_order_payload(household_id: str, **overrides) -> dict:
    defaults = {"household_id": household_id}
    defaults.update(overrides)
    return defaults


def add_order_line_payload(product_sku: str, quantity: int, **overrides) -> dict:
    defaults = {"product_sku": product_sku, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_invoice_payload(household_id: str, **overrides) -> dict:
    defaults = {
        "household_id": household_id,
        "period_start": "2026-05-01T00:00:00Z",
        "period_end": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def wallet_adjustment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "reason": "adjustment"}
    defaults.update(overrides)
    return defaults


def plan_change_payload(new_plan_id: str, expected_subscription_version: int, **overrides) -> dict:
    defaults = {
        "new_plan_id": new_plan_id,
        "expected_subscription_version": expected_subscription_version,
    }
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(adjustment_amount_cents: int, **overrides) -> dict:
    defaults = {"adjustment_amount_cents": adjustment_amount_cents, "reason": "resolution"}
    defaults.update(overrides)
    return defaults


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
