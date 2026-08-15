"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    INSIDER = "Insider"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    COMMITTEE_MEMBER = "CommitteeMember"
    LEGAL_ADMIN = "LegalAdmin"


class Designation(str, Enum):
    SECTION_16_OFFICER = "SECTION_16_OFFICER"
    DIRECTOR = "DIRECTOR"
    EMPLOYEE = "EMPLOYEE"
    CONSULTANT = "CONSULTANT"


class CoveredPersonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DealType(str, Enum):
    MERGER = "MERGER"
    ACQUISITION = "ACQUISITION"
    DIVESTITURE = "DIVESTITURE"
    FINANCING = "FINANCING"
    RESTRUCTURING = "RESTRUCTURING"


class DealStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class RestrictedEntrySource(str, Enum):
    DEAL_INTAKE = "DEAL_INTAKE"
    MANUAL = "MANUAL"


class RestrictedEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class RemovedReason(str, Enum):
    DEAL_CLOSED = "DEAL_CLOSED"
    MANUAL = "MANUAL"


class BlackoutWindowKind(str, Enum):
    QUARTERLY = "QUARTERLY"
    EVENT_DRIVEN = "EVENT_DRIVEN"


class FiscalQuarter(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"


class BlackoutWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"
    CANCELLED = "CANCELLED"
    MERGED = "MERGED"


class TradeSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PreclearanceRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"
    CLOSED = "CLOSED"


class DenialReason(str, Enum):
    RESTRICTED_LIST = "RESTRICTED_LIST"
    OFFICER_DISCRETION = "OFFICER_DISCRETION"


class ExceptionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class CommitteeVote(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class TenB5PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    CANCELLED = "CANCELLED"


class TradeConfirmationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    MATCHED_PRECLEARANCE = "MATCHED_PRECLEARANCE"
    MATCHED_PLAN = "MATCHED_PLAN"
    FLAGGED = "FLAGGED"
    CLEARED = "CLEARED"


class FlaggedReason(str, Enum):
    BLACKOUT_TRADE = "BLACKOUT_TRADE"
    RESTRICTED_LIST = "RESTRICTED_LIST"
    NO_PRECLEARANCE = "NO_PRECLEARANCE"


class ViolationType(str, Enum):
    BLACKOUT_TRADE = "BLACKOUT_TRADE"
    NO_PRECLEARANCE = "NO_PRECLEARANCE"
    RESTRICTED_LIST = "RESTRICTED_LIST"
    PLAN_VIOLATION = "PLAN_VIOLATION"
    OTHER = "OTHER"


class ViolationCaseStatus(str, Enum):
    OPENED = "OPENED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    ESCALATED = "ESCALATED"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNFOUNDED = "UNFOUNDED"
    SANCTION_RECORDED = "SANCTION_RECORDED"
    CLOSED = "CLOSED"


class ViolationCaseSource(str, Enum):
    AUTO_FLAG = "AUTO_FLAG"
    MANUAL = "MANUAL"


class Sanction(str, Enum):
    WARNING = "WARNING"
    SUSPENSION_30D = "SUSPENSION_30D"
    SUSPENSION_90D = "SUSPENSION_90D"
    TERMINATION_REFERRAL = "TERMINATION_REFERRAL"


class AttestationKind(str, Enum):
    POLICY_ACK = "POLICY_ACK"
    ANNUAL_TRAINING = "ANNUAL_TRAINING"


class AttestationStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"


class CoveredPerson(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    designation: str
    department: str
    status: str
    suspended_until: Optional[str]
    policy_ack_current: bool
    training_current: bool
    compliance_hold: bool
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict, total=False):
    id: str
    codename: str
    deal_type: str
    security_ticker: str
    event_blackout_start: Optional[str]
    event_blackout_end: Optional[str]
    status: str
    activated_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestrictedListEntry(TypedDict, total=False):
    id: str
    security_ticker: str
    deal_id: Optional[str]
    source: str
    note: Optional[str]
    status: str
    removed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlackoutWindow(TypedDict, total=False):
    id: str
    kind: str
    fiscal_year: Optional[int]
    fiscal_quarter: Optional[str]
    security_ticker: Optional[str]
    deal_id: Optional[str]
    start_at: str
    end_at: str
    status: str
    merged_into_id: Optional[str]
    applicability_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PreclearanceRequest(TypedDict, total=False):
    id: str
    covered_person_id: str
    security_ticker: str
    trade_side: str
    quantity: float
    proposed_trade_date: str
    exception_id: Optional[str]
    status: str
    denial_reason: Optional[str]
    decided_by: Optional[str]
    decided_at: Optional[str]
    approval_valid_until: Optional[str]
    matched_quantity: float
    remaining_quantity: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ExceptionRequest(TypedDict, total=False):
    id: str
    covered_person_id: str
    security_ticker: str
    quantity: float
    hardship_reason: str
    status: str
    votes_for: int
    votes_against: int
    voter_ids: List[str]
    decision_window_end: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TenB5Plan(TypedDict, total=False):
    id: str
    covered_person_id: str
    security_ticker: str
    total_quantity: float
    first_trade_date: str
    status: str
    approved_at: Optional[str]
    approved_by: Optional[str]
    return_note: Optional[str]
    cooling_off_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeConfirmation(TypedDict, total=False):
    id: str
    covered_person_id: str
    security_ticker: str
    trade_side: str
    quantity: float
    price: float
    trade_date: str
    broker_ref: str
    status: str
    match_preclearance_id: Optional[str]
    match_plan_id: Optional[str]
    flagged_reason: Optional[str]
    trade_value: float
    created_at: str
    updated_at: str
    version: int


class ViolationCase(TypedDict, total=False):
    id: str
    covered_person_id: str
    trade_confirmation_id: Optional[str]
    violation_type: str
    source: str
    status: str
    severity_score: Optional[int]
    sanction: Optional[str]
    sanction_recorded_at: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Attestation(TypedDict, total=False):
    id: str
    covered_person_id: str
    kind: str
    period_year: int
    due_date: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
