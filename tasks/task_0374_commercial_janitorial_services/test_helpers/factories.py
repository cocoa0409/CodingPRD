"""Payload factories — one per entity, input fields only."""
from .constants import DEFAULT_CONTACT_USER_ID

DEFAULTS = {
    "ACCOUNT_NAME": "Acme",
    "BILLING_EMAIL": "ap@acme.test",
    "SITE_LABEL": "HQ",
    "CLEANABLE_SQFT": 8000,
    "FLOOR_TYPE": "CARPET",
    "CREW_NAME": "Pat Crew",
    "MONTHLY_BASE_CENTS": 300000,
    "HOURLY_RATE_CENTS": 6000,
    "QUOTED_HOURS": 2,
    "SERVICE_DATE": "2026-06-16",
    "PERIOD_MONTH": "2026-06",
}


def create_account_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["ACCOUNT_NAME"],
        "billing_email": DEFAULTS["BILLING_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "contact_user_id": DEFAULT_CONTACT_USER_ID,
        "label": DEFAULTS["SITE_LABEL"],
        "cleanable_sqft": DEFAULTS["CLEANABLE_SQFT"],
        "floor_type": DEFAULTS["FLOOR_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "monthly_base_cents": DEFAULTS["MONTHLY_BASE_CENTS"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["CREW_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_schedule_payload(site_id, assigned_crew_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "weekday": 0,
        "window_start_min": 600,
        "window_end_min": 660,
        "assigned_crew_id": assigned_crew_id,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(site_id, crew_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "crew_id": crew_id,
        "service_date": DEFAULTS["SERVICE_DATE"],
        "planned_start_min": 540,
        "planned_end_min": 600,
        "visit_kind": "ROUTINE",
    }
    defaults.update(overrides)
    return defaults


def create_time_entry_payload(visit_id, crew_id, clock_in_min, **overrides) -> dict:
    defaults = {
        "visit_id": visit_id,
        "crew_id": crew_id,
        "clock_in_min": clock_in_min,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(visit_id, score, **overrides) -> dict:
    defaults = {
        "visit_id": visit_id,
        "score": score,
    }
    defaults.update(overrides)
    return defaults


def create_periodic_job_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "job_type": "STRIP_WAX",
        "quoted_hours": DEFAULTS["QUOTED_HOURS"],
        "requested_date": "2026-06-12",
    }
    defaults.update(overrides)
    return defaults


def dispatch_periodic_job_payload(crew_id, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "service_date": "2026-06-12",
        "planned_start_min": 480,
        "planned_end_min": 600,
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "severity": "MINOR",
        "description": "Issue reported",
    }
    defaults.update(overrides)
    return defaults


def schedule_callback_payload(crew_id, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "service_date": "2026-06-18",
        "planned_start_min": 600,
        "planned_end_min": 660,
    }
    defaults.update(overrides)
    return defaults


def create_billing_period_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "period_month": DEFAULTS["PERIOD_MONTH"],
    }
    defaults.update(overrides)
    return defaults


def create_supply_order_payload(site_id, **overrides) -> dict:
    defaults = {
        "site_id": site_id,
        "sku": "PAPER_TOWEL",
        "quantity": 5,
    }
    defaults.update(overrides)
    return defaults
