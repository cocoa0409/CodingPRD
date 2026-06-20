"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import HIGH_ANNUAL_USAGE

# Monotonic counters so independent factory calls in the same test never collide
# on the unique fields (utility_account_no, period_month).
_acct_counter = {"n": 0}


def _next_account_no() -> str:
    _acct_counter["n"] += 1
    return f"ACC-{_acct_counter['n']:06d}"


def create_project_payload(**overrides) -> dict:
    """POST /projects input. carve_out_pct and program_fee_rate are optional (have defaults)."""
    defaults = {
        "name": "Test Garden",
        "state_code": "NY",
        "nameplate_capacity_kw": 100,
        "credit_rate_cents_per_kwh": 10,
    }
    defaults.update(overrides)
    return defaults


def create_subscriber_payload(**overrides) -> dict:
    """POST /subscribers input. is_low_income optional (defaults false)."""
    defaults = {
        "full_name": "Test Subscriber",
        "utility_account_no": _next_account_no(),
        "state_code": "NY",
        "annual_usage_kwh": HIGH_ANNUAL_USAGE,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(project_id, subscriber_id, **overrides) -> dict:
    """POST /enrollments input."""
    defaults = {
        "project_id": project_id,
        "subscriber_id": subscriber_id,
        "requested_share_kw": 5.0,
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(project_id, subscriber_id, **overrides) -> dict:
    """POST /waitlist-entries input."""
    defaults = {
        "project_id": project_id,
        "subscriber_id": subscriber_id,
        "requested_share_kw": 5.0,
    }
    defaults.update(overrides)
    return defaults


def create_period_payload(project_id, period_month, **overrides) -> dict:
    """POST /periods input."""
    defaults = {
        "project_id": project_id,
        "period_month": period_month,
        "forecast_production_kwh": 1000,
    }
    defaults.update(overrides)
    return defaults


def meter_payload(metered_production_kwh, expected_period_version, **overrides) -> dict:
    """POST /periods/{id}/meter input."""
    defaults = {
        "metered_production_kwh": metered_production_kwh,
        "expected_period_version": expected_period_version,
    }
    defaults.update(overrides)
    return defaults


def reconcile_payload(expected_period_version, **overrides) -> dict:
    """POST /periods/{id}/reconcile input."""
    defaults = {"expected_period_version": expected_period_version}
    defaults.update(overrides)
    return defaults


def transfer_payload(target_subscriber_id, expected_project_version, **overrides) -> dict:
    """POST /subscriptions/{id}/transfer input."""
    defaults = {
        "target_subscriber_id": target_subscriber_id,
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def reject_payload(rejection_reason="needs documents", **overrides) -> dict:
    """POST /enrollments/{id}/reject input."""
    defaults = {"rejection_reason": rejection_reason}
    defaults.update(overrides)
    return defaults


def carve_out_adjustment_payload(new_carve_out_pct, reason="adjust", **overrides) -> dict:
    """POST /projects/{id}/carve-out-adjustments input."""
    defaults = {"new_carve_out_pct": new_carve_out_pct, "reason": reason}
    defaults.update(overrides)
    return defaults


def retire_payload(retirement_beneficiary="City of Albany", **overrides) -> dict:
    """POST /rec-batches/{id}/retire input."""
    defaults = {"retirement_beneficiary": retirement_beneficiary}
    defaults.update(overrides)
    return defaults


def transfer_rec_payload(transfer_counterparty="Counterparty Co", **overrides) -> dict:
    """POST /rec-batches/{id}/transfer input."""
    defaults = {"transfer_counterparty": transfer_counterparty}
    defaults.update(overrides)
    return defaults
