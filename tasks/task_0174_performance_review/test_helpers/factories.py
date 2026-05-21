"""Payload factories — one per entity, input fields only.

Each factory mirrors the PRD-declared input fields for a single POST or
PATCH body. Required fields receive sensible defaults; callers pass
overrides to exercise specific test scenarios. Computed fields (e.g.
status, weighted_goal_score, merit_increase_cents) are never emitted.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from .constants import TEST_DEFAULTS


# ---------------------------------------------------------------------------
# Helpers for uniqueness across tests sharing process state.
# ---------------------------------------------------------------------------
def _fresh_suffix() -> str:
    """Short token used by factories to keep emails / names unique."""
    return uuid.uuid4().hex[:10]


# ---------------------------------------------------------------------------
# Employee — PRD §3.1
# ---------------------------------------------------------------------------
def create_employee_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /employees (PRD §3.1).

    Required input fields per PRD §3.1: full_name, email, department,
    job_level, base_salary_cents, hire_date. Optional:
    manager_employee_id, equity_units_outstanding.
    """
    suffix = _fresh_suffix()
    defaults: Dict[str, Any] = {
        "full_name": f"Test Employee {suffix}",
        "email": f"emp-{suffix}@example.test",
        "department": TEST_DEFAULTS["DEPARTMENT"],
        "job_level": TEST_DEFAULTS["JOB_LEVEL"],
        "base_salary_cents": TEST_DEFAULTS["BASE_SALARY_CENTS"],
        "hire_date": TEST_DEFAULTS["HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def update_employee_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for PATCH /employees/{id} (PRD §3.1). All fields optional."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Cycle — PRD §3.2
# ---------------------------------------------------------------------------
def create_cycle_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for POST /cycles (PRD §3.2). All seven inputs required.

    PRD §3.2: review_window_end must be strictly after start; bell_curve_target
    must have exactly the five rating buckets with integer percents summing
    to 100; merit_budget_cents >= 0; equity_refresh_pool_units >= 0.
    """
    suffix = _fresh_suffix()
    defaults: Dict[str, Any] = {
        "name": f"Cycle {suffix}",
        "cadence": TEST_DEFAULTS["CADENCE"],
        "review_window_start": TEST_DEFAULTS["REVIEW_WINDOW_START"],
        "review_window_end": TEST_DEFAULTS["REVIEW_WINDOW_END"],
        "bell_curve_target": dict(TEST_DEFAULTS["BELL_CURVE_TARGET_EVEN"]),
        "merit_budget_cents": TEST_DEFAULTS["MERIT_BUDGET_CENTS"],
        "equity_refresh_pool_units": TEST_DEFAULTS["EQUITY_REFRESH_POOL_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def update_cycle_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for PATCH /cycles/{id} (PRD §3.2). All fields optional."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# ReviewCase — PRD §3.3
# ---------------------------------------------------------------------------
def create_review_case_payload(subject_employee_id: str,
                               **overrides: Any) -> Dict[str, Any]:
    """Body for POST /cycles/{cid}/review-cases (PRD §3.3).

    "The creator supplies only `subject_employee_id`" — manager and cycle
    are derived server-side.
    """
    defaults: Dict[str, Any] = {
        "subject_employee_id": subject_employee_id,
    }
    defaults.update(overrides)
    return defaults


def update_review_case_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for PATCH /cycles/{cid}/review-cases/{rid} (PRD §3.3).

    Per PRD §4 endpoint table this edits ReviewCase fields
    (manager_rating); the optional `version` is accepted for OCC.
    """
    return dict(overrides)


# ---------------------------------------------------------------------------
# Goal — PRD §3.3
# ---------------------------------------------------------------------------
def create_goal_payload(weight: int, **overrides: Any) -> Dict[str, Any]:
    """Body for POST /cycles/{cid}/review-cases/{rid}/goals (PRD §3.3).

    Required: title, weight. Optional: self_score, manager_score.
    """
    defaults: Dict[str, Any] = {
        "title": f"Goal {_fresh_suffix()}",
        "weight": weight,
    }
    defaults.update(overrides)
    return defaults


def update_goal_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for PATCH /goals/{id} (PRD §3.3)."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# FeedbackRequest — PRD §3.4
# ---------------------------------------------------------------------------
def create_feedback_request_payload(reviewer_employee_id: str,
                                    relation: str = "PEER",
                                    **overrides: Any) -> Dict[str, Any]:
    """Body for POST .../feedback-requests (PRD §3.4)."""
    defaults: Dict[str, Any] = {
        "reviewer_employee_id": reviewer_employee_id,
        "relation": relation,
    }
    defaults.update(overrides)
    return defaults


def submit_feedback_request_payload(narrative: Optional[str] = None,
                                    **overrides: Any) -> Dict[str, Any]:
    """Body for POST .../feedback-requests/{id}/submit (PRD §3.4).

    Per PRD §3.4 the narrative must be 50..5000 characters at submit.
    """
    text = narrative if narrative is not None else (
        "Standard feedback narrative content used in tests; "
        "exceeds the 50-character minimum required by PRD §3.4."
    )
    defaults: Dict[str, Any] = {"narrative": text}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# CalibrationSession — PRD §3.5
# ---------------------------------------------------------------------------
def create_calibration_session_payload(department: str,
                                       facilitator_employee_id: str,
                                       **overrides: Any) -> Dict[str, Any]:
    """Body for POST .../calibration-sessions (PRD §3.5)."""
    defaults: Dict[str, Any] = {
        "department": department,
        "facilitator_employee_id": facilitator_employee_id,
    }
    defaults.update(overrides)
    return defaults


def proposals_payload(pairs: List[Dict[str, str]],
                      **overrides: Any) -> Dict[str, Any]:
    """Body for PATCH .../proposals (PRD §3.5).

    `pairs` is a list of {"review_case_id": ..., "proposed_rating": ...}
    objects. PRD §3.5: "Each call replaces `proposed_ratings` in its
    entirety with an ordered list of `{review_case_id, proposed_rating}`
    pairs".
    """
    defaults: Dict[str, Any] = {"proposed_ratings": pairs}
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# CompPlan — PRD §3.7
# ---------------------------------------------------------------------------
def create_comp_plan_payload(subject_employee_id: str,
                             promotion_to_level: Optional[int] = None,
                             **overrides: Any) -> Dict[str, Any]:
    """Body for POST /cycles/{cid}/comp-plans (PRD §3.7).

    Per PRD §3.7 the creator supplies subject_employee_id and an optional
    promotion_to_level; every pinned snapshot field is derived server-side.
    """
    defaults: Dict[str, Any] = {"subject_employee_id": subject_employee_id}
    if promotion_to_level is not None:
        defaults["promotion_to_level"] = promotion_to_level
    defaults.update(overrides)
    return defaults


def update_comp_plan_payload(**overrides: Any) -> Dict[str, Any]:
    """Body for PATCH /comp-plans/{id} (PRD §3.7). All fields optional."""
    return dict(overrides)


# ---------------------------------------------------------------------------
# Clock — PRD §2.13, §3.8
# ---------------------------------------------------------------------------
def advance_clock_payload(to_datetime: str) -> Dict[str, Any]:
    """Body for POST /_clock/advance (PRD §2.13)."""
    return {"to_datetime": to_datetime}


__all__ = [
    "create_employee_payload",
    "update_employee_payload",
    "create_cycle_payload",
    "update_cycle_payload",
    "create_review_case_payload",
    "update_review_case_payload",
    "create_goal_payload",
    "update_goal_payload",
    "create_feedback_request_payload",
    "submit_feedback_request_payload",
    "create_calibration_session_payload",
    "proposals_payload",
    "create_comp_plan_payload",
    "update_comp_plan_payload",
    "advance_clock_payload",
]
