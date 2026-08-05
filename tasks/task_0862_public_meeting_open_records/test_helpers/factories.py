"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_public_body_payload(**overrides) -> dict:
    d = {
        "name": "City Council",
        "jurisdiction_state": "TX",
        "seat_count": 5,
        "quorum_size": 2,
    }
    d.update(overrides)
    return d


def create_requester_payload(**overrides) -> dict:
    d = {"full_name": "Rey Q", "email": "rey@example.com"}
    d.update(overrides)
    return d


def create_member_payload(**overrides) -> dict:
    d = {"full_name": "Member", "seat_number": 1}
    d.update(overrides)
    return d


def create_venue_payload(**overrides) -> dict:
    d = {"name": "Chamber"}
    d.update(overrides)
    return d


def create_meeting_payload(venue_id, presiding_member_id, **overrides) -> dict:
    d = {
        "venue_id": venue_id,
        "presiding_member_id": presiding_member_id,
        "title": "Meeting",
        "meeting_type": "EMERGENCY",
        "scheduled_start": "2026-05-01T02:00:00Z",
        "scheduled_end": "2026-05-01T03:00:00Z",
    }
    d.update(overrides)
    return d


def create_agenda_item_payload(**overrides) -> dict:
    d = {"title": "Agenda Item", "sequence": 1}
    d.update(overrides)
    return d


def create_speaker_slip_payload(requester_id, **overrides) -> dict:
    d = {"requester_id": requester_id, "speaker_name": "Speaker"}
    d.update(overrides)
    return d


def create_motion_payload(moved_by_member_id, seconded_by_member_id, **overrides) -> dict:
    d = {
        "text": "A motion",
        "moved_by_member_id": moved_by_member_id,
        "seconded_by_member_id": seconded_by_member_id,
    }
    d.update(overrides)
    return d


def create_records_request_payload(requester_id, body_id, **overrides) -> dict:
    d = {
        "requester_id": requester_id,
        "body_id": body_id,
        "subject": "Records",
        "description": "All responsive records",
        "estimated_page_count": 0,
    }
    d.update(overrides)
    return d


def create_document_payload(**overrides) -> dict:
    d = {
        "title": "Document",
        "page_count": 10,
        "review_minutes": 0,
        "retention_series": "ADMIN",
    }
    d.update(overrides)
    return d


def create_appeal_payload(**overrides) -> dict:
    d = {"grounds": "Wrongful denial"}
    d.update(overrides)
    return d
