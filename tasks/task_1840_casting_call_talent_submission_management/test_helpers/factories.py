"""Payload factories — one per entity, input fields only (PRD sections 3, 4)."""
import itertools

from .constants import TEST_DEFAULTS as _D

_counter = itertools.count(1)


def _n(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_production_payload(**overrides) -> dict:
    defaults = {
        "title": _n("Prod"),
        "production_type": "FILM",
        "union_signatory": False,
        "shoot_city": "Los Angeles",
        "shoot_state": "CA",
        "start_date": _D["PRODUCTION_START"],
        "wrap_date": _D["PRODUCTION_WRAP"],
        "casting_office_id": "office-1",
    }
    defaults.update(overrides)
    return defaults


def create_role_payload(production_id=None, **overrides) -> dict:
    defaults = {
        "character_name": _n("Role"),
        "is_minor_role": False,
        "is_union_covered": False,
        "engagement_start": "2026-08-20T00:00:00Z",
        "engagement_end": "2026-08-22T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_breakdown_payload(role_id, **overrides) -> dict:
    defaults = {
        "role_id": role_id,
        "distribution": "OPEN_CALL",
        "submission_deadline": _D["SUBMISSION_DEADLINE"],
        "rate_weekly_cents": _D["BREAKDOWN_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    defaults = {
        "agency_name": _n("Agency"),
        "contact_email": f"agency{next(_counter)}@example.com",
        "franchise_status": "FRANCHISED",
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_guardian_payload(**overrides) -> dict:
    defaults = {
        "full_name": _n("Guardian"),
        "contact_email": f"guardian{next(_counter)}@example.com",
        "relationship": "parent",
    }
    defaults.update(overrides)
    return defaults


def create_talent_payload(**overrides) -> dict:
    defaults = {
        "full_name": _n("Talent"),
        "date_of_birth": _D["ADULT_DOB"],
        "union_status": "NON_UNION",
    }
    defaults.update(overrides)
    return defaults


def create_submission_payload(talent_id, expected_breakdown_version, agent_id=None, **overrides) -> dict:
    payload = {
        "talent_id": talent_id,
        "expected_breakdown_version": expected_breakdown_version,
    }
    if agent_id is not None:
        payload["agent_id"] = agent_id
    payload.update(overrides)
    return payload


def create_self_tape_payload(**overrides) -> dict:
    defaults = {
        "media_url": f"https://media.example.com/tape-{next(_counter)}.mp4",
        "duration_seconds": 120,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    defaults = {
        "session_start": "2026-08-04T09:00:00Z",
        "session_end": "2026-08-04T12:00:00Z",
        "capacity": _D["SESSION_CAPACITY"],
        "location": "Studio 1",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(submission_id, **overrides) -> dict:
    defaults = {
        "submission_id": submission_id,
        "slot_start": "2026-08-04T09:00:00Z",
        "slot_end": "2026-08-04T09:30:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_hold_payload(talent_id, **overrides) -> dict:
    defaults = {
        "talent_id": talent_id,
        "hold_kind": "PIN",
        "window_start": "2026-08-20T00:00:00Z",
        "window_end": "2026-08-23T00:00:00Z",
        "priority_rank": 1,
        "expires_at": "2026-08-25T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_offer_payload(**overrides) -> dict:
    defaults = {
        "weekly_rate_cents": _D["WEEKLY_RATE_CENTS"],
        "guarantee_cents": _D["GUARANTEE_CENTS"],
        "expires_at": _D["OFFER_EXPIRES"],
    }
    defaults.update(overrides)
    return defaults


def create_counter_payload(expected_offer_version, **overrides) -> dict:
    defaults = {
        "weekly_rate_cents": 1_200_000,
        "guarantee_cents": 900_000,
        "expires_at": "2026-08-21T00:00:00Z",
        "expected_offer_version": expected_offer_version,
    }
    defaults.update(overrides)
    return defaults


def create_accept_payload(**overrides) -> dict:
    defaults = {
        "engagement_start": "2026-08-20T00:00:00Z",
        "engagement_end": "2026-08-22T00:00:00Z",
        "proration_mode": "CALENDAR_SPAN",
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(talent_id, production_id, guardian_user_id, **overrides) -> dict:
    defaults = {
        "talent_id": talent_id,
        "production_id": production_id,
        "permit_number": f"PER-{next(_counter)}",
        "issued_at": "2026-08-01T00:00:00Z",
        "valid_until": "2026-12-31T00:00:00Z",
        "guardian_user_id": guardian_user_id,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(submission_id, deal_memo_id, work_permit_id=None, **overrides) -> dict:
    payload = {
        "submission_id": submission_id,
        "deal_memo_id": deal_memo_id,
    }
    if work_permit_id is not None:
        payload["work_permit_id"] = work_permit_id
    payload.update(overrides)
    return payload
