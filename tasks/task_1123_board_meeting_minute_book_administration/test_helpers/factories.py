"""Payload factories for the Board Governance API — input fields only."""

DEFAULT_CORPORATION_NAME = "Corp"
DEFAULT_INCORPORATION_STATE = "DE"
DEFAULT_TERM_START = "2026-01-01T00:00:00Z"
DEFAULT_TERM_END = "2029-01-01T00:00:00Z"
DEFAULT_SCHEDULED_START = "2026-06-20T10:00:00Z"
DEFAULT_DURATION_MINUTES = 60
DEFAULT_LOCATION = "Boardroom"
DEFAULT_CHARTER_TEXT = "charter"
DEFAULT_COMMITTEE_QUORUM = 1
DEFAULT_RELATED_PARTY = "Acme"
DEFAULT_DISCLOSURE_FROM = "2026-01-01T00:00:00Z"
DEFAULT_DISCLOSURE_TO = "2026-12-31T00:00:00Z"


def create_corporation_payload(**overrides) -> dict:
    defaults = {"name": DEFAULT_CORPORATION_NAME, "incorporation_state": DEFAULT_INCORPORATION_STATE}
    defaults.update(overrides)
    return defaults


def create_bylaws_payload(corporation_id: str, **overrides) -> dict:
    defaults = {
        "corporation_id": corporation_id,
        "notice_days_regular": 10,
        "notice_days_special": 3,
        "package_lead_days": 5,
        "quorum_percent": 60,
        "quorum_fixed_count": 1,
        "consent_window_days": 10,
        "consent_unanimity_required": True,
        "minute_retention_years": 5,
        "rotation_max_years": 6,
        "board_seat_count": 15,
    }
    defaults.update(overrides)
    return defaults


def create_director_payload(corporation_id: str, full_name: str, email: str, **overrides) -> dict:
    defaults = {
        "corporation_id": corporation_id,
        "full_name": full_name,
        "email": email,
        "term_start": DEFAULT_TERM_START,
        "term_end": DEFAULT_TERM_END,
    }
    defaults.update(overrides)
    return defaults


def create_committee_payload(corporation_id: str, name: str, committee_type: str, **overrides) -> dict:
    defaults = {
        "corporation_id": corporation_id,
        "name": name,
        "committee_type": committee_type,
        "charter_text": DEFAULT_CHARTER_TEXT,
        "quorum_fixed_count": DEFAULT_COMMITTEE_QUORUM,
    }
    defaults.update(overrides)
    return defaults


def create_committee_membership_payload(
    committee_id: str, director_id: str, committee_role: str = "MEMBER", **overrides
) -> dict:
    defaults = {
        "committee_id": committee_id,
        "director_id": director_id,
        "committee_role": committee_role,
        "term_start": "2026-02-01T00:00:00Z",
        "term_end": "2028-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_meeting_payload(corporation_id: str, chair_director_id: str, **overrides) -> dict:
    defaults = {
        "corporation_id": corporation_id,
        "meeting_type": "REGULAR",
        "scheduled_start": DEFAULT_SCHEDULED_START,
        "duration_minutes": DEFAULT_DURATION_MINUTES,
        "location_or_medium": DEFAULT_LOCATION,
        "chair_director_id": chair_director_id,
    }
    defaults.update(overrides)
    return defaults


def create_attendance_payload(meeting_id: str, director_id: str, attendance_mode: str, **overrides) -> dict:
    defaults = {
        "meeting_id": meeting_id,
        "director_id": director_id,
        "attendance_mode": attendance_mode,
    }
    defaults.update(overrides)
    return defaults


def create_agenda_item_payload(meeting_id: str, title: str, order_index: int, proposed_by: str, **overrides) -> dict:
    defaults = {
        "meeting_id": meeting_id,
        "title": title,
        "order_index": order_index,
        "proposed_by_director_id": proposed_by,
    }
    defaults.update(overrides)
    return defaults


def create_board_package_payload(meeting_id: str, **overrides) -> dict:
    defaults = {"meeting_id": meeting_id}
    defaults.update(overrides)
    return defaults


def create_package_document_payload(package_id: str, title: str, content_ref: str, tier: str, **overrides) -> dict:
    defaults = {
        "package_id": package_id,
        "title": title,
        "content_ref": content_ref,
        "confidentiality_tier": tier,
    }
    defaults.update(overrides)
    return defaults


def create_resolution_payload(corporation_id: str, origin: str, resolution_type: str, title: str, text: str, **overrides) -> dict:
    defaults = {
        "corporation_id": corporation_id,
        "origin": origin,
        "resolution_type": resolution_type,
        "title": title,
        "text": text,
    }
    defaults.update(overrides)
    return defaults


def create_vote_record_payload(resolution_id: str, channel: str, vote: str, **overrides) -> dict:
    defaults = {"resolution_id": resolution_id, "channel": channel, "vote": vote}
    defaults.update(overrides)
    return defaults


def create_conflict_disclosure_payload(
    director_id: str, corporation_id: str, related_party: str, **overrides
) -> dict:
    defaults = {
        "director_id": director_id,
        "corporation_id": corporation_id,
        "related_party": related_party,
        "effective_from": DEFAULT_DISCLOSURE_FROM,
        "effective_to": DEFAULT_DISCLOSURE_TO,
    }
    defaults.update(overrides)
    return defaults


def create_audit_request_payload(corporation_id: str, requested_by_label: str, scope_start: str, scope_end: str, **overrides) -> dict:
    defaults = {
        "corporation_id": corporation_id,
        "requested_by_label": requested_by_label,
        "scope_start": scope_start,
        "scope_end": scope_end,
    }
    defaults.update(overrides)
    return defaults
