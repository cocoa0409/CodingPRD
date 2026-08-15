"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD resource narratives (§2.4, §3.1-§3.7).
AdvancementDecision and RetentionSnapshot are append-only / immutable and
carry only id + created_at from the common set (no updated_at, no version).
"""
from enum import Enum
from typing import Dict, Optional, TypedDict


class LadderLevel(str, Enum):
    CN_I = "CN_I"
    CN_II = "CN_II"
    CN_III = "CN_III"
    CN_IV = "CN_IV"


class DifferentialStatus(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CertificationTrack(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    SPECIALTY = "SPECIALTY"
    ADVANCED = "ADVANCED"


class ParticipationEventKind(str, Enum):
    COMMITTEE_SEAT = "COMMITTEE_SEAT"
    QI_PROJECT = "QI_PROJECT"
    PEER_EDUCATION = "PEER_EDUCATION"
    EBP_RESEARCH = "EBP_RESEARCH"
    PRECEPTORSHIP = "PRECEPTORSHIP"


class ParticipationEventStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class CertificationStatus(str, Enum):
    CURRENT = "CURRENT"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"


class BonusStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    RETURNED_FOR_REVISION = "RETURNED_FOR_REVISION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class AssignmentStatus(str, Enum):
    PENDING = "PENDING"
    SCORED = "SCORED"
    RECUSED = "RECUSED"
    EXPIRED = "EXPIRED"


class DecisionOutcome(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class ReviewOutcome(str, Enum):
    OPEN = "OPEN"
    SUSTAIN = "SUSTAIN"
    DEMOTE = "DEMOTE"
    LAPSE = "LAPSE"


class ForecastVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class UserRole(str, Enum):
    NURSE = "Nurse"
    PROGRAM_ADMIN = "ProgramAdmin"
    PAYROLL_OFFICER = "PayrollOfficer"
    RETENTION_ANALYST = "RetentionAnalyst"


class Nurse(TypedDict, total=False):
    id: str
    employee_code: str
    full_name: str
    hire_date: str
    home_unit: str
    current_level: str
    differential_status: str
    differential_activated_at: Optional[str]
    tenure_years: float
    retention_risk_score: float
    created_at: str
    updated_at: str
    version: int


class LadderCriterion(TypedDict, total=False):
    id: str
    target_level: str
    min_portfolio_score: int
    min_participation_points: int
    required_certification_track: str
    differential_monthly_cents: int
    effective_from: str
    effective_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParticipationEvent(TypedDict, total=False):
    id: str
    nurse_id: str
    event_kind: str
    points: int
    occurred_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    nurse_id: str
    track: str
    certifying_body: str
    exam_fee_cents: int
    obtained_on: str
    expires_on: str
    status: str
    renewal_of_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict, total=False):
    id: str
    certification_id: str
    claimed_amount_cents: int
    approved_amount_cents: int
    status: str
    denial_reason: Optional[str]
    fiscal_year: int
    created_at: str
    updated_at: str
    version: int


class CertificationBonus(TypedDict, total=False):
    id: str
    certification_id: str
    bonus_amount_cents: int
    status: str
    clawback_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    nurse_id: str
    target_level: str
    portfolio_narrative: str
    criterion_id: Optional[str]
    status: str
    submitted_at: Optional[str]
    review_cycle: int
    aggregate_score: Optional[int]
    participation_snapshot_points: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DimensionScores(TypedDict):
    leadership: int
    clinical_expertise: int
    professional_development: int
    outcomes: int


class ReviewAssignment(TypedDict, total=False):
    id: str
    application_id: str
    reviewer_nurse_id: str
    dimension_scores: Optional[DimensionScores]
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdvancementDecision(TypedDict, total=False):
    # Append-only audit row: id + created_at only from the common set
    # (no updated_at, no version).
    id: str
    created_at: str
    application_id: str
    decided_by_admin_id: str
    outcome: str
    criterion_version_snapshot: int
    decided_at: str


class AnniversaryReview(TypedDict, total=False):
    id: str
    nurse_id: str
    review_year: int
    maintenance_score: Optional[int]
    outcome: str
    resolution_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BudgetLine(TypedDict, total=False):
    id: str
    unit: str
    fiscal_year: int
    allocated_cents: int
    committed_cents: int
    forecast_cents: int
    forecast_variant: str
    created_at: str
    updated_at: str
    version: int


class RetentionSnapshot(TypedDict, total=False):
    # Immutable point-in-time capture: id + created_at only from the common set.
    id: str
    created_at: str
    captured_at: str
    unit: str
    headcount_by_level: Dict[str, int]
    avg_retention_risk_score: float
    demotion_rate: float
