"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here. Server-computed
and system fields (severity_score, priority, status, boarding_fee, etc.) are
never sent.
"""

# Sensible non-conflicting default timestamps (aligned to the logical-clock
# startup default of 2026-03-01T00:00:00Z).
DEFAULT_SHIFT_START = "2026-03-01T00:00:00Z"
DEFAULT_SHIFT_END = "2026-03-02T00:00:00Z"


def create_complaint_payload(**overrides) -> dict:
    payload = {
        "reporter_name": "Test Reporter",
        "reporter_phone": "555-0000",
        "zone": "NORTH",
        "animal_type": "DOG",
        "complaint_type": "STRAY",
    }
    payload.update(overrides)
    return payload


def create_officer_payload(**overrides) -> dict:
    payload = {
        "name": "Test Officer",
        "badge_number": "BADGE-1",
        "territory_zone": "NORTH",
        "shift_start_at": DEFAULT_SHIFT_START,
        "shift_end_at": DEFAULT_SHIFT_END,
    }
    payload.update(overrides)
    return payload


def create_kennel_payload(**overrides) -> dict:
    payload = {
        "code": "K-TEST",
        "facility_zone": "NORTH",
    }
    payload.update(overrides)
    return payload


def create_dispatch_payload(complaint_id, officer_id, **overrides) -> dict:
    payload = {
        "complaint_id": complaint_id,
        "officer_id": officer_id,
        "scheduled_start_at": "2026-03-01T09:00:00Z",
        "scheduled_end_at": "2026-03-01T10:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_case_payload(complaint_id, assigned_officer_id, case_type="BITE", **overrides) -> dict:
    payload = {
        "complaint_id": complaint_id,
        "assigned_officer_id": assigned_officer_id,
        "case_type": case_type,
    }
    payload.update(overrides)
    return payload


def create_note_payload(**overrides) -> dict:
    payload = {
        "note_type": "OBSERVATION",
        "body": "Test note body.",
    }
    payload.update(overrides)
    return payload


def create_quarantine_hold_payload(case_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "hold_type": "HOME_QUARANTINE",
        "start_at": "2026-03-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_impound_payload(case_id, kennel_id, expected_case_version, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "kennel_id": kennel_id,
        "impounded_at": "2026-03-01T00:00:00Z",
        "hold_until": "2026-03-05T00:00:00Z",
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def create_citation_payload(case_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "violation_code": "UNLICENSED",
        "issued_to_name": "Test Owner",
        "issued_to_ref": "OWNER-TEST",
    }
    payload.update(overrides)
    return payload


def create_rabies_report_payload(case_id, quarantine_hold_id, **overrides) -> dict:
    payload = {
        "case_id": case_id,
        "quarantine_hold_id": quarantine_hold_id,
        "victim_name": "Test Victim",
        "exposure_date": "2026-03-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload
