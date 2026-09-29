"""Payload builders.

Each builder returns a valid creation payload for one entity with unique
identifying values, and accepts keyword overrides so a test can perturb exactly
the field under examination.
"""
import itertools
from typing import Any, Dict, List, Optional

from .constants import FEE_SCHEDULE_DEFAULTS

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def fee_schedule_payload(**overrides: Any) -> Dict[str, Any]:
    """The governing schedule at PRD defaults, with any knob overridden."""
    payload = dict(FEE_SCHEDULE_DEFAULTS)
    payload["schedule_code"] = f"FS-{_seq():05d}"
    payload.update(overrides)
    return payload


def alarm_company_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "legal_name": f"Sentinel Monitoring {n:04d} LLC",
        "license_number": f"AC-2507-{n:05d}",
        "contact_email": f"ops{n:04d}@sentinel2507.example",
        "contact_phone": f"+1555{n:07d}",
        "score_mode": "VOLUME_WEIGHTED",
    }
    payload.update(overrides)
    return payload


def alarm_site_payload(**overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "address_key": f"2507-{n:05d}-ROLLING-WAY",
        "street_address": f"{100 + n} Rolling Way",
        "city": "Fairview",
        "zip_code": "44011",
        "occupancy_class": "RESIDENTIAL",
        "police_beat": "B12",
    }
    payload.update(overrides)
    return payload


def site_contact_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _seq()
    payload: Dict[str, Any] = {
        "alarm_site_id": site_id,
        "full_name": f"Dana Reyes {n:04d}",
        "phone_number": f"+1555{n:07d}",
        "relationship": "KEYHOLDER",
        # PRD §3.2 fixes the roster slot at "a `contact_priority` between 1 and
        # 5", so the default must stay inside that range.
        "contact_priority": ((n - 1) % 5) + 1,
        "is_ecv_callable": True,
    }
    payload.update(overrides)
    return payload


def alarm_system_payload(site_id: str, company_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "alarm_site_id": site_id,
        "monitoring_company_id": company_id,
        "system_type": "BURGLARY",
        "zone_count": 8,
        "ecv_enabled": True,
        "verified_response_mode": "NONE",
        "installed_at": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def call_attempt(contact_id: str, attempted_at: str, outcome: str = "NO_ANSWER") -> Dict[str, Any]:
    return {"site_contact_id": contact_id, "attempted_at": attempted_at, "outcome": outcome}


def dispatch_request_payload(
    system_id: str,
    occurred_at: str,
    call_attempts: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "alarm_system_id": system_id,
        "alarm_type": "BURGLARY",
        "verification_method": "TWO_CALL_ECV",
        "call_attempts": call_attempts or [],
        "audio_video_evidence": False,
        "guard_on_scene": False,
        "occurred_at": occurred_at,
        "idempotency_key": f"idem-2507-{_seq():06d}",
    }
    payload.update(overrides)
    return payload


def false_alarm_incident_payload(dispatch_request_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "dispatch_request_id": dispatch_request_id,
        "cause_code": "OPERATOR_ERROR",
        "narrative": "Keypad error, no evidence of entry.",
    }
    payload.update(overrides)
    return payload


def determination_payload(determination: str = "COUNTED", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"determination": determination}
    payload.update(overrides)
    return payload


def hearing_docket_payload(
    officer_user_id: str, session_start: str, session_end: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hearing_officer_user_id": officer_user_id,
        "session_start": session_start,
        "session_end": session_end,
        "location": "City Hall Room 2B",
        "capacity": 4,
    }
    payload.update(overrides)
    return payload


def appeal_payload(incident_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "false_alarm_incident_id": incident_id,
        "grounds": "WRONG_CAUSE_CODE",
        "narrative": "The signal was caused by a utility power failure, not operator error.",
    }
    payload.update(overrides)
    return payload


def suspension_order_payload(
    site_id: str,
    triggering_incident_id: str,
    effective_from: str,
    effective_through: str,
    expected_alarm_site_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "alarm_site_id": site_id,
        "triggering_incident_id": triggering_incident_id,
        "basis": "EXCESSIVE_FALSE_ALARMS",
        "effective_from": effective_from,
        "effective_through": effective_through,
        "expected_alarm_site_version": expected_alarm_site_version,
    }
    payload.update(overrides)
    return payload


def payment_record_payload(
    site_id: str, amount_cents: int, tendered_on: str, expected_alarm_site_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "alarm_site_id": site_id,
        "amount_cents": amount_cents,
        "tendered_on": tendered_on,
        "method": "CHECK",
        "allocation_mode": "AUTO_WATERFALL",
        "expected_alarm_site_version": expected_alarm_site_version,
    }
    payload.update(overrides)
    return payload


def compliance_report_payload(
    company_id: str, period_start: str, period_end: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "monitoring_company_id": company_id,
        "period_start": period_start,
        "period_end": period_end,
        "reported_dispatch_count": 10,
        "reported_cancellation_count": 1,
        "ecv_attempt_count": 10,
    }
    payload.update(overrides)
    return payload
