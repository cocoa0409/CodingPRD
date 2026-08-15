"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import Any, Dict, Optional, TypedDict


class UserRole(str, Enum):
    TRUST_ADMIN = "TrustAdmin"
    STEWARDSHIP_COORDINATOR = "StewardshipCoordinator"
    FIELD_MONITOR = "FieldMonitor"
    LANDOWNER = "Landowner"
    TRUST_BOARD_REVIEWER = "TrustBoardReviewer"
    APPRAISER = "Appraiser"


class EasementStatus(str, Enum):
    DRAFT = "DRAFT"
    RECORDED = "RECORDED"


class EasementPosture(str, Enum):
    ENFORCEMENT_ACTIVE = "ENFORCEMENT_ACTIVE"
    VIOLATION_OPEN = "VIOLATION_OPEN"
    MONITORING_DUE = "MONITORING_DUE"
    GOOD_STANDING = "GOOD_STANDING"


class LandownerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING_SUCCESSION = "PENDING_SUCCESSION"
    SUPERSEDED = "SUPERSEDED"


class BaselineReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"


class MonitoringVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    NOTICE_SENT = "NOTICE_SENT"
    CURE_IN_PROGRESS = "CURE_IN_PROGRESS"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class ViolationSeverity(str, Enum):
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"
    IRREPARABLE = "IRREPARABLE"


class AmendmentRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    STAFF_REVIEW = "STAFF_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    BOARD_REVIEW = "BOARD_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ReviewPath(str, Enum):
    STAFF = "STAFF"
    BOARD = "BOARD"


class UseAuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    DENIED = "DENIED"


class UseAuthorizationDecision(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    DENIED = "DENIED"


class EnforcementActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EXECUTED = "EXECUTED"
    BREACHED = "BREACHED"
    COMPLETED = "COMPLETED"


class SuccessionNoticeStatus(str, Enum):
    NOTICE_GIVEN = "NOTICE_GIVEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RECORDED = "RECORDED"
    EXPIRED = "EXPIRED"


class AppraisalStatus(str, Enum):
    ENGAGED = "ENGAGED"
    DELIVERED = "DELIVERED"
    CERTIFIED = "CERTIFIED"
    WITHDRAWN = "WITHDRAWN"


class EndowmentFundStatus(str, Enum):
    INITIALIZING = "INITIALIZING"
    ACTIVE = "ACTIVE"


class EndowmentTxnType(str, Enum):
    CONTRIBUTION = "CONTRIBUTION"
    INVESTMENT_RETURN = "INVESTMENT_RETURN"
    DRAW = "DRAW"


class DrawPurpose(str, Enum):
    MONITORING = "MONITORING"
    ENFORCEMENT = "ENFORCEMENT"
    GENERAL_STEWARDSHIP = "GENERAL_STEWARDSHIP"


class UseLevel(str, Enum):
    PERMITTED = "PERMITTED"
    DISCRETIONARY = "DISCRETIONARY"
    PROHIBITED = "PROHIBITED"


# --- Entity TypedDicts (PRD §2.4 common fields: id, created_at, updated_at, version) ---


class Easement(TypedDict, total=False):
    id: str
    easement_name: str
    grantor_name: str
    parcel_acreage: int
    permitted_use_matrix: Dict[str, str]
    monitoring_interval_months: int
    status: str
    posture: str
    current_landowner_id: Optional[str]
    recorded_on: Optional[str]
    last_monitoring_completed_on: Optional[str]
    next_monitoring_due_on: Optional[str]
    open_violation_count: int
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class Landowner(TypedDict, total=False):
    id: str
    easement_id: str
    predecessor_landowner_id: Optional[str]
    owner_name: str
    contact_email: str
    status: str
    acquired_on: str
    created_at: str
    updated_at: str
    version: int


class BaselineReport(TypedDict, total=False):
    id: str
    easement_id: str
    prepared_by_user_id: str
    condition_narrative: str
    photo_point_count: int
    required_photo_points: Optional[int]
    review_round: int
    submitted_on: Optional[str]
    accepted_on: Optional[str]
    revision_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MonitoringVisit(TypedDict, total=False):
    id: str
    easement_id: str
    monitor_user_id: str
    window_start_on: str
    window_end_on: str
    actual_visit_on: Optional[str]
    findings_summary: Optional[str]
    stewardship_cost_cents: Optional[int]
    on_time: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    easement_id: str
    monitoring_visit_id: Optional[str]
    detected_by_user_id: str
    violation_type: str
    severity: str
    detected_on: str
    notice_served_on: Optional[str]
    cure_deadline_on: Optional[str]
    resolved_on: Optional[str]
    resolution_verified_by_user_id: Optional[str]
    escalated_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AmendmentRequest(TypedDict, total=False):
    id: str
    easement_id: str
    submitted_by_user_id: str
    requested_changes: list
    affected_acreage: int
    materiality_score: int
    review_path: str
    revision_notes: Optional[str]
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UseAuthorization(TypedDict, total=False):
    id: str
    easement_id: str
    use_type: str
    requested_by_landowner_id: str
    justification: str
    decision: Optional[str]
    conditions: Optional[list]
    decision_reason: Optional[str]
    conditions_breached: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict, total=False):
    id: str
    violation_id: str
    easement_id: str
    agreement_terms: Optional[str]
    remediation_cost_cents: Optional[int]
    executed_by_user_id: Optional[str]
    completed_by_user_id: Optional[str]
    breach_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SuccessionNotice(TypedDict, total=False):
    id: str
    easement_id: str
    successor_landowner_id: str
    predecessor_landowner_id: str
    transfer_on: str
    notice_given_on: str
    ack_deadline_on: str
    recorded_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict, total=False):
    id: str
    easement_id: str
    appraiser_user_id: str
    effective_on: str
    gift_on: str
    contiguous_enhancement_applies: bool
    before_value_cents: Optional[int]
    after_value_cents: Optional[int]
    enhancement_value_cents: Optional[int]
    deductible_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class EndowmentFund(TypedDict, total=False):
    id: str
    easement_id: str
    spending_rate_bps: int
    principal_floor_cents: int
    status: str
    market_value_cents: int
    units_outstanding: float
    unit_value_cents: Optional[float]
    fiscal_year: int
    prior_year_close_mv_cents: int
    provisional_draws_ytd_cents: int
    policy_draw_allowance_cents: int
    carryover_allowance_cents: int
    unitized_draw_capacity_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only ledger event (PRD §2.4): carries id and created_at ONLY —
# no updated_at, no version.
class EndowmentTransaction(TypedDict, total=False):
    id: str
    fund_id: str
    txn_type: str
    amount_cents: int
    units: float
    purpose: Optional[str]
    from_policy_allowance_cents: Optional[int]
    from_excess_cents: Optional[int]
    from_principal_invasion_cents: Optional[int]
    fiscal_year: int
    posted_on: str
    created_at: str
