"""Domain types: entity TypedDicts, status enums, role enum.

Field names and lifecycle states are taken verbatim from the PRD
(Performance Review & Compensation Planning API).
"""
from enum import Enum
from typing import TypedDict, Optional, Dict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    HR_ADMIN = "HrAdmin"
    MANAGER = "Manager"
    EMPLOYEE = "Employee"
    HRBP_PARTNER = "HrbpPartner"
    COMP_APPROVER = "CompApprover"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ReviewCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CALIBRATION = "CALIBRATION"
    COMP_PLANNING = "COMP_PLANNING"
    CLOSED = "CLOSED"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SELF_REVIEW = "SELF_REVIEW"
    MANAGER_REVIEW = "MANAGER_REVIEW"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    CALIBRATED = "CALIBRATED"
    FINALIZED = "FINALIZED"


class GoalStatus(str, Enum):
    OPEN = "OPEN"
    SCORED = "SCORED"


class FeedbackStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    DECLINED = "DECLINED"


class CalibrationSessionStatus(str, Enum):
    OPEN = "OPEN"
    BALANCED = "BALANCED"
    FINALIZED = "FINALIZED"


class CompPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PipCaseStatus(str, Enum):
    OPEN = "OPEN"
    ACTIVE = "ACTIVE"
    CURED = "CURED"
    FAILED = "FAILED"


class Cadence(str, Enum):
    ANNUAL = "ANNUAL"
    SEMI_ANNUAL = "SEMI_ANNUAL"


class PlanType(str, Enum):
    MERIT_ONLY = "MERIT_ONLY"
    MERIT_AND_PROMO = "MERIT_AND_PROMO"


class FeedbackRelationship(str, Enum):
    PEER = "PEER"
    REPORT = "REPORT"
    MANAGER = "MANAGER"
    SELF = "SELF"


# --------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id + created_at + updated_at + version
# common_fields: false -> id + created_at only (RatingBand)
# --------------------------------------------------------------------------
class ReviewCycle(TypedDict):
    id: str
    name: str
    cadence: str
    merit_budget_pct: float
    equity_refresh_pool: float
    status: str
    bell_curve_target: Dict[str, float]
    distribution_tolerance: float
    merit_committed_total: float
    equity_committed_total: float
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict):
    id: str
    cycle_id: str
    employee_id: str
    reviewer_id: str
    base_salary: float
    self_rating: Optional[str]
    manager_rating: Optional[str]
    final_rating: Optional[str]
    status: str
    composite_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    full_name: str
    manager_id: Optional[str]
    department: str
    hire_date: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Goal(TypedDict):
    id: str
    review_id: str
    title: str
    weight: float
    attainment_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeedbackRequest(TypedDict):
    id: str
    review_id: str
    rater_id: str
    relationship: str
    score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class CalibrationSession(TypedDict):
    id: str
    cycle_id: str
    department: str
    facilitator_id: str
    status: str
    bell_curve_actual: Optional[Dict[str, float]]
    review_count: int
    created_at: str
    updated_at: str
    version: int


class CompPlan(TypedDict):
    id: str
    cycle_id: str
    review_id: str
    plan_type: str
    merit_pct: float
    merit_amount: float
    promo_band_jump: int
    equity_refresh_units: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PipCase(TypedDict):
    id: str
    review_id: str
    employee_id: str
    duration_days: Optional[int]
    target_score: Optional[float]
    outcome_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only band definition, NO updated_at / version
class RatingBand(TypedDict):
    id: str
    cycle_id: str
    label: str
    min_score: float
    max_score: float
    merit_pct: float
    pip_eligible: bool
    created_at: str
