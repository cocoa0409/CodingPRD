"""Payload factories — one per entity, input fields only.

Default dates line up with the logical-clock startup default of 2026-05-01:
event on 2026-06-15, comfortably more than 14 days out and inside every
supporting document's validity window.
"""

# Canonical event window used by the standard fixtures.
EVENT_START = "2026-06-15T18:00:00Z"
EVENT_END = "2026-06-15T23:00:00Z"


def create_venue_payload(**overrides) -> dict:
    payload = {
        "name": "Riverside Hall",
        "address": "1 River Rd",
        "occupancy_limit": 200,
        "indoor": True,
    }
    payload.update(overrides)
    return payload


def create_inspector_payload(**overrides) -> dict:
    payload = {
        "name": "Ivy Fire",
        "badge_number": "B-1",
        "agency": "FIRE",
    }
    payload.update(overrides)
    return payload


def create_application_payload(venue_id, **overrides) -> dict:
    payload = {
        "venue_id": venue_id,
        "organizer_name": "Rotary Club",
        "event_name": "Summer Gala",
        "event_start": EVENT_START,
        "event_end": EVENT_END,
        "alcohol_service_hours": 5,
        "expected_attendance": 151,
        "requested_sales_limit_cents": 250050,
    }
    payload.update(overrides)
    return payload


def create_server_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "full_name": "Sam Pour",
        "cert_number": "C-1",
        "training_provider": "TIPS",
        "cert_issued_date": "2025-01-01T00:00:00Z",
        "cert_expiry_date": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_insurance_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "insurer_name": "Acme Ins",
        "coverage_cents": 200000000,
        "effective_date": "2026-06-01T00:00:00Z",
        "expiry_date": "2026-07-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_security_plan_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "planned_guard_count": 3,
        "plan_summary": "Perimeter + ID",
        "has_medical_staff": False,
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(application_id, inspector_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "inspector_id": inspector_id,
        "scheduled_start": "2026-06-14T10:00:00Z",
        "scheduled_end": "2026-06-14T11:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_violation_payload(inspection_id, **overrides) -> dict:
    payload = {
        "inspection_id": inspection_id,
        "severity": "CRITICAL",
        "description": "Serving after hours",
    }
    payload.update(overrides)
    return payload


def create_report_payload(application_id, **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "actual_attendance": 151,
        "gross_sales_cents": 250050,
        "incident_count": 0,
    }
    payload.update(overrides)
    return payload


def create_payment_payload(amount_cents, expected_application_version, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "expected_application_version": expected_application_version,
    }
    payload.update(overrides)
    return payload


def decide_payload(decision, expected_application_version, conditions=None, **overrides) -> dict:
    payload = {
        "decision": decision,
        "expected_application_version": expected_application_version,
    }
    if conditions is not None:
        payload["conditions"] = conditions
    payload.update(overrides)
    return payload
