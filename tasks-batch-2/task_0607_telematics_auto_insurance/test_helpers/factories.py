"""Payload factories — one per entity, input fields only (PRD §3)."""
import uuid

from .constants import SHARED_RATE_PLAN


def create_rate_plan_payload(**overrides) -> dict:
    """Rate plan input fields (PRD §3.1). Defaults to the shared CA UBI literals."""
    defaults = dict(SHARED_RATE_PLAN)
    defaults.update(overrides)
    return defaults


def unique_email(prefix: str = "driver") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def create_driver_payload(**overrides) -> dict:
    """Driver input fields (PRD §3.2): email, full_name, state_code."""
    defaults = {
        "email": unique_email(),
        "full_name": "Test Driver",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_privacy_consent_payload(action: str, **overrides) -> dict:
    """Privacy-consent input fields (PRD §3.2): action (+ optional reason)."""
    defaults = {"action": action, "reason": "test consent change"}
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(driver_id: str, rate_plan_id: str, scoring_days: int = 30, **overrides) -> dict:
    """Enrollment input fields (PRD §3.3): driver_id, rate_plan_id, scoring_days."""
    defaults = {
        "driver_id": driver_id,
        "rate_plan_id": rate_plan_id,
        "scoring_days": scoring_days,
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(started_at: str, ended_at: str, distance_miles: float,
                        policy_id: str = None, enrollment_id: str = None, **overrides) -> dict:
    """Trip input fields (PRD §3.5). Exactly one of policy_id / enrollment_id."""
    defaults = {
        "started_at": started_at,
        "ended_at": ended_at,
        "distance_miles": distance_miles,
    }
    if policy_id is not None:
        defaults["policy_id"] = policy_id
    if enrollment_id is not None:
        defaults["enrollment_id"] = enrollment_id
    defaults.update(overrides)
    return defaults


def create_trip_event_payload(event_type: str, severity: int, occurred_at: str, **overrides) -> dict:
    """Trip-event input fields (PRD §3.5): event_type, severity, occurred_at."""
    defaults = {
        "event_type": event_type,
        "severity": severity,
        "occurred_at": occurred_at,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(enrollment_id: str, **overrides) -> dict:
    """Quote input fields (PRD §3.4): enrollment_id."""
    defaults = {"enrollment_id": enrollment_id}
    defaults.update(overrides)
    return defaults


def create_policy_payload(quote_id: str, **overrides) -> dict:
    """Policy input fields (PRD §3.4): quote_id."""
    defaults = {"quote_id": quote_id}
    defaults.update(overrides)
    return defaults


def create_statement_payload(policy_id: str, expected_policy_version: int, **overrides) -> dict:
    """Statement input fields (PRD §3.6): policy_id, expected_policy_version."""
    defaults = {
        "policy_id": policy_id,
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults


def create_renewal_payload(policy_id: str, expected_policy_version: int, **overrides) -> dict:
    """Renewal input fields (PRD §3.9): policy_id, expected_policy_version."""
    defaults = {
        "policy_id": policy_id,
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id: str, reported_severity: int, **overrides) -> dict:
    """Manual claim input fields (PRD §3.8): policy_id, reported_severity (+ optional reason)."""
    defaults = {
        "policy_id": policy_id,
        "reported_severity": reported_severity,
    }
    defaults.update(overrides)
    return defaults


def triage_claim_payload(**overrides) -> dict:
    """Claim-triage input fields (PRD §3.8): optional reserve_severity_override."""
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def reopen_claim_payload(expected_claim_version: int, **overrides) -> dict:
    """Claim-reopen input fields (PRD §3.8): expected_claim_version."""
    defaults = {"expected_claim_version": expected_claim_version}
    defaults.update(overrides)
    return defaults
