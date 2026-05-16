"""Entity assertions and domain invariant checkers.

These check the response shape and domain invariants required by the PRD
contract. They are intentionally generous about server-minted optional
fields (e.g., null-valued computed timestamps before transition): a
test that wants to pin a specific computed value asserts it directly.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields predicates — PRD §2.4
# ---------------------------------------------------------------------------
def _assert_id_and_created_at(data: Dict[str, Any]) -> None:
    assert "id" in data, f"missing id; got keys: {list(data)}"
    assert is_valid_uuid(data["id"]), (
        f"id must be a UUID with no type prefix, got {data['id']!r}"
    )
    assert "created_at" in data, "missing created_at"
    assert is_iso8601_timestamp(data["created_at"]), (
        f"created_at must be ISO 8601, got {data['created_at']!r}"
    )


def _assert_updated_at_and_version(data: Dict[str, Any]) -> None:
    """PRD §2.4 four common properties: id, created_at, updated_at,
    version. Asserted for the eight entities that carry version (i.e.,
    NOT ParentalConsent or GoalProgressReport, which PRD §2.4 declares
    as append-only event records)."""
    assert "updated_at" in data, "missing updated_at"
    assert is_iso8601_timestamp(data["updated_at"]), (
        f"updated_at must be ISO 8601, got {data['updated_at']!r}"
    )
    assert "version" in data, "missing version"
    assert isinstance(data["version"], int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


# ---------------------------------------------------------------------------
# District
# ---------------------------------------------------------------------------
def assert_district(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert isinstance(data.get("name"), str) and data["name"]
    sc = data.get("state_code")
    assert isinstance(sc, str) and len(sc) == 2 and sc.isupper(), (
        f"state_code must be 2 uppercase letters, got {sc!r}"
    )
    cd = data.get("current_date")
    assert isinstance(cd, str) and is_iso8601_timestamp(cd), (
        f"current_date must be ISO 8601, got {cd!r}"
    )


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------
VALID_TRIENNIAL_STATUSES = {
    "NOT_APPLICABLE", "ON_TRACK", "DUE_SOON", "OVERDUE",
}
VALID_LRE_CLASSIFICATIONS = {
    "NOT_APPLICABLE", "LRE_A", "LRE_B", "LRE_C",
}


def assert_student(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("district_id", ""))
    assert isinstance(data.get("external_student_number"), str)
    assert isinstance(data.get("date_of_birth"), str)
    assert isinstance(data.get("parent_user_id"), str)
    assert data.get("triennial_status") in VALID_TRIENNIAL_STATUSES, (
        f"triennial_status must be one of {VALID_TRIENNIAL_STATUSES}, "
        f"got {data.get('triennial_status')!r}"
    )
    assert data.get("lre_classification") in VALID_LRE_CLASSIFICATIONS, (
        f"lre_classification must be one of {VALID_LRE_CLASSIFICATIONS},"
        f" got {data.get('lre_classification')!r}"
    )
    assert isinstance(data.get("requires_transition_plan"), bool)


# ---------------------------------------------------------------------------
# EligibilityEvaluation
# ---------------------------------------------------------------------------
VALID_EVAL_STATUSES = {
    "REQUESTED", "CONSENT_PENDING", "IN_PROGRESS",
    "ELIGIBLE", "INELIGIBLE",
}
VALID_EVAL_TYPES = {"INITIAL", "TRIENNIAL", "INTERIM"}


def assert_evaluation(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("district_id", ""))
    assert data.get("evaluation_type") in VALID_EVAL_TYPES
    assert isinstance(data.get("is_reevaluation"), bool)
    assert data.get("status") in VALID_EVAL_STATUSES
    assert isinstance(data.get("evaluator_user_id"), str) and (
        data["evaluator_user_id"]
    )


# ---------------------------------------------------------------------------
# ParentalConsent — append-only, ONLY id + created_at per PRD §2.4
# ---------------------------------------------------------------------------
VALID_CONSENT_STATUSES = {"PENDING", "APPROVED", "REJECTED", "WITHDRAWN"}
VALID_CONSENT_SCOPES = {
    "EVALUATION", "IEP_IMPLEMENTATION", "RELATED_SERVICE",
    "PLACEMENT_CHANGE",
}
VALID_CONSENT_TARGET_TYPES = {
    "EligibilityEvaluation", "IEP", "RelatedService", "Student",
}


def assert_parental_consent(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: ParentalConsent does NOT carry updated_at or version.
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("district_id", ""))
    assert data.get("scope") in VALID_CONSENT_SCOPES
    assert data.get("target_resource_type") in VALID_CONSENT_TARGET_TYPES
    assert isinstance(data.get("target_resource_id"), str) and (
        data["target_resource_id"]
    )
    assert data.get("status") in VALID_CONSENT_STATUSES


# ---------------------------------------------------------------------------
# IEP
# ---------------------------------------------------------------------------
VALID_IEP_STATUSES = {
    "DRAFT", "ACTIVE", "AMENDMENT_PENDING",
    "EXPIRED", "REVOKED", "SUPERSEDED",
}


def assert_iep(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("student_id", ""))
    assert is_valid_uuid(data.get("district_id", ""))
    assert isinstance(data.get("meeting_held_at"), str)
    assert isinstance(data.get("effective_start_date"), str)
    assert isinstance(data.get("scheduled_review_date"), str)
    assert isinstance(data.get("total_instructional_minutes_per_week"),
                      int)
    assert isinstance(data.get("total_school_day_minutes_per_week"), int)
    assert isinstance(data.get("special_education_minutes_per_week"), int)
    assert data["special_education_minutes_per_week"] >= 0
    # PRD §2.10: both percentages are floats rounded to 2 dp.
    for f in ("lre_percentage_instructional",
              "lre_percentage_school_day"):
        v = data.get(f)
        assert isinstance(v, (int, float)), (
            f"{f} must be numeric, got {type(v).__name__}"
        )
        assert v >= 0
    assert data.get("status") in VALID_IEP_STATUSES
    assert isinstance(data.get("requires_transition_plan"), bool)


def assert_lre_relationship(data: Dict[str, Any]) -> None:
    """PRD §3.8: school-day-basis variant is less than or equal to
    instructional-basis variant for any identical numerator.

    "Because total_school_day_minutes_per_week includes
    non-instructional time such as lunch and recess, it is greater
    than or equal to total_instructional_minutes_per_week, and so
    lre_percentage_school_day is less than or equal to
    lre_percentage_instructional for any identical numerator."
    """
    assert (
        data["lre_percentage_school_day"]
        <= data["lre_percentage_instructional"]
    ), (
        f"lre_percentage_school_day ({data['lre_percentage_school_day']})"
        f" must be <= lre_percentage_instructional "
        f"({data['lre_percentage_instructional']})"
    )


# ---------------------------------------------------------------------------
# IEPGoal
# ---------------------------------------------------------------------------
VALID_GOAL_STATUSES = {
    "PROPOSED", "ACTIVE", "MET", "NOT_MET", "DISCONTINUED",
}
VALID_GOAL_DOMAINS = {
    "ACADEMIC", "COMMUNICATION", "MOTOR",
    "BEHAVIORAL", "FUNCTIONAL", "TRANSITION",
}
VALID_MASTERY_TIERS = {
    "INSUFFICIENT_PROGRESS", "PROGRESSING", "MASTERED",
}


def assert_iep_goal(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("iep_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert data.get("domain") in VALID_GOAL_DOMAINS
    assert isinstance(data.get("description"), str) and data["description"]
    objectives = data.get("objectives")
    assert isinstance(objectives, list) and len(objectives) >= 1, (
        "objectives must be a non-empty list"
    )
    for obj in objectives:
        assert isinstance(obj.get("objective_id"), str) and (
            obj["objective_id"]
        )
        w = obj.get("weight")
        assert isinstance(w, (int, float))
        assert 0 < w <= 1, f"weight must be in (0, 1], got {w}"
        p = obj.get("latest_progress_percent")
        assert isinstance(p, int) and 0 <= p <= 100, (
            f"latest_progress_percent must be int in [0, 100], got {p}"
        )
    # mastery_score / mastery_tier may be 0 / INSUFFICIENT_PROGRESS by
    # default; ensure they are present and well-typed.
    ms = data.get("mastery_score")
    assert isinstance(ms, (int, float)) and ms >= 0
    assert data.get("mastery_tier") in VALID_MASTERY_TIERS
    assert data.get("status") in VALID_GOAL_STATUSES


def assert_objective_weights_sum_to_one(objectives: list) -> None:
    """PRD §3.3: "the sum of all objective weight values on a goal
    must equal exactly 1.00 when rounded half-up to two decimal
    places".
    """
    total = round(sum(o["weight"] for o in objectives), 2)
    assert total == 1.00, (
        f"objective weights must sum to 1.00, got {total}"
    )


# ---------------------------------------------------------------------------
# GoalProgressReport — append-only, ONLY id + created_at per PRD §2.4
# ---------------------------------------------------------------------------
def assert_progress_report(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    # PRD §2.4: GoalProgressReport does NOT carry updated_at or version.
    assert is_valid_uuid(data.get("iep_goal_id", ""))
    assert is_valid_uuid(data.get("iep_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    rpi = data.get("reporting_period_index")
    assert isinstance(rpi, int) and rpi >= 1, (
        f"reporting_period_index must be a positive integer, got {rpi}"
    )
    assert isinstance(data.get("reported_by_user_id"), str) and (
        data["reported_by_user_id"]
    )
    op = data.get("objective_progress")
    assert isinstance(op, list) and len(op) >= 1
    for row in op:
        assert isinstance(row.get("objective_id"), str)
        p = row.get("progress_percent")
        assert isinstance(p, int) and 0 <= p <= 100
    n = data.get("narrative")
    assert isinstance(n, str) and 1 <= len(n) <= 2000


# ---------------------------------------------------------------------------
# RelatedService
# ---------------------------------------------------------------------------
VALID_SERVICE_STATUSES = {"PROPOSED", "ACTIVE", "SUSPENDED", "COMPLETED"}
VALID_SERVICE_TYPES = {
    "OT", "PT", "SPEECH", "COUNSELING", "ORIENTATION_MOBILITY",
}
VALID_LOCATION_SETTINGS = {"PULL_OUT", "PUSH_IN", "COMMUNITY"}


def assert_related_service(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("iep_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    assert data.get("service_type") in VALID_SERVICE_TYPES
    mpw = data.get("minutes_per_week")
    assert isinstance(mpw, int) and mpw > 0, (
        f"minutes_per_week must be a positive integer, got {mpw}"
    )
    assert isinstance(data.get("provider_user_id"), str)
    assert data.get("location_setting") in VALID_LOCATION_SETTINGS
    assert data.get("status") in VALID_SERVICE_STATUSES
    for f in ("total_prescribed_minutes_to_date",
              "total_delivered_minutes", "total_cancelled_minutes",
              "compensatory_minutes_owed"):
        v = data.get(f)
        assert isinstance(v, int) and v >= 0, (
            f"{f} must be non-negative int, got {v!r}"
        )
    up = data.get("utilization_percent")
    assert isinstance(up, (int, float)) and up >= 0


# ---------------------------------------------------------------------------
# ServiceSession
# ---------------------------------------------------------------------------
VALID_SESSION_STATUSES = {"SCHEDULED", "DELIVERED", "CANCELLED"}


def assert_service_session(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("related_service_id", ""))
    assert isinstance(data.get("scheduled_start"), str)
    assert isinstance(data.get("scheduled_end"), str)
    sm = data.get("scheduled_minutes")
    assert isinstance(sm, int) and sm >= 0
    assert data.get("status") in VALID_SESSION_STATUSES


# ---------------------------------------------------------------------------
# TransitionPlan
# ---------------------------------------------------------------------------
VALID_TRANSITION_PLAN_STATUSES = {
    "DRAFT", "FINALIZED", "ACTIVE", "SUPERSEDED",
}


def assert_transition_plan(data: Dict[str, Any]) -> None:
    _assert_id_and_created_at(data)
    _assert_updated_at_and_version(data)
    assert is_valid_uuid(data.get("iep_id", ""))
    assert is_valid_uuid(data.get("student_id", ""))
    psg = data.get("post_secondary_goal")
    assert isinstance(psg, str) and 10 <= len(psg) <= 1000
    rc = data.get("required_courses")
    assert isinstance(rc, list) and len(rc) >= 1
    oar = data.get("outside_agency_referrals")
    assert isinstance(oar, list)
    assert isinstance(data.get("parent_invitation_documented"), bool)
    assert isinstance(data.get("student_invitation_documented"), bool)
    assert data.get("status") in VALID_TRANSITION_PLAN_STATUSES


# ---------------------------------------------------------------------------
# Version-bump invariant — PRD §2.4
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(after: Dict[str, Any],
                                      before_version: int) -> None:
    """PRD §2.4: "version ... begins at 1 on creation and increases by
    exactly one on every successful mutation, including system-driven
    mutations."""
    assert after["version"] == before_version + 1, (
        f"expected version {before_version + 1}, got {after['version']}"
    )


__all__ = [
    "assert_district",
    "assert_student",
    "assert_evaluation",
    "assert_parental_consent",
    "assert_iep",
    "assert_lre_relationship",
    "assert_iep_goal",
    "assert_objective_weights_sum_to_one",
    "assert_progress_report",
    "assert_related_service",
    "assert_service_session",
    "assert_transition_plan",
    "assert_version_incremented_by_one",
    "VALID_TRIENNIAL_STATUSES",
    "VALID_LRE_CLASSIFICATIONS",
    "VALID_EVAL_STATUSES",
    "VALID_EVAL_TYPES",
    "VALID_CONSENT_STATUSES",
    "VALID_CONSENT_SCOPES",
    "VALID_IEP_STATUSES",
    "VALID_GOAL_STATUSES",
    "VALID_GOAL_DOMAINS",
    "VALID_MASTERY_TIERS",
    "VALID_SERVICE_STATUSES",
    "VALID_SERVICE_TYPES",
    "VALID_LOCATION_SETTINGS",
    "VALID_SESSION_STATUSES",
    "VALID_TRANSITION_PLAN_STATUSES",
]
