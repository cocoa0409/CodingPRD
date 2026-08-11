"""Payload factories — one per entity, input fields only.

Each factory returns a dict payload suitable for the corresponding POST/PUT
endpoint. Tests override specific keys via **overrides.
"""
import itertools

from .constants import DEFAULT_REGION

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


# ---------- Customers ----------

def create_customer_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Test Customer {n}",
        "email": f"customer{n}@example.com",
        "phone": f"+1415555{1000 + (n % 9000):04d}",
    }
    defaults.update(overrides)
    return defaults


# ---------- Yards ----------

def create_yard_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "address_line1": "1 Main St",
        "city": "San Francisco",
        "state_code": "CA",
        "postal_code": "94110",
        "yard_size_sqft": 1500,
        "pet_count": 1,
        "service_region_code": DEFAULT_REGION,
    }
    defaults.update(overrides)
    return defaults


# ---------- PropertyAccessProfile ----------

def create_access_profile_payload(**overrides) -> dict:
    defaults = {
        "gate_access_code": "1234",
        "gate_instructions": "side gate",
        "pet_on_premises": False,
        "pet_aggression_flag": "NONE",
    }
    defaults.update(overrides)
    return defaults


# ---------- SubscriptionPlan ----------

def create_subscription_plan_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "plan_code": f"PLAN-{n}",
        "display_name": f"Plan {n}",
        "visit_frequency": "WEEKLY",
        "applies_to_multifamily": False,
        "base_monthly_fee_cents": 10000,
        "yard_tier_thresholds": [],
        "yard_tier_surcharges_cents": [0],
        "pet_tier_thresholds": [],
        "pet_tier_surcharges_cents": [0],
    }
    defaults.update(overrides)
    return defaults


# ---------- ServiceAddon ----------

def create_service_addon_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "addon_code": f"ADDON-{n}",
        "display_name": f"Addon {n}",
        "price_cents_per_visit": 1500,
    }
    defaults.update(overrides)
    return defaults


# ---------- Subscription ----------

def create_subscription_payload(customer_id: str, yard_id: str, plan_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "yard_id": yard_id,
        "plan_id": plan_id,
    }
    defaults.update(overrides)
    return defaults


# ---------- Technician ----------

def create_technician_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Tech {n}",
        "employee_code": f"T-{n:04d}",
    }
    defaults.update(overrides)
    return defaults


# ---------- ServiceRoute ----------

def create_service_route_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "route_code": f"ROUTE-{n}",
        "service_date": "2026-05-08T00:00:00Z",
        "service_region_code": DEFAULT_REGION,
        "max_visit_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


# ---------- Visit ----------

def create_visit_payload(subscription_id: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "scheduled_date": "2026-05-08T00:00:00Z",
        "scheduled_window_start": "2026-05-08T09:00:00Z",
        "scheduled_window_end": "2026-05-08T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ---------- VacationWindow ----------

def create_vacation_window_payload(subscription_id: str, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "start_date": "2026-06-01T00:00:00Z",
        "end_date": "2026-06-05T00:00:00Z",
        "skip_reason": "VACATION",
    }
    defaults.update(overrides)
    return defaults


# ---------- Invoice ----------

def create_invoice_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "billing_period_start": "2026-05-01T00:00:00Z",
        "billing_period_end": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


# ---------- SatisfactionReport ----------

def create_satisfaction_report_payload(customer_id: str, visit_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "visit_id": visit_id,
        "rating": 3,
        "issue_category": "OTHER",
    }
    defaults.update(overrides)
    return defaults
