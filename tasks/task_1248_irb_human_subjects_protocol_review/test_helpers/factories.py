"""Payload factories — one per entity, client-supplied (input) fields only."""
import itertools

from .constants import DEFAULT_CLOCK_ISO

_email_counter = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    """Emails must be unique across investigators / members (PRD §3.1)."""
    return f"{prefix}-{next(_email_counter)}@univ.edu"


def create_investigator_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Dr Test Investigator",
        "email": unique_email("inv"),
        "department": "Medicine",
        "training_expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "email": unique_email("member"),
        "member_category": "SCIENTIST",
    }
    defaults.update(overrides)
    return defaults


def create_protocol_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Protocol",
        "claimed_review_level": "EXPEDITED",
        "risk_level": "MINIMAL",
    }
    defaults.update(overrides)
    return defaults


def create_consent_document_payload(**overrides) -> dict:
    defaults = {
        "file_ref": "s3://consent/test-v1.pdf",
    }
    defaults.update(overrides)
    return defaults


def create_review_assignment_payload(**overrides) -> dict:
    return dict(overrides)


def create_conflict_declaration_payload(**overrides) -> dict:
    defaults = {
        "declaration_type": "FINANCIAL",
        "detail": "test conflict detail",
    }
    defaults.update(overrides)
    return defaults


def create_board_meeting_payload(**overrides) -> dict:
    defaults = {
        "room_id": "R-TEST",
        "scheduled_at": "2026-06-01T10:00:00Z",
        "duration_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_agenda_item_payload(protocol_id, expected_meeting_version, **overrides) -> dict:
    defaults = {
        "protocol_id": protocol_id,
        "expected_meeting_version": expected_meeting_version,
    }
    defaults.update(overrides)
    return defaults


def create_modification_payload(expected_protocol_version, **overrides) -> dict:
    defaults = {
        "scope": "MINOR",
        "description": "test amendment",
        "expected_protocol_version": expected_protocol_version,
    }
    defaults.update(overrides)
    return defaults


def create_adverse_event_payload(**overrides) -> dict:
    defaults = {
        "event_type": "SERIOUS_ADVERSE_EVENT",
        "occurred_at": DEFAULT_CLOCK_ISO,
        "description": "test adverse event",
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "reason": "test manual case",
    }
    defaults.update(overrides)
    return defaults


def create_reliance_agreement_payload(protocol_id, **overrides) -> dict:
    defaults = {
        "protocol_id": protocol_id,
        "ceding_institution_code": "INST_A",
        "reviewing_institution_code": "UNIV",
        "effective_start_date": "2026-06-01T00:00:00Z",
        "effective_end_date": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
