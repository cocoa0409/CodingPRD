"""Payload factories — one per creatable entity, input fields only.

Every field name matches the PRD exactly. Only `source: input` fields appear
here; computed and system fields are never sent.
"""
from .constants import AUTH_VALID_FROM, AUTH_VALID_UNTIL


def create_child_payload(**overrides) -> dict:
    """POST /clinic/children — full_name, date_of_birth (ISO YYYY-MM-DD)."""
    defaults = {
        "full_name": "Test Child",
        "date_of_birth": "2023-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_therapist_payload(**overrides) -> dict:
    """POST /clinic/therapists — full_name, discipline, max_caseload,
    weekly_visit_minutes_cap."""
    defaults = {
        "full_name": "Test Therapist",
        "discipline": "SLP",
        "max_caseload": 5,
        "weekly_visit_minutes_cap": 600,
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(child_id: str, **overrides) -> dict:
    """POST /clinic/evaluations — child_id, discipline, severity_score."""
    defaults = {
        "child_id": child_id,
        "discipline": "SLP",
        "severity_score": 40,
    }
    defaults.update(overrides)
    return defaults


def create_plan_of_care_payload(child_id: str, evaluation_id: str,
                                primary_therapist_id: str, **overrides) -> dict:
    """POST /clinic/plans-of-care — child_id, evaluation_id,
    primary_therapist_id, planned_weekly_minutes."""
    defaults = {
        "child_id": child_id,
        "evaluation_id": evaluation_id,
        "primary_therapist_id": primary_therapist_id,
        "planned_weekly_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_goal_payload(**overrides) -> dict:
    """POST /clinic/plans-of-care/{planId}/goals — description, weight,
    baseline_pct, target_pct."""
    defaults = {
        "description": "Test goal",
        "weight": 1,
        "baseline_pct": 0,
        "target_pct": 50,
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(child_id: str, **overrides) -> dict:
    """POST /clinic/authorizations — child_id, discipline, payer_name,
    authorized_visits, valid_from, valid_until."""
    defaults = {
        "child_id": child_id,
        "discipline": "SLP",
        "payer_name": "PayerX",
        "authorized_visits": 3,
        "valid_from": AUTH_VALID_FROM,
        "valid_until": AUTH_VALID_UNTIL,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(child_id: str, therapist_id: str,
                               authorization_id: str, plan_of_care_id: str,
                               start_time: str, end_time: str, **overrides) -> dict:
    """POST /clinic/appointments — child_id, therapist_id, authorization_id,
    plan_of_care_id, start_time, end_time."""
    defaults = {
        "child_id": child_id,
        "therapist_id": therapist_id,
        "authorization_id": authorization_id,
        "plan_of_care_id": plan_of_care_id,
        "start_time": start_time,
        "end_time": end_time,
    }
    defaults.update(overrides)
    return defaults


def complete_appointment_payload(narrative: str = "Session completed fine.",
                                 minutes_delivered: int = 45,
                                 goal_progress_entries=None, **overrides) -> dict:
    """POST /clinic/appointments/{id}/complete — narrative, minutes_delivered,
    goal_progress_entries (array of {goal_id, recorded_pct})."""
    defaults = {
        "narrative": narrative,
        "minutes_delivered": minutes_delivered,
        "goal_progress_entries": goal_progress_entries if goal_progress_entries is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_coordination_plan_payload(child_id: str, **overrides) -> dict:
    """POST /clinic/coordination-plans — child_id, plan_type, jurisdiction,
    review_due_time."""
    defaults = {
        "child_id": child_id,
        "plan_type": "IFSP",
        "jurisdiction": "Lead Agency",
        "review_due_time": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_home_program_payload(**overrides) -> dict:
    """POST /clinic/plans-of-care/{planId}/home-programs — title,
    weekly_target_sessions, parent_training_completed (optional)."""
    defaults = {
        "title": "Daily oral-motor drills",
        "weekly_target_sessions": 5,
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(child_id: str, therapist_id: str,
                                  evaluation_id: str, **overrides) -> dict:
    """POST /clinic/waitlist-entries — child_id, therapist_id, discipline,
    evaluation_id, requested_minutes."""
    defaults = {
        "child_id": child_id,
        "therapist_id": therapist_id,
        "discipline": "SLP",
        "evaluation_id": evaluation_id,
        "requested_minutes": 45,
    }
    defaults.update(overrides)
    return defaults


def accept_waitlist_payload(authorization_id: str, plan_of_care_id: str,
                            start_time: str, end_time: str, **overrides) -> dict:
    """POST /clinic/waitlist-entries/{id}/accept — authorization_id,
    plan_of_care_id, start_time, end_time."""
    defaults = {
        "authorization_id": authorization_id,
        "plan_of_care_id": plan_of_care_id,
        "start_time": start_time,
        "end_time": end_time,
    }
    defaults.update(overrides)
    return defaults
