"""Payload factories - one per entity, input fields only."""
from .constants import TEST_DEFAULTS

_UNSET = object()


def create_event_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Summit",
        "timezone": "UTC",
        "starts_at": "2026-09-10T09:00:00Z",
        "ends_at": "2026-09-10T18:00:00Z",
        "early_bird_ends_at": TEST_DEFAULTS["PAST_EARLY_BIRD"],
        "capacity": TEST_DEFAULTS["EVENT_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_ticket_type_payload(**overrides) -> dict:
    defaults = {
        "name": "General",
        "tier": "GENERAL",
        "price_cents": TEST_DEFAULTS["GENERAL_PRICE_CENTS"],
        "quota": TEST_DEFAULTS["TICKET_QUOTA"],
        "gating_level": "BOTH",
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(event_id, ticket_type_id, attendee_email, **overrides) -> dict:
    """Only event_id, ticket_type_id and attendee_email are required; group_code,
    group_size and waitlist_if_full are optional and are omitted unless given."""
    payload = {
        "event_id": event_id,
        "ticket_type_id": ticket_type_id,
        "attendee_email": attendee_email,
    }
    payload.update(overrides)
    return payload


def create_track_payload(**overrides) -> dict:
    defaults = {"name": "Main Stage"}
    defaults.update(overrides)
    return defaults


def create_session_payload(event_id, track_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "track_id": track_id,
        "title": "Keynote",
        "starts_at": "2026-09-10T10:00:00Z",
        "ends_at": "2026-09-10T11:00:00Z",
        "session_type": "LIVE",
        "capacity": 100,
    }
    defaults.update(overrides)
    return defaults


def create_speaker_payload(**overrides) -> dict:
    defaults = {"full_name": "Dana Reed", "email": "dana@example.com"}
    defaults.update(overrides)
    return defaults


def create_session_speaker_payload(session_id, speaker_id, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "speaker_id": speaker_id,
        "speaking_role": "HOST",
    }
    defaults.update(overrides)
    return defaults


def create_broadcast_payload(session_id, **overrides) -> dict:
    defaults = {"session_id": session_id, "ingest_region": "US_EAST"}
    defaults.update(overrides)
    return defaults


def create_sponsor_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Cloud",
        "package_tier": "GOLD",
        "contact_email": "sales@acme.example",
    }
    defaults.update(overrides)
    return defaults


def create_booth_payload(sponsor_id, **overrides) -> dict:
    defaults = {"sponsor_id": sponsor_id, "headline": "Acme Cloud Booth", "lead_quota": 2}
    defaults.update(overrides)
    return defaults


def create_match_request_payload(
    event_id, requester_registration_id, target_registration_id, **overrides
) -> dict:
    defaults = {
        "event_id": event_id,
        "requester_registration_id": requester_registration_id,
        "target_registration_id": target_registration_id,
        "window_start": "2026-09-10T12:00:00Z",
        "window_end": "2026-09-10T13:00:00Z",
    }
    defaults.update(overrides)
    return defaults
