"""Request payload builders.

Every builder returns a valid payload that a test can adjust through keyword
overrides. Passing ``OMIT`` as an override value deletes the key, which is how
tests exercise a missing required field or a field that must be absent.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .constants import (
    CLOCK_INITIAL,
    DEFAULT_PASSING_SCORE,
    DEFAULT_REFRESH_INTERVAL_DAYS,
    DEFAULT_REVIEW_INTERVAL_DAYS,
)


class _Omit:
    """Sentinel meaning "delete this key from the payload"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


def _apply(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in overrides.items():
        if isinstance(value, _Omit):
            payload.pop(key, None)
        else:
            payload[key] = value
    # A builder's positional argument may also be OMIT, which deletes the key.
    return {key: value for key, value in payload.items() if not isinstance(value, _Omit)}


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------


def build_worksite(**overrides: Any) -> Dict[str, Any]:
    """A twenty-person California plant."""
    return _apply({"name": "North Plant", "state_code": "CA", "employee_count": 20}, overrides)


def build_work_area(worksite_id: str, **overrides: Any) -> Dict[str, Any]:
    """The public-facing, night-staffed cash-handling front desk."""
    return _apply(
        {
            "worksite_id": worksite_id,
            "name": "Front Desk",
            "job_function": "CASH_HANDLING",
            "public_access_flag": True,
            "lone_worker_flag": False,
            "night_shift_flag": True,
            "occupancy_cap": 8,
        },
        overrides,
    )


def build_employee(
    worksite_id: str, work_area_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """An administrative worker posted to the given area."""
    payload: Dict[str, Any] = {
        "worksite_id": worksite_id,
        "work_area_id": work_area_id,
        "full_name": "Sofia Ortiz",
        "job_function": "ADMIN",
    }
    return _apply(payload, overrides)


# --------------------------------------------------------------------------
# Prevention plans and hazard assessments
# --------------------------------------------------------------------------


def build_prevention_plan(worksite_id: str, **overrides: Any) -> Dict[str, Any]:
    """A plan effective on the initial clock instant with the annual review interval."""
    return _apply(
        {
            "worksite_id": worksite_id,
            "effective_date": CLOCK_INITIAL,
            "review_interval_days": DEFAULT_REVIEW_INTERVAL_DAYS,
        },
        overrides,
    )


def build_plan_submission(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"submission_note": "Initial prevention plan for the North Plant front desk."}, overrides
    )


def build_plan_activation(**overrides: Any) -> Dict[str, Any]:
    return _apply({"activation_note": "Reviewed on site walkthrough; approved."}, overrides)


def build_plan_revision_return(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"revision_reason": "Hazard narrative for the loading dock is still missing."}, overrides
    )


def build_hazard_assessment(
    plan_id: str, work_area_id: str, expected_plan_version: int, **overrides: Any
) -> Dict[str, Any]:
    """Four prior incidents, high proximity, two staff per shift."""
    return _apply(
        {
            "plan_id": plan_id,
            "work_area_id": work_area_id,
            "reported_incident_count": 4,
            "proximity_factor": "HIGH",
            "cash_on_hand_cents": 0,
            "min_staff_per_shift": 2,
            "expected_plan_version": expected_plan_version,
        },
        overrides,
    )


def build_hazard_validation(**overrides: Any) -> Dict[str, Any]:
    """A walkthrough crediting three administrative controls and a barrier."""
    return _apply(
        {
            "walkthrough_note": "Barrier fitted at the counter and three administrative controls verified.",
            "mitigation_credits": 3,
            "barrier_installed": True,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Training
# --------------------------------------------------------------------------


def build_training_module(
    code: str = "WVP-ADMIN",
    job_function_scope: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "code": code,
            "job_function_scope": list(job_function_scope or ["ADMIN"]),
            "scenario_set_version": "2026.1",
            "refresh_interval_days": DEFAULT_REFRESH_INTERVAL_DAYS,
            "passing_score": DEFAULT_PASSING_SCORE,
            "required_for_escort": False,
        },
        overrides,
    )


def build_escort_module(**overrides: Any) -> Dict[str, Any]:
    """The module whose completion is a precondition for acting as an escort."""
    return _apply(
        build_training_module(
            code="ESC-101",
            job_function_scope=["SECURITY"],
            required_for_escort=True,
        ),
        overrides,
    )


def build_training_assignment(
    employee_id: str, module_id: str, expected_employee_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "employee_id": employee_id,
            "module_id": module_id,
            "due_at": "2026-08-10T00:00:00Z",
            "expected_employee_version": expected_employee_version,
        },
        overrides,
    )


def build_training_completion(score: int = 92, **overrides: Any) -> Dict[str, Any]:
    return _apply({"score": score}, overrides)


def build_separation(**overrides: Any) -> Dict[str, Any]:
    return _apply({"separation_reason": "Resigned at the end of the shift."}, overrides)


# --------------------------------------------------------------------------
# Incident reports
# --------------------------------------------------------------------------


