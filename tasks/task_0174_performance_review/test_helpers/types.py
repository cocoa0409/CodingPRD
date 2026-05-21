"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror PRD §3 entity descriptions verbatim.
- Entities with id+created_at+updated_at+version (per PRD §2.4): Employee,
  Cycle, ReviewCase, Goal, CalibrationSession, PIPCase, CompPlan.
- Append-only ledgers (id + created_at only, no updated_at, no version):
  FeedbackRequest, AuditEvent.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    ADMIN = "Admin"
    HRBP = "HRBP"
    MANAGER = "Manager"
    REVIEWER = "Reviewer"
    APPROVER = "Approver"


# ===========================================================================
# Status enums — PRD §3
# ===========================================================================
class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_PIP = "ON_PIP"
    TERMINATED = "TERMINATED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    IN_CALIBRATION = "IN_CALIBRATION"
    COMP_PLANNING = "COMP_PLANNING"
    CLOSED = "CLOSED"


class CycleCadence(str, Enum):
    ANNUAL = "ANNUAL"
    SEMI_ANNUAL = "SEMI_ANNUAL"


class ReviewCaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    LOCKED = "LOCKED"
    FINALIZED = "FINALIZED"


class Rating(str, Enum):
    """The five rating buckets used by ReviewCase.manager_rating,
    ReviewCase.final_rating, CalibrationSession.proposed_ratings, and
    Cycle.bell_curve_target. PRD §3.3, §3.5, §3.7."""
    OUTSTANDING = "OUTSTANDING"
    EXCEEDS = "EXCEEDS"
    MEETS = "MEETS"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    UNSATISFACTORY = "UNSATISFACTORY"


class FeedbackRequestStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    DECLINED = "DECLINED"


class FeedbackRelation(str, Enum):
    PEER = "PEER"
    UPWARD = "UPWARD"
    DOWNWARD = "DOWNWARD"
    CROSS_FUNCTIONAL = "CROSS_FUNCTIONAL"


class CalibrationSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    COMMITTED = "COMMITTED"
    ABANDONED = "ABANDONED"


class PIPCaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WITHDRAWN = "WITHDRAWN"


class CompPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ===========================================================================
# Entity TypedDicts — PRD §2.4 (common fields) and §3 (per-entity).
# ===========================================================================
class Employee(TypedDict, total=False):
    """PRD §3.1 — common_fields true (id, created_at, updated_at, version)."""
    id: str
    full_name: str
    email: str
    department: str
    job_level: int
    manager_employee_id: Optional[str]
    base_salary_cents: int
    equity_units_outstanding: int
    status: str
    hire_date: str
    created_at: str
    updated_at: str
    version: int


class Cycle(TypedDict, total=False):
    """PRD §3.2 — common_fields true."""
    id: str
    name: str
    cadence: str
    status: str
    review_window_start: str
    review_window_end: str
    bell_curve_target: Dict[str, int]
    merit_budget_cents: int
    equity_refresh_pool_units: int
    merit_budget_consumed_cents: int
    equity_pool_consumed_units: int
    created_at: str
    updated_at: str
    version: int


class ReviewCase(TypedDict, total=False):
    """PRD §3.3 — common_fields true."""
    id: str
    cycle_id: str
    subject_employee_id: str
    manager_employee_id: str
    status: str
    manager_rating: Optional[str]
    final_rating: Optional[str]
    weighted_goal_score: float
    peer_feedback_count: int
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class Goal(TypedDict, total=False):
    """PRD §3.3 — common_fields true."""
    id: str
    review_case_id: str
    title: str
    weight: int
    self_score: Optional[int]
    manager_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FeedbackRequest(TypedDict, total=False):
    """PRD §3.4 — common_fields FALSE (append-only).
    Carries ONLY id + created_at — no updated_at, no version."""
    id: str
    review_case_id: str
    reviewer_employee_id: str
    relation: str
    status: str
    narrative: Optional[str]
    submitted_at: Optional[str]
    created_at: str


class CalibrationSession(TypedDict, total=False):
    """PRD §3.5 — common_fields true."""
    id: str
    cycle_id: str
    department: str
    facilitator_employee_id: str
    status: str
    proposed_ratings: List[Dict[str, str]]
    bell_curve_distribution: Dict[str, int]
    committed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PIPCase(TypedDict, total=False):
    """PRD §3.6 — common_fields true."""
    id: str
    cycle_id: str
    subject_employee_id: str
    triggering_review_case_id: str
    duration_days: int
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CompPlan(TypedDict, total=False):
    """PRD §3.7 — common_fields true."""
    id: str
    cycle_id: str
    subject_employee_id: str
    pinned_review_case_id: str
    pinned_review_case_version: int
    pinned_base_salary_cents: int
    merit_increase_cents: int
    promotion_to_level: Optional[int]
    equity_refresh_units: int
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict, total=False):
    """PRD §2.12 — common_fields FALSE (append-only)."""
    id: str
    actor_role: str
    actor_user_id: str
    entity_type: str
    entity_id: str
    action: str
    payload_hash: str
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "EmployeeStatus",
    "CycleStatus",
    "CycleCadence",
    "ReviewCaseStatus",
    "Rating",
    "FeedbackRequestStatus",
    "FeedbackRelation",
    "CalibrationSessionStatus",
    "PIPCaseStatus",
    "CompPlanStatus",
    "Employee",
    "Cycle",
    "ReviewCase",
    "Goal",
    "FeedbackRequest",
    "CalibrationSession",
    "PIPCase",
    "CompPlan",
    "AuditEvent",
]
