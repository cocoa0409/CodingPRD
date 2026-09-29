"""Request-payload factories.

Each builder returns a minimal, PRD-valid body for one write endpoint and
accepts ``**overrides`` so a test can vary exactly the field under study.
Monetary amounts are integer cents (PRD §2.4) and GPAs are three-decimal
numbers (PRD §2.8); no money or GPA value is ever emitted as a string.
"""
import itertools
from typing import Any, Dict

_counter = itertools.count(1)


def _n() -> int:
    """Monotonic suffix so uniqueness-constrained names never collide."""
    return next(_counter)


# --------------------------------------------------------------------------
# Districts (PRD §3.1)
# --------------------------------------------------------------------------
def district_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"District {_n()}",
        "state_code": "CA",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Schools (PRD §3.1)
# --------------------------------------------------------------------------
def school_payload(district_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "district_id": district_id,
        "name": f"School {_n()}",
        "nces_code": f"NCES-{_n():05d}",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Coaches (PRD §3.2)
# --------------------------------------------------------------------------
def coach_payload(school_id: str, **overrides: Any) -> Dict[str, Any]:
    n = _n()
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "full_name": f"Coach {n}",
        "email": f"coach{n}@example.org",
    }
    payload.update(overrides)
    return payload


def certification_payload(**overrides: Any) -> Dict[str, Any]:
    """Default is a CERTIFY with a background check well in the future."""
    payload: Dict[str, Any] = {
        "action": "CERTIFY",
        "background_check_expires_on": "2027-06-30",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Students (PRD §3.2)
# --------------------------------------------------------------------------
def student_payload(school_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "school_id": school_id,
        "full_name": f"Student {_n()}",
        # 2010-05-01 is 16 completed years at the default age_cutoff_date
        # 2026-09-01: at or above the default min_player_age of 13 and
        # strictly below the default max_age of 19 (PRD §3.5).
        "birthdate": "2010-05-01",
        "grade_level": 11,
    }
    payload.update(overrides)
    return payload


def academic_posting_payload(
    expected_student_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "term_label": f"Term {_n()}",
        "term_gpa": 3.500,
        "term_credits": 6.0,
        "expected_student_version": expected_student_version,
    }
    payload.update(overrides)
    return payload


def showcase_nomination_payload(
    nominating_team_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"nominating_team_id": nominating_team_id}
    payload.update(overrides)
    return payload


def recruiting_contact_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Titles (PRD §3.3)
# --------------------------------------------------------------------------
def title_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"Title {_n()}",
        "publisher": "Example Publisher",
    }
    payload.update(overrides)
    return payload


def title_approval_payload(
    district_id: str, title_id: str, requested_by_school_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "district_id": district_id,
        "title_id": title_id,
        "requested_by_school_id": requested_by_school_id,
    }
    payload.update(overrides)
    return payload


def approval_decision_payload(action: str = "APPROVE", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Seasons (PRD §3.4)
# --------------------------------------------------------------------------
def season_payload(title_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title_id": title_id,
        "name": f"Season {_n()}",
    }
    payload.update(overrides)
    return payload


def advance_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return payload


def seeding_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Teams (PRD §3.5)
# --------------------------------------------------------------------------
def team_payload(
    season_id: str, school_id: str, title_id: str, coach_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "school_id": school_id,
        "title_id": title_id,
        "coach_id": coach_id,
        "name": f"Team {_n()}",
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Roster slots (PRD §3.5)
# --------------------------------------------------------------------------
def roster_slot_payload(
    team_id: str, student_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"team_id": team_id, "student_id": student_id}
    payload.update(overrides)
    return payload


def verify_enrollment_payload(verified_birthdate: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "enrollment_document_ref": f"DOC-{_n():05d}",
        "verified_birthdate": verified_birthdate,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Matches (PRD §3.7)
# --------------------------------------------------------------------------
def match_payload(
    season_id: str,
    home_team_id: str,
    away_team_id: str,
    scheduled_start_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "season_id": season_id,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "scheduled_start_at": scheduled_start_at,
    }
    payload.update(overrides)
    return payload


def server_config_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"region_code": "NA-WEST", "patch_version": "1.2.3"}
    payload.update(overrides)
    return payload


def result_report_payload(
    reporting_team_id: str,
    home_games_won: int,
    away_games_won: int,
    expected_match_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "reporting_team_id": reporting_team_id,
        "home_games_won": home_games_won,
        "away_games_won": away_games_won,
        "expected_match_version": expected_match_version,
    }
    payload.update(overrides)
    return payload


def forfeit_payload(forfeiting_team_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"forfeiting_team_id": forfeiting_team_id}
    payload.update(overrides)
    return payload


def dispute_payload(
    filing_team_id: str,
    dispute_reason_code: str = "SCORE_MISMATCH",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "filing_team_id": filing_team_id,
        "dispute_reason_code": dispute_reason_code,
    }
    payload.update(overrides)
    return payload


def dispute_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


def broadcast_register_payload(
    broadcast_school_id: str,
    broadcast_start_at: str,
    broadcast_end_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "action": "REGISTER",
        "broadcast_school_id": broadcast_school_id,
        "broadcast_start_at": broadcast_start_at,
        "broadcast_end_at": broadcast_end_at,
    }
    payload.update(overrides)
    return payload


def broadcast_action_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Fair-play cases (PRD §3.8)
# --------------------------------------------------------------------------
def student_case_payload(
    team_id: str, subject_student_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "team_id": team_id,
        "subject_type": "STUDENT",
        "subject_student_id": subject_student_id,
        "case_type": "ACCOUNT_SHARING",
        "evidence_ref": f"EV-{_n():05d}",
    }
    payload.update(overrides)
    return payload


def broadcast_case_payload(
    team_id: str, subject_match_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "team_id": team_id,
        "subject_type": "MATCH_BROADCAST",
        "subject_match_id": subject_match_id,
        "case_type": "SPECTATOR_CONDUCT",
        "evidence_ref": f"EV-{_n():05d}",
    }
    payload.update(overrides)
    return payload


def case_decision_payload(
    decision: str = "SUSTAIN", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision == "SUSTAIN":
        payload["severity"] = "MINOR"
    payload.update(overrides)
    return payload


def appeal_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"appeal_grounds": "Written grounds for appeal."}
    payload.update(overrides)
    return payload


def appeal_decision_payload(decision: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    payload.update(overrides)
    return payload
