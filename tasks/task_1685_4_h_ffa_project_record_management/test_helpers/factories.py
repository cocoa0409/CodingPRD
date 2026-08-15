"""Payload factories — one per entity, input fields only.

Unique suffixes keep names/emails/labels collision-free inside a single test
(the database is reset between tests, so cross-test uniqueness is unnecessary).
"""
import uuid

from .constants import TEST_DEFAULTS


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}


def create_club_payload(**overrides) -> dict:
    defaults = {"name": _uniq("Club"), "county_code": "TC"}
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(club_id: str, **overrides) -> dict:
    defaults = {
        "full_name": _uniq("Vol"),
        "email": f"{uuid.uuid4().hex[:10]}@example.com",
        "base_clearance": TEST_DEFAULTS["VOL_BASE_CLEARANCE"],
        "risk_flags": TEST_DEFAULTS["VOL_RISK_FLAGS"],
        "years_service": TEST_DEFAULTS["VOL_YEARS_SERVICE"],
        "club_id": club_id,
    }
    defaults.update(overrides)
    return defaults


def create_screening_event_payload(volunteer_id: str, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "event_kind": "BACKGROUND_CHECK",
        "outcome": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(club_id: str, **overrides) -> dict:
    defaults = {
        "full_name": _uniq("Mem"),
        "birth_date": "2009-01-01",
        "club_id": club_id,
        "is_club_officer": False,
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "project_type": "FOODS",
        "program_year": TEST_DEFAULTS["PROGRAM_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_animal_tag_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "tag_number": _uniq("TAG"),
        "species": "SHEEP",
        "owned_since": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_record_book_payload(project_id: str, **overrides) -> dict:
    defaults = {"project_id": project_id, "program_year": TEST_DEFAULTS["PROGRAM_YEAR"]}
    defaults.update(overrides)
    return defaults


def create_ledger_entry_payload(record_book_id: str, **overrides) -> dict:
    defaults = {
        "record_book_id": record_book_id,
        "entry_kind": "EXPENSE",
        "amount_cents": 1000,
        "hours": 0,
        "recorded_on": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def submit_record_book_payload(expected_record_book_version: int, **overrides) -> dict:
    scores = dict(TEST_DEFAULTS["SCORES_81"])
    scores.update(overrides)
    return {"expected_record_book_version": expected_record_book_version, **scores}


def create_room_payload(**overrides) -> dict:
    defaults = {"name": _uniq("Room"), "capacity": 30}
    defaults.update(overrides)
    return defaults


def create_meeting_payload(club_id: str, room_id: str, **overrides) -> dict:
    defaults = {
        "club_id": club_id,
        "starts_at": "2026-06-01T18:00:00Z",
        "ends_at": "2026-06-01T19:00:00Z",
        "room_id": room_id,
    }
    defaults.update(overrides)
    return defaults


def create_attendance_payload(meeting_id: str, member_id: str, **overrides) -> dict:
    defaults = {
        "meeting_id": meeting_id,
        "member_id": member_id,
        "attendance_status": "PRESENT",
    }
    defaults.update(overrides)
    return defaults


def create_pen_payload(**overrides) -> dict:
    defaults = {"label": _uniq("Pen"), "animal_capacity": 2}
    defaults.update(overrides)
    return defaults


def create_fair_entry_payload(member_id: str, project_id: str, **overrides) -> dict:
    defaults = {"member_id": member_id, "project_id": project_id, "fair_level": "COUNTY"}
    defaults.update(overrides)
    return defaults


def create_stall_assignment_payload(fair_entry_id: str, pen_id: str, **overrides) -> dict:
    defaults = {"fair_entry_id": fair_entry_id, "pen_id": pen_id}
    defaults.update(overrides)
    return defaults


def create_award_application_payload(member_id: str, record_book_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "award_track": "DEGREE",
        "record_book_id": record_book_id,
    }
    defaults.update(overrides)
    return defaults


def nominate_award_payload(expected_club_version: int) -> dict:
    return {"expected_club_version": expected_club_version}


def evaluate_award_payload(participation_pct: int, leadership_pts: int) -> dict:
    return {"participation_pct": participation_pct, "leadership_pts": leadership_pts}


def complete_project_payload(grade: str = "A") -> dict:
    return {"grade": grade}


def create_scholarship_app_payload(member_id: str, linked_award_application_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "linked_award_application_id": linked_award_application_id,
    }
    defaults.update(overrides)
    return defaults


def create_treasury_transaction_payload(club_id: str, **overrides) -> dict:
    defaults = {"club_id": club_id, "txn_kind": "DUES_PAYMENT", "amount_cents": 1000}
    defaults.update(overrides)
    return defaults
