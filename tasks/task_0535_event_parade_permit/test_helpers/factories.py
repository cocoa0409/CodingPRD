"""Payload factories — one per entity, input fields only.

Timestamps are chosen to sit within the default logical clock window
(2026-05-01T00:00:00Z at boot) or later; tests that depend on the clock
set it explicitly.
"""

DEFAULTS = {
    "APPLICANT_ORG": "Test Org",
    "CONTACT_EMAIL": "test@example.com",
    "VENUE_NAME": "Test Venue",
    "VENUE_TYPE": "PARK",
    "MAX_CAPACITY": 6000,
    "CORRIDOR_NAME": "Test Corridor",
    "EVENT_KIND": "FESTIVAL",
    "EXPECTED_ATTENDANCE": 3000,
    "OCCUPY_START": "2026-06-01T10:00:00Z",
    "OCCUPY_END": "2026-06-01T14:00:00Z",
    "SEGMENT_LABEL": "Main St 1-4",
    "CLOSURE_START": "2026-06-01T09:00:00Z",
    "CLOSURE_END": "2026-06-01T15:00:00Z",
    "CARRIER": "Acme Ins",
    "COVERAGE_AMOUNT": 1_200_000,
    "COI_EXPIRES_AT": "2027-01-01T00:00:00Z",
}


def create_applicant_payload(**overrides) -> dict:
    payload = {
        "org_name": DEFAULTS["APPLICANT_ORG"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_venue_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["VENUE_NAME"],
        "venue_type": DEFAULTS["VENUE_TYPE"],
        "max_capacity": DEFAULTS["MAX_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def create_closure_schedule_payload(**overrides) -> dict:
    payload = {"corridor_name": DEFAULTS["CORRIDOR_NAME"]}
    payload.update(overrides)
    return payload


def create_application_payload(venue_id, **overrides) -> dict:
    payload = {
        "applicant_org": DEFAULTS["APPLICANT_ORG"],
        "venue_id": venue_id,
        "event_kind": DEFAULTS["EVENT_KIND"],
        "expected_attendance": DEFAULTS["EXPECTED_ATTENDANCE"],
        "occupy_start": DEFAULTS["OCCUPY_START"],
        "occupy_end": DEFAULTS["OCCUPY_END"],
    }
    payload.update(overrides)
    return payload


def create_route_segment_payload(closure_schedule_id, **overrides) -> dict:
    payload = {
        "closure_schedule_id": closure_schedule_id,
        "segment_label": DEFAULTS["SEGMENT_LABEL"],
        "closure_start": DEFAULTS["CLOSURE_START"],
        "closure_end": DEFAULTS["CLOSURE_END"],
    }
    payload.update(overrides)
    return payload


def create_coi_payload(**overrides) -> dict:
    payload = {
        "carrier": DEFAULTS["CARRIER"],
        "coverage_amount": DEFAULTS["COVERAGE_AMOUNT"],
        "expires_at": DEFAULTS["COI_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


def create_deposit_payload(amount, **overrides) -> dict:
    payload = {"amount": amount}
    payload.update(overrides)
    return payload


def approve_review_payload(**overrides) -> dict:
    """Staffing plan supplied on approval. Defaults reproduce the canonical
    MEDIUM staffing scenario (POLICE 4x8x50, etc.) unless overridden."""
    payload = {}
    payload.update(overrides)
    return payload


def open_debrief_payload(actual_attendance, **overrides) -> dict:
    payload = {"actual_attendance": actual_attendance}
    payload.update(overrides)
    return payload
