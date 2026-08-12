"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource descriptions (section 3) and endpoint table
(section 4). Every persisted resource carries the full common-field set
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    BANK_ADMIN = "BankAdmin"
    LENDING_DATA_OPS = "LendingDataOps"
    LOAN_OFFICER = "LoanOfficer"
    FAIR_LENDING_ANALYST = "FairLendingAnalyst"
    FAIR_LENDING_OFFICER = "FairLendingOfficer"
    COMPLIANCE_DIRECTOR = "ComplianceDirector"
    REMEDIATION_SPECIALIST = "RemediationSpecialist"


# ---------------------------------------------------------------------------
# Status / enum value sets
# ---------------------------------------------------------------------------

class BranchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class LoanOfficerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MonitoringTier(str, Enum):
    GREEN = "GREEN"
    WATCH = "WATCH"
    RED = "RED"


class ProductType(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    FHA = "FHA"
    VA = "VA"


class ApplicantGroup(str, Enum):
    PROTECTED_1 = "PROTECTED_1"
    PROTECTED_2 = "PROTECTED_2"
    CONTROL = "CONTROL"


class ApplicationOutcome(str, Enum):
    ORIGINATED = "ORIGINATED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    APPROVED_NOT_ACCEPTED = "APPROVED_NOT_ACCEPTED"


class ApplicationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    EXCLUDED = "EXCLUDED"


class HasException(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"


class ExceptionKind(str, Enum):
    RATE_ABOVE_CAP = "RATE_ABOVE_CAP"
    RATE_BELOW_FLOOR = "RATE_BELOW_FLOOR"
    FEE_WAIVER = "FEE_WAIVER"


class PricingExceptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ESCALATED = "ESCALATED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class OverrideStatus(str, Enum):
    RECORDED = "RECORDED"
    CONFIRMED = "CONFIRMED"
    REVERSED = "REVERSED"


class ProhibitedBasis(str, Enum):
    RACE = "RACE"
    ETHNICITY = "ETHNICITY"
    SEX = "SEX"
    AGE = "AGE"


class AnalysisRunStatus(str, Enum):
    DRAFT = "DRAFT"
    DATA_LOCKED = "DATA_LOCKED"
    COMPUTED = "COMPUTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    FINALIZED = "FINALIZED"
    ARCHIVED = "ARCHIVED"


class AdverseClassification(str, Enum):
    NONE = "NONE"
    MARGINAL = "MARGINAL"
    ADVERSE = "ADVERSE"


class FindingKind(str, Enum):
    DENIAL_DISPARITY = "DENIAL_DISPARITY"
    PRICING_DISPARITY = "PRICING_DISPARITY"
    PENETRATION_SHORTFALL = "PENETRATION_SHORTFALL"
    OVERRIDE_ASYMMETRY = "OVERRIDE_ASYMMETRY"
    MANUAL = "MANUAL"


class FindingSource(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class FindingStatus(str, Enum):
    FLAGGED = "FLAGGED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    REFUTED = "REFUTED"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class ReviewOutcome(str, Enum):
    COMPARABLE_TREATMENT = "COMPARABLE_TREATMENT"
    DIFFERENTIAL_TREATMENT = "DIFFERENTIAL_TREATMENT"


class MatchedPairReviewStatus(str, Enum):
    PENDING = "PENDING"
    INITIAL_REVIEWED = "INITIAL_REVIEWED"
    DISPUTED = "DISPUTED"
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"


class CapStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    EXECUTING = "EXECUTING"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class PaymentOrigin(str, Enum):
    AUTO_ALLOCATED = "AUTO_ALLOCATED"
    MANUAL = "MANUAL"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    DISBURSED = "DISBURSED"
    VOIDED = "VOIDED"
    RETURNED = "RETURNED"


class DisclosureStatus(str, Enum):
    PRIVILEGED = "PRIVILEGED"
    DISCLOSABLE = "DISCLOSABLE"


class SelfTestStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED_NO_VIOLATION = "CLOSED_NO_VIOLATION"
    CLOSED_VIOLATION = "CLOSED_VIOLATION"
    REMEDIATED = "REMEDIATED"
    PRIVILEGE_LOST = "PRIVILEGE_LOST"


class SelfTestOutcome(str, Enum):
    NO_VIOLATION = "NO_VIOLATION"
    VIOLATION_FOUND = "VIOLATION_FOUND"


class BoardReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    PUBLISHED = "PUBLISHED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry the full common-field set per PRD section 2.4)
# ---------------------------------------------------------------------------

class Market(TypedDict, total=False):
    id: str
    name: str
    msa_code: str
    protected_group_population_share: float
    peer_group_code: str
    created_at: str
    updated_at: str
    version: int


class Branch(TypedDict, total=False):
    id: str
    market_id: str
    name: str
    tract_minority_pct: float
    opened_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanOfficer(TypedDict, total=False):
    id: str
    branch_id: str
    full_name: str
    status: str
    approved_exception_count: int
    confirmed_override_count: int
    validated_application_count: int
    risk_score: float
    monitoring_tier: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    market_id: str
    branch_id: str
    loan_officer_id: str
    product_type: str
    applicant_group: str
    outcome: str
    note_rate_bps: int
    loan_amount_cents: int
    credit_score: int
    dti_pct: float
    application_date: str
    decision_date: str
    status: str
    has_exception: str
    created_at: str
    updated_at: str
    version: int


class PricingException(TypedDict, total=False):
    id: str
    application_id: str
    loan_officer_id: str
    kind: str
    requested_rate_bps: int
    justification: str
    status: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnderwritingOverride(TypedDict, total=False):
    id: str
    application_id: str
    loan_officer_id: str
    original_decision: str
    overridden_decision: str
    justification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PeerBenchmark(TypedDict, total=False):
    id: str
    market_id: str
    period_start: str
    period_end: str
    peer_protected_origination_rate: float
    peer_origination_count: int
    source: str
    created_at: str
    updated_at: str
    version: int


class AnalysisRun(TypedDict, total=False):
    id: str
    market_id: str
    product_type: str
    prohibited_basis: str
    period_start: str
    period_end: str
    status: str
    locked_at: Optional[str]
    snapshot_application_count: Optional[int]
    approval_rate_protected_net: Optional[float]
    approval_rate_control_net: Optional[float]
    impact_ratio_net: Optional[float]
    impact_ratio_raw: Optional[float]
    pricing_disparity_unadjusted_bps: Optional[float]
    pricing_disparity_adjusted_bps: Optional[float]
    adverse_classification: Optional[str]
    screening_flag: Optional[bool]
    open_finding_count: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisparityFinding(TypedDict, total=False):
    id: str
    analysis_run_id: str
    kind: str
    source: str
    metric_value: Optional[float]
    threshold_value: Optional[float]
    notes: str
    status: str
    harmed_application_ids: List[str]
    created_by_user_id: str
    substantiated_by_user_id: Optional[str]
    refute_reason: Optional[str]
    reopen_count: int
    superseded_by_finding_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchedPairReview(TypedDict, total=False):
    id: str
    finding_id: str
    target_application_id: str
    control_application_id: Optional[str]
    selector_used: bool
    status: str
    initial_outcome: Optional[str]
    initial_reviewer_user_id: Optional[str]
    confirmed_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict, total=False):
    id: str
    finding_id: str
    title: str
    pool_cents: int
    remaining_cents: int
    disbursed_cents: int
    due_date: str
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationPayment(TypedDict, total=False):
    id: str
    corrective_action_plan_id: str
    application_id: str
    amount_cents: int
    origin: str
    status: str
    disbursed_by_user_id: Optional[str]
    disposition_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SelfTest(TypedDict, total=False):
    id: str
    market_id: str
    analysis_run_id: Optional[str]
    window_start: str
    window_end: str
    privileged: bool
    disclosure_status: str
    status: str
    cycles_open: int
    created_at: str
    updated_at: str
    version: int


class BoardReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    status: str
    substantiated_finding_count: int
    caps_executing_count: int
    red_officer_count: int
    privileged_exclusion_count: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
