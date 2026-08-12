"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    BSA_ANALYST = "BSAAnalyst"
    QA_REVIEWER = "QAReviewer"
    BSA_MANAGER = "BSAManager"


class CountryRisk(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXITED = "EXITED"


class RiskRating(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    PROHIBITED = "PROHIBITED"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    EXITED = "EXITED"


class TxnType(str, Enum):
    CASH_DEPOSIT = "CASH_DEPOSIT"
    WIRE_IN = "WIRE_IN"
    WIRE_OUT = "WIRE_OUT"
    ACH_DEBIT = "ACH_DEBIT"
    CHECK_DEPOSIT = "CHECK_DEPOSIT"


class TxnDirection(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class TxnChannel(str, Enum):
    BRANCH = "BRANCH"
    ATM = "ATM"
    ONLINE = "ONLINE"
    WIRE_DESK = "WIRE_DESK"


class ScenarioStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ThresholdStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class AlertStatus(str, Enum):
    NEW = "NEW"
    UNDER_TRIAGE = "UNDER_TRIAGE"
    DISMISSED = "DISMISSED"
    LINKED = "LINKED"
    AUTO_CLOSED = "AUTO_CLOSED"


class AlertClosureReason(str, Enum):
    STALE_EXPIRY = "STALE_EXPIRY"
    CUSTOMER_EXITED = "CUSTOMER_EXITED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    INVESTIGATING = "INVESTIGATING"
    ON_HOLD = "ON_HOLD"
    SAR_IN_PROGRESS = "SAR_IN_PROGRESS"
    PENDING_QA = "PENDING_QA"
    CLOSED = "CLOSED"


class CaseDecision(str, Enum):
    NONE = "NONE"
    SAR_REQUIRED = "SAR_REQUIRED"
    NO_SAR = "NO_SAR"


class CaseClosedReason(str, Enum):
    NO_SAR_CONFIRMED = "NO_SAR_CONFIRMED"
    SAR_FILED = "SAR_FILED"


class SARStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_QA = "IN_QA"
    QA_PASSED = "QA_PASSED"
    APPROVED = "APPROVED"
    FILED = "FILED"


class ReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"


class ReviewOutcome(str, Enum):
    NONE = "NONE"
    FILE_CONTINUING_SAR = "FILE_CONTINUING_SAR"
    CLOSE_MONITORING = "CLOSE_MONITORING"


class InquiryStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESPONDED = "RESPONDED"
    CLOSED = "CLOSED"


class InfoShareStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    RESPONDED = "RESPONDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class InfoShareDirection(str, Enum):
    OUTBOUND = "OUTBOUND"
    INBOUND = "INBOUND"


class AccountDecisionKind(str, Enum):
    EXIT = "EXIT"
    RESTRICT = "RESTRICT"
    RETAIN = "RETAIN"


class AccountDecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REVERSED = "REVERSED"


class QAReviewOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class QAReviewStatus(str, Enum):
    SAMPLED = "SAMPLED"
    COMPLETED = "COMPLETED"


# ---------------------------------------------------------------------------
# Entity payloads (PRD §2.4: most resources carry id/created_at/updated_at/
# version; Transaction is the documented exception with only id/created_at).
# ---------------------------------------------------------------------------


class Analyst(TypedDict, total=False):
    id: str
    full_name: str
    capacity_max_cases: int
    assigned_open_cases: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    country_code: str
    country_risk: str
    status: str
    sar_filings_365d: int
    open_le_inquiry_count: int
    any_account_exited: bool
    risk_score_standard: int
    risk_score_enhanced: int
    risk_rating: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    customer_id: str
    account_number: str
    status: str
    restriction_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict, total=False):
    # Append-only posted event: carries only id + created_at (no updated_at,
    # no version) per PRD §2.4.
    id: str
    account_id: str
    amount_cents: int
    txn_type: str
    direction: str
    counterparty_country: str
    posted_at: str
    channel: str
    created_at: str


class MonitoringScenario(TypedDict, total=False):
    id: str
    scenario_code: str
    name: str
    applies_to_txn_types: List[str]
    direction_filter: str
    status: str
    baseline_weight_amount: float
    baseline_weight_velocity: float
    baseline_weight_geo: float
    stale_alert_days: int
    current_active_threshold_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScenarioThreshold(TypedDict, total=False):
    id: str
    scenario_id: str
    version_number: int
    threshold_amount_cents: int
    lookback_days: int
    min_transaction_count: int
    weight_amount: float
    weight_velocity: float
    weight_geo: float
    effective_from: str
    effective_to: Optional[str]
    tuning_rationale: str
    backtest_precision: float
    backtest_recall: float
    status: str
    proposed_by_analyst_id: str
    approved_by_analyst_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Alert(TypedDict, total=False):
    id: str
    scenario_id: str
    scenario_threshold_id: str
    account_id: str
    customer_id: str
    case_id: Optional[str]
    window_start: str
    window_end: str
    aggregate_amount_cents: int
    txn_count: int
    risk_score: int
    baseline_score: int
    status: str
    triaged_by_analyst_id: Optional[str]
    dismissal_rationale: Optional[str]
    dismissed_at: Optional[str]
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    customer_id: str
    source_alert_id: Optional[str]
    assigned_analyst_id: Optional[str]
    on_hold_inquiry_id: Optional[str]
    status: str
    decision: str
    decision_rationale: Optional[str]
    decided_at: Optional[str]
    initial_detection_at: Optional[str]
    qa_reviewed_by: Optional[str]
    closed_reason: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SARReport(TypedDict, total=False):
    id: str
    case_id: str
    customer_id: str
    prior_sar_id: Optional[str]
    is_continuing: bool
    subject_unidentified: bool
    narrative: str
    narrative_length: int
    activity_start_date: str
    activity_end_date: str
    deadline_at: str
    status: str
    drafted_by_analyst_id: str
    qa_reviewer_id: Optional[str]
    approved_by_analyst_id: Optional[str]
    filed_at: Optional[str]
    filing_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContinuingReview(TypedDict, total=False):
    id: str
    sar_report_id: str
    cycle_number: int
    due_at: str
    filing_deadline_at: str
    status: str
    outcome: str
    completed_at: Optional[str]
    created_continuing_sar_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LawEnforcementInquiry(TypedDict, total=False):
    id: str
    agency_name: str
    inquiry_reference: str
    subject_customer_id: str
    case_id: Optional[str]
    received_at: str
    status: str
    response_summary: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InfoShareRequest(TypedDict, total=False):
    id: str
    direction: str
    counterparty_institution_id: str
    subject_customer_id: str
    case_id: Optional[str]
    certified_at: str
    certification_expires_at: str
    purpose_note: str
    sent_at: Optional[str]
    response_received_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccountDecision(TypedDict, total=False):
    id: str
    account_id: str
    decision: str
    rationale: str
    status: str
    proposed_by_analyst_id: str
    approved_by_analyst_id: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QAReview(TypedDict, total=False):
    id: str
    case_id: Optional[str]
    sar_report_id: Optional[str]
    period_month: str
    reviewer_id: str
    outcome: str
    defect_count: int
    notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