def build_incident_report(
    worksite_id: str, work_area_id: str, reporter_employee_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """A weaponed, first-aid coworker incident filed through the web form."""
    payload: Dict[str, Any] = {
        "worksite_id": worksite_id,
        "work_area_id": work_area_id,
        "reporter_employee_id": reporter_employee_id,
        "channel": "WEB_FORM",
        "occurred_at": "2026-07-30T14:00:00Z",
        "narrative": "Co-worker brandished a box cutter during a shift handover argument.",
        "incident_type": "TYPE_3_COWORKER",
        "weapon_involved": True,
        "injury_level": "FIRST_AID",
    }
    return _apply(payload, overrides)


def build_triage(disposition: str = "ESCALATE", **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {
            "disposition": disposition,
            "triage_note": "Weapon present; convening the threat assessment team.",
        },
        overrides,
    )


def build_retaliation_update(action: str, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"action": action, "statement": "My shift was changed the day after I filed this report."},
        overrides,
    )


# --------------------------------------------------------------------------
# Threat cases
# --------------------------------------------------------------------------


def build_threat_case(incident_report_id: str, lead_employee_id: str, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"incident_report_id": incident_report_id, "lead_employee_id": lead_employee_id}, overrides
    )


def build_team_assignment(
    member_employee_id: str, discipline: str, role_on_team: str = "VOTING_MEMBER", **overrides: Any
) -> Dict[str, Any]:
    return _apply(
        {
            "member_employee_id": member_employee_id,
            "discipline": discipline,
            "role_on_team": role_on_team,
        },
        overrides,
    )


def build_convene(**overrides: Any) -> Dict[str, Any]:
    return _apply({"convene_note": "Five disciplines seated; opening round 1."}, overrides)


def build_ballot(ballot_value: str, rationale: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"ballot_value": ballot_value, "rationale": rationale}, overrides)


def build_reassess(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"reassess_reason": "New witness statement arrived; the team needs a second round."},
        overrides,
    )


def build_decision(disposition: str, **overrides: Any) -> Dict[str, Any]:
    return _apply({"disposition": disposition}, overrides)


def build_closure(**overrides: Any) -> Dict[str, Any]:
    return _apply({"closure_summary": "Monitoring complete; the case is closed."}, overrides)


# --------------------------------------------------------------------------
# Case actions
# --------------------------------------------------------------------------


def build_protective_action(
    case_id: str,
    action_type: str,
    subject_employee_id: str,
    starts_at: str,
    ends_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "case_id": case_id,
            "action_class": "PROTECTIVE",
            "action_type": action_type,
            "subject_employee_id": subject_employee_id,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "note": "Protective measure recorded for the protected employee.",
        },
        overrides,
    )


def build_escort_action(
    case_id: str,
    subject_employee_id: str,
    escort_employee_id: str,
    starts_at: str,
    ends_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        build_protective_action(
            case_id,
            "SECURITY_ESCORT",
            subject_employee_id,
            starts_at,
            ends_at,
            escort_employee_id=escort_employee_id,
            note="Security escort between the car park and the front desk.",
        ),
        overrides,
    )


def build_access_restriction(
    case_id: str,
    subject_employee_id: str,
    work_area_id: str,
    starts_at: str,
    ends_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        build_protective_action(
            case_id,
            "ACCESS_RESTRICTION",
            subject_employee_id,
            starts_at,
            ends_at,
            work_area_id=work_area_id,
            note="Subject barred from the front desk for the duration of the window.",
        ),
        overrides,
    )


def build_post_incident_action(
    case_id: str,
    action_type: str,
    assigned_employee_id: str,
    due_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _apply(
        {
            "case_id": case_id,
            "action_class": "POST_INCIDENT",
            "action_type": action_type,
            "assigned_employee_id": assigned_employee_id,
            "due_at": due_at,
            "note": "Post-incident follow-up for the protected employee.",
        },
        overrides,
    )


def build_revocation(**overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"revocation_reason": "Subject moved off site, so the measure is no longer needed."},
        overrides,
    )


def build_action_completion(**overrides: Any) -> Dict[str, Any]:
    return _apply({"completion_note": "Follow-up delivered and documented."}, overrides)


# --------------------------------------------------------------------------
# Violent incident log
# --------------------------------------------------------------------------


def build_log_amendment(**overrides: Any) -> Dict[str, Any]:
    """An amendment supplying the two outcome elements the auto entry lacks."""
    return _apply(
        {
            "amendment_reason": "Adding the two outcome elements required by the recordkeeping rule.",
            "consequence_narrative": "Subject separated from the shift; no lost time recorded.",
            "controls_summary": "Badge control installed at the front desk and escorts scheduled.",
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Drills
# --------------------------------------------------------------------------


def build_drill(plan_id: str, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {
            "plan_id": plan_id,
            "scenario_type": "ACTIVE_ASSAILANT",
            "scheduled_at": "2026-08-01T09:00:00Z",
        },
        overrides,
    )


def build_drill_execution(participant_count: int, findings_count: int = 2, **overrides: Any) -> Dict[str, Any]:
    return _apply(
        {"participant_count": participant_count, "findings_count": findings_count}, overrides
    )


# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------


def build_clock(current_utc: str = CLOCK_INITIAL, **overrides: Any) -> Dict[str, Any]:
    return _apply({"current_utc": current_utc}, overrides)
