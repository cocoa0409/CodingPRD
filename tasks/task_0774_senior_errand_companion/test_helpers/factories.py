"""Payload factories — one per entity, input fields only.

Each factory returns a payload dict with sensible defaults, overridable via
**overrides. Only fields the client is expected to supply are included.
"""
from .constants import (
    BOND_EFFECTIVE_DEFAULT,
    BOND_EXPIRY_DEFAULT,
    FAR_FUTURE,
)


def create_client_payload(**overrides) -> dict:
    """Required: name, home_zip, hourly_rate_cents, mileage_rate_cents_per_mile.
    Optional (server defaults apply if omitted): timezone, ot_threshold_hours,
    ot_multiplier, min_visit_minutes."""
    defaults = {
        "name": "Test Client",
        "home_zip": "90001",
        "hourly_rate_cents": 3000,
        "mileage_rate_cents_per_mile": 75,
    }
    defaults.update(overrides)
    return defaults


def create_family_contact_payload(**overrides) -> dict:
    defaults = {
        "name": "Jane Doe",
        "email": "jane@example.com",
        "relationship": "daughter",
    }
    defaults.update(overrides)
    return defaults


def create_caregiver_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Caregiver",
        "home_zip": "90001",
    }
    defaults.update(overrides)
    return defaults


def background_check_decision_payload(outcome="CLEARED", expires_at=FAR_FUTURE, **overrides) -> dict:
    """outcome CLEARED carries expires_at; FLAGGED does not."""
    payload = {"outcome": outcome}
    if outcome == "CLEARED":
        payload["expires_at"] = expires_at
    payload.update(overrides)
    return payload


def create_bond_payload(**overrides) -> dict:
    defaults = {
        "coverage_cents": 5_000_000,
        "effective_date": BOND_EFFECTIVE_DEFAULT,
        "expiry_date": BOND_EXPIRY_DEFAULT,
    }
    defaults.update(overrides)
    return defaults


def create_schedule_payload(**overrides) -> dict:
    defaults = {
        "task_type": "COMPANION",
        "frequency": "WEEKLY",
        "day_of_week": "THU",
        "start_time": "09:00",
        "duration_minutes": 180,
        "start_date": "2026-03-01T00:00:00Z",
        "end_date": "2026-03-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_ltc_policy_payload(**overrides) -> dict:
    """benefit_type INDEMNITY carries daily_benefit_cents; REIMBURSEMENT carries
    reimbursement_rate + daily_cap_cents. Caller supplies the relevant terms."""
    defaults = {
        "payer_name": "Test Payer",
        "benefit_type": "INDEMNITY",
        "lifetime_max_cents": 1_000_000,
        "daily_benefit_cents": 10_000,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(client_id, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "task_type": "COMPANION",
        "scheduled_start": "2026-03-05T09:00:00Z",
        "scheduled_end": "2026-03-05T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(caregiver_id, expected_visit_version, **overrides) -> dict:
    defaults = {
        "caregiver_id": caregiver_id,
        "expected_visit_version": expected_visit_version,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(**overrides) -> dict:
    defaults = {
        "addon_type": "MEAL_PREP",
        "fee_cents": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_wellness_escalation_payload(**overrides) -> dict:
    defaults = {
        "severity": "HIGH",
        "reason": "client fall risk",
    }
    defaults.update(overrides)
    return defaults


def create_log_payload(**overrides) -> dict:
    defaults = {
        "entry_type": "NOTE",
        "note": "arrived on time",
    }
    defaults.update(overrides)
    return defaults
