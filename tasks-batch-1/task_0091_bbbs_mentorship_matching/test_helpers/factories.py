"""Payload factories — one per entity, input fields only (PRD §3.1–§3.7)."""
import itertools

_counter = itertools.count(1)


def _unique_email(prefix: str) -> str:
    return f"{prefix}{next(_counter)}@example.com"


def create_volunteer_payload(**overrides) -> dict:
    """POST /volunteers input fields (PRD §3.1)."""
    defaults = {
        "full_name": "Volunteer Big",
        "email": _unique_email("vol"),
        "gender": "MALE",
        "home_zip": "10001",
        "interest_tags": ["SPORTS"],
        "max_weekly_hours": 5,
    }
    defaults.update(overrides)
    return defaults


def create_guardian_payload(**overrides) -> dict:
    """POST /guardians input fields (PRD §3.3). consent_on_file defaults to false."""
    defaults = {
        "full_name": "Guardian Parent",
        "email": _unique_email("guard"),
    }
    defaults.update(overrides)
    return defaults


def create_child_payload(guardian_id, **overrides) -> dict:
    """POST /children input fields (PRD §3.3). requires_same_gender optional."""
    defaults = {
        "guardian_id": guardian_id,
        "first_name": "Little One",
        "age": 10,
        "gender": "MALE",
        "home_zip": "10001",
        "interest_tags": ["SPORTS"],
    }
    defaults.update(overrides)
    return defaults


def adjudicate_payload(decision: str, adverse_findings: int = 0) -> dict:
    """POST /background-checks/{id}/adjudicate input (PRD §3.1)."""
    return {"decision": decision, "adverse_findings": adverse_findings}


def schedule_meeting_payload(scheduled_start, scheduled_end, location="Library") -> dict:
    """POST /matches/{id}/meetings input (PRD §3.5)."""
    return {
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "location": location,
    }


def activity_payload(occurred_at, duration_minutes, activity_type="OUTING") -> dict:
    """POST /matches/{id}/activities input (PRD §3.6)."""
    return {
        "occurred_at": occurred_at,
        "duration_minutes": duration_minutes,
        "activity_type": activity_type,
    }


def complete_contact_payload(contacted_at, party="BIG", **overrides) -> dict:
    """POST /supervision-contacts/{id}/complete input (PRD §3.6)."""
    defaults = {"contacted_at": contacted_at, "party": party}
    defaults.update(overrides)
    return defaults


def exit_transition_payload(
    exit_type, initiated_by="AGENCY", reason_code="GRADUATION"
) -> dict:
    """POST /matches/{id}/exit-transitions input (PRD §3.7)."""
    return {
        "exit_type": exit_type,
        "initiated_by": initiated_by,
        "reason_code": reason_code,
    }


def outcome_survey_payload(
    match_id, exit_transition_id, relationship_quality, child_outcome, would_rematch
) -> dict:
    """POST /outcome-surveys input (PRD §3.7)."""
    return {
        "match_id": match_id,
        "exit_transition_id": exit_transition_id,
        "relationship_quality": relationship_quality,
        "child_outcome": child_outcome,
        "would_rematch": would_rematch,
    }
