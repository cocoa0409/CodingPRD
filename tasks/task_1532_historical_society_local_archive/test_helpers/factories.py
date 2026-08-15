"""Payload factories — one per entity, input fields only."""

DONOR = {"donor_name": "E. Stone", "donor_contact": "stone@example.org"}


def create_storage_zone_payload(**overrides) -> dict:
    defaults = {"zone_code": "Z1", "name": "Vault A"}
    defaults.update(overrides)
    return defaults


def create_collection_payload(**overrides) -> dict:
    defaults = {
        "title": "Pioneer Papers",
        "collection_code": "C1",
    }
    defaults.update(overrides)
    return defaults


def create_accession_payload(**overrides) -> dict:
    defaults = {
        "donor_name": DONOR["donor_name"],
        "donor_contact": DONOR["donor_contact"],
        "accession_date": "2026-07-15",
        "lot_appraised_value_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_deed_payload(**overrides) -> dict:
    return dict(overrides)


def create_item_payload(**overrides) -> dict:
    defaults = {"title": "Ledger"}
    defaults.update(overrides)
    return defaults


def catalog_item_payload(**overrides) -> dict:
    defaults = {
        "description": "x",
        "condition_grade": "GOOD",
        "appraised_value_cents": 100,
        "format": "MAP",
    }
    defaults.update(overrides)
    return defaults


def create_assessment_payload(**overrides) -> dict:
    defaults = {
        "condition_grade_observed": "POOR",
        "urgency_score": 60,
        "treatment_estimate_hours": 5,
    }
    defaults.update(overrides)
    return defaults


def create_finding_aid_payload(**overrides) -> dict:
    defaults = {"title": "FA", "summary": "S"}
    defaults.update(overrides)
    return defaults


def create_project_payload(**overrides) -> dict:
    defaults = {"name": "P1"}
    defaults.update(overrides)
    return defaults


def create_ticket_payload(**overrides) -> dict:
    return dict(overrides)


def create_researcher_payload(**overrides) -> dict:
    defaults = {"full_name": "R. Reader", "email": "r1@example.org"}
    defaults.update(overrides)
    return defaults


def create_request_payload(**overrides) -> dict:
    defaults = {"topic": "t", "purpose": "PERSONAL"}
    defaults.update(overrides)
    return defaults


def create_appointment_payload(**overrides) -> dict:
    defaults = {
        "room_code": "MAIN",
        "scheduled_date": "2026-08-10",
        "start_time": "10:00",
        "end_time": "12:00",
    }
    defaults.update(overrides)
    return defaults


def create_reproduction_order_payload(**overrides) -> dict:
    defaults = {
        "format": "SCAN_STANDARD",
        "page_estimate": 60,
        "license_class": "PERSONAL",
        "rush": False,
    }
    defaults.update(overrides)
    return defaults


def create_proposal_payload(**overrides) -> dict:
    defaults = {
        "justification": "Duplicates of state library holdings",
        "disposal_method": "TRANSFER",
    }
    defaults.update(overrides)
    return defaults


def create_oral_history_payload(**overrides) -> dict:
    defaults = {
        "narrator_name": "N. One",
        "interviewer_name": "I. One",
        "recording_room_id": "STUDIO_A",
        "session_start": "2026-09-01T10:00:00Z",
        "session_end": "2026-09-01T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def zone_reading_payload(**overrides) -> dict:
    defaults = {
        "recorded_at": "2026-08-01T01:00:00Z",
        "temperature_c": 25.0,
        "humidity_pct": 50.0,
    }
    defaults.update(overrides)
    return defaults
