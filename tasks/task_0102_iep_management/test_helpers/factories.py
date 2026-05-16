"""Payload factories — one per endpoint that accepts input fields.

Each factory emits the exact JSON-body schema the PRD declares for the
request body (PRD §3 narrative + §4 endpoint table). Tests pass
overrides for the values they want to control. Only PRD-declared input
fields are produced; computed/system fields are intentionally omitted
so the implementation cannot accidentally accept them as inputs.

PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
"""
from __future__ import annotations

import random
import string
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Timestamp helpers — PRD §2.4 format with three fractional digits.
# ---------------------------------------------------------------------------
def iso_utc(dt: datetime) -> str:
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def iso_now() -> str:
    return iso_utc(utcnow())


def date_iso(year: int, month: int, day: int) -> str:
    """Return ISO 8601 UTC datetime at midnight for a given date."""
    return iso_utc(datetime(year, month, day, tzinfo=timezone.utc))


_ALPHANUM = string.ascii_uppercase + string.digits


def random_suffix(n: int = 8) -> str:
    return "".join(random.choices(_ALPHANUM, k=n))


# ---------------------------------------------------------------------------
# District — PRD §3.1
# ---------------------------------------------------------------------------
def create_district_payload(
    *,
    name: Optional[str] = None,
    state_code: str = "NY",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /districts — DistrictAdmin only.

    PRD §3.1: required input fields are `name` and `state_code` (a
    two-letter US state code).
    """
    payload: Dict[str, Any] = {
        "name": name if name is not None else f"District {random_suffix(4)}",
        "state_code": state_code,
    }
    payload.update(overrides)
    return payload


def clock_advance_payload(
    *,
    by_days: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /districts/{id}/clock/advance — DistrictAdmin only.

    PRD §2.7: "an integer by_days in the request body, validated as an
    integer between 1 and 3650 inclusive".
    """
    payload: Dict[str, Any] = {"by_days": by_days}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Student — PRD §3.1
# ---------------------------------------------------------------------------
def create_student_payload(
    *,
    external_student_number: Optional[str] = None,
    date_of_birth: str = TEST_DEFAULTS["DEFAULT_DOB"],
    parent_user_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST /districts/{id}/students — DistrictAdmin only.

    PRD §3.1: required input fields are `external_student_number`,
    `date_of_birth`, and `parent_user_id`.
    """
    payload: Dict[str, Any] = {
        "external_student_number": (
            external_student_number
            if external_student_number is not None
            else f"STU-{random_suffix(6)}"
        ),
        "date_of_birth": date_of_birth,
        "parent_user_id": (
            parent_user_id
            if parent_user_id is not None
            else f"parent-{random_suffix(6)}"
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EligibilityEvaluation — PRD §3.2
# ---------------------------------------------------------------------------
def create_evaluation_payload(
    *,
    evaluation_type: str = "INITIAL",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../eligibility-evaluations — SchoolPsychologist only.

    PRD §3.2: required input is `evaluation_type` (INITIAL, TRIENNIAL,
    or INTERIM).
    """
    payload: Dict[str, Any] = {"evaluation_type": evaluation_type}
    payload.update(overrides)
    return payload


def finalize_evaluation_payload(
    *,
    disability_categories: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../eligibility-evaluations/{id}/finalize.

    PRD §3.2: "A non-empty disability_categories array drives the
    evaluation to ELIGIBLE; an empty array drives it to INELIGIBLE."
    """
    if disability_categories is None:
        disability_categories = ["SLD"]
    payload: Dict[str, Any] = {
        "disability_categories": list(disability_categories),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ParentalConsent — PRD §3.4
# ---------------------------------------------------------------------------
def create_consent_payload(
    *,
    scope: str,
    target_resource_type: str,
    target_resource_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../parental-consents.

    PRD §3.4 pairings: scope=IEP_IMPLEMENTATION→IEP;
    scope=RELATED_SERVICE→RelatedService; scope=PLACEMENT_CHANGE→Student.
    (scope=EVALUATION consents are auto-created by request-consent and
    are NOT created via this endpoint.)
    """
    payload: Dict[str, Any] = {
        "scope": scope,
        "target_resource_type": target_resource_type,
        "target_resource_id": target_resource_id,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# IEP — PRD §3.3
# ---------------------------------------------------------------------------
def create_iep_payload(
    *,
    meeting_held_at: Optional[str] = None,
    effective_start_date: Optional[str] = None,
    total_instructional_minutes_per_week: int = TEST_DEFAULTS[
        "TOTAL_INSTRUCTIONAL_MINUTES"
    ],
    total_school_day_minutes_per_week: int = TEST_DEFAULTS[
        "TOTAL_SCHOOL_DAY_MINUTES"
    ],
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../ieps — SpecialEducationTeacher only.

    PRD §3.3: required input fields are `meeting_held_at`,
    `effective_start_date`, `total_instructional_minutes_per_week`,
    `total_school_day_minutes_per_week`.
    """
    # Default meeting_held_at to the initial logical-clock date so it
    # is at or before District.current_date (PRD §3.3 activation gate;
    # PRD §2.7 says District.current_date starts at 2025-01-01T00:00:00.000Z).
    payload: Dict[str, Any] = {
        "meeting_held_at": (
            meeting_held_at if meeting_held_at is not None
            else "2025-01-01T00:00:00.000Z"
        ),
        "effective_start_date": (
            effective_start_date if effective_start_date is not None
            else "2025-01-15T00:00:00.000Z"
        ),
        "total_instructional_minutes_per_week": (
            total_instructional_minutes_per_week
        ),
        "total_school_day_minutes_per_week": (
            total_school_day_minutes_per_week
        ),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# IEPGoal — PRD §3.3
# ---------------------------------------------------------------------------
def make_objective(
    *,
    objective_id: Optional[str] = None,
    weight: float = 1.0,
    latest_progress_percent: int = 0,
) -> Dict[str, Any]:
    """One objective row. PRD §3.3: each objective is a record
    containing `objective_id`, a `weight` strictly greater than zero
    and less than or equal to one, and a `latest_progress_percent`
    that ranges from 0 through 100 inclusive and defaults to 0 when
    the goal is created.
    """
    return {
        "objective_id": (
            objective_id if objective_id is not None
            else f"obj-{random_suffix(4)}"
        ),
        "weight": weight,
        "latest_progress_percent": latest_progress_percent,
    }


def create_goal_payload(
    *,
    domain: str = "ACADEMIC",
    description: str = "Demonstrate grade-level reading comprehension.",
    objectives: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../goals — SpecialEducationTeacher only.

    PRD §3.3: required input fields are `domain`, `description`, and
    `objectives` (a non-empty list of objective records whose weights
    sum to exactly 1.00).
    """
    if objectives is None:
        objectives = [make_objective(weight=1.0)]
    payload: Dict[str, Any] = {
        "domain": domain,
        "description": description,
        "objectives": objectives,
    }
    payload.update(overrides)
    return payload


def close_goal_payload(*, disposition: str = "MET",
                       **overrides: Any) -> Dict[str, Any]:
    """POST .../goals/{id}/close.

    PRD §3.5: "a disposition of either MET or NOT_MET".
    """
    payload: Dict[str, Any] = {"disposition": disposition}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# GoalProgressReport — PRD §3.7
# ---------------------------------------------------------------------------
def create_progress_report_payload(
    *,
    reporting_period_index: int,
    objective_progress: List[Dict[str, Any]],
    narrative: str = TEST_DEFAULTS["PROGRESS_NARRATIVE"],
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../goals/{id}/progress-reports.

    PRD §3.7: required inputs are `reporting_period_index` (monotone
    integer >= 1), `objective_progress` (one entry per objective on
    the parent goal — no missing, no extra), and `narrative` (1..2000
    characters).
    """
    payload: Dict[str, Any] = {
        "reporting_period_index": reporting_period_index,
        "objective_progress": list(objective_progress),
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# RelatedService — PRD §3.3, §3.6
# ---------------------------------------------------------------------------
def create_related_service_payload(
    *,
    service_type: str = "OT",
    minutes_per_week: int = 60,
    provider_user_id: Optional[str] = None,
    location_setting: str = "PULL_OUT",
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../related-services — SpecialEducationTeacher only.

    PRD §3.3: required input fields are `service_type`,
    `minutes_per_week` (strictly positive integer), `provider_user_id`,
    `location_setting`.
    """
    payload: Dict[str, Any] = {
        "service_type": service_type,
        "minutes_per_week": minutes_per_week,
        "provider_user_id": (
            provider_user_id if provider_user_id is not None
            else "provider-001"
        ),
        "location_setting": location_setting,
    }
    payload.update(overrides)
    return payload


def activate_related_service_payload(
    *,
    consent_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PUT .../related-services/{id}/activate.

    PRD §3.6: "Activation accepts consent_id in the request body".
    """
    payload: Dict[str, Any] = {"consent_id": consent_id}
    payload.update(overrides)
    return payload


def resume_related_service_payload(
    *,
    consent_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """PUT .../related-services/{id}/resume.

    PRD §3.6: "A SUSPENDED service can be resumed back to ACTIVE by
    the RelatedServiceProvider by supplying a consent_id in the
    request body."
    """
    payload: Dict[str, Any] = {"consent_id": consent_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ServiceSession — PRD §3.6
# ---------------------------------------------------------------------------
def create_session_payload(
    *,
    scheduled_start: str,
    scheduled_end: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../sessions.

    PRD §3.6: required inputs are `scheduled_start` and `scheduled_end`
    (both ISO 8601 UTC datetimes; end strictly greater than start).
    """
    payload: Dict[str, Any] = {
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def deliver_session_payload(*, actual_minutes: int,
                            **overrides: Any) -> Dict[str, Any]:
    """POST .../sessions/{id}/deliver.

    PRD §3.6: required input is `actual_minutes` (non-negative integer
    at most equal to scheduled_minutes).
    """
    payload: Dict[str, Any] = {"actual_minutes": actual_minutes}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# TransitionPlan — PRD §3.3
# ---------------------------------------------------------------------------
def create_transition_plan_payload(
    *,
    post_secondary_goal: str = TEST_DEFAULTS["POST_SECONDARY_GOAL"],
    required_courses: Optional[List[Dict[str, Any]]] = None,
    outside_agency_referrals: Optional[List[Dict[str, Any]]] = None,
    parent_invitation_documented: bool = True,
    student_invitation_documented: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    """POST .../transition-plan.

    PRD §3.3: required input fields are `post_secondary_goal` (length
    10..1000 inclusive), `required_courses` (non-empty list of
    {course_code, projected_completion_term}),
    `outside_agency_referrals` (list, possibly empty),
    `parent_invitation_documented` (bool), and
    `student_invitation_documented` (bool).
    """
    if required_courses is None:
        required_courses = [
            {"course_code": "MATH-101",
             "projected_completion_term": "FALL_2026"},
        ]
    if outside_agency_referrals is None:
        outside_agency_referrals = []
    payload: Dict[str, Any] = {
        "post_secondary_goal": post_secondary_goal,
        "required_courses": required_courses,
        "outside_agency_referrals": outside_agency_referrals,
        "parent_invitation_documented": parent_invitation_documented,
        "student_invitation_documented": student_invitation_documented,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "iso_utc",
    "iso_now",
    "utcnow",
    "date_iso",
    "random_suffix",
    "make_objective",
    "create_district_payload",
    "clock_advance_payload",
    "create_student_payload",
    "create_evaluation_payload",
    "finalize_evaluation_payload",
    "create_consent_payload",
    "create_iep_payload",
    "create_goal_payload",
    "close_goal_payload",
    "create_progress_report_payload",
    "create_related_service_payload",
    "activate_related_service_payload",
    "resume_related_service_payload",
    "create_session_payload",
    "deliver_session_payload",
    "create_transition_plan_payload",
]
