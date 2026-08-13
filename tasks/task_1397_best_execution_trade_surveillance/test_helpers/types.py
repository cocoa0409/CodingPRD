"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    SURVEILLANCE_ANALYST = "SurveillanceAnalyst"
    FILING_OFFICER = "FilingOfficer"
    BEST_EX_ANALYST = "BestExAnalyst"
    COMMITTEE_MEMBER = "CommitteeMember"
    COVERED_EMPLOYEE = "CoveredEmployee"


class Department(str, Enum):
    TRADING = "TRADING"
    OPERATIONS = "OPERATIONS"
    COMPLIANCE = "COMPLIANCE"
    EXECUTIVE = "EXECUTIVE"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class AttestationStatus(str, Enum):
    CURRENT = "CURRENT"
    DUE = "DUE"
    LAPSED = "LAPSED"


class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VenueType(str, Enum):
    EXCHANGE = "EXCHANGE"
    ATS = "ATS"
    MARKET_MAKER = "MARKET_MAKER"


class ArrangementStatus(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class OrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ROUTED = "ROUTED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    MARKET_ON_CLOSE = "MARKET_ON_CLOSE"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class SnapshotStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    LOCKED = "LOCKED"


class SnapshotVariant(str, Enum):
    FAR_TOUCH = "FAR_TOUCH"
    MIDPOINT = "MIDPOINT"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class PricingVariant(str, Enum):
    MARGINAL = "MARGINAL"
    RETROACTIVE = "RETROACTIVE"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_COMMITTEE = "IN_COMMITTEE"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"


class Determination(str, Enum):
    CONTINUE = "CONTINUE"
    MODIFY = "MODIFY"
    TERMINATE_ROUTING = "TERMINATE_ROUTING"


class AlertType(str, Enum):
    FRONT_RUNNING = "FRONT_RUNNING"
    MARKING_THE_CLOSE = "MARKING_THE_CLOSE"


class AlertStatus(str, Enum):
    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    CLOSED_FALSE_POSITIVE = "CLOSED_FALSE_POSITIVE"


class CaseReviewStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    DISPOSITIONED = "DISPOSITIONED"
    REOPENED = "REOPENED"


class Disposition(str, Enum):
    VIOLATION_CONFIRMED = "VIOLATION_CONFIRMED"
    UNFOUNDED = "UNFOUNDED"


class FilingStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class TradeStatus(str, Enum):
    PRECLEARANCE_REQUESTED = "PRECLEARANCE_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTION_REPORTED = "EXECUTION_REPORTED"
    RECONCILED = "RECONCILED"
    EXPIRED = "EXPIRED"


class RestrictionKind(str, Enum):
    ALL = "ALL"
    EMPLOYEE_ONLY = "EMPLOYEE_ONLY"
    CLIENT_ONLY = "CLIENT_ONLY"


class RestrictedEntryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class CommItemStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_REVIEW = "IN_REVIEW"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"


class Channel(str, Enum):
    EMAIL = "EMAIL"
    CHAT = "CHAT"


class LexiconStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class TrainingStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# All fifteen resource types carry the four common properties id, created_at,
# updated_at, version (PRD §2.5), so every TypedDict below includes them.


class Employee(TypedDict, total=False):
    id: str
    full_name: str
    employee_ref: str
    department: str
    employment_status: str
    attestation_status: str
    attestation_due_at: str
    last_attested_at: Optional[str]
    open_case_count: int
    training_overdue_count: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    venue_code: str
    name: str
    venue_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PfofTier(TypedDict):
    min_monthly_shares: int
    rate_cents_per_share: float


class RoutingArrangement(TypedDict, total=False):
    id: str
    venue_id: str
    effective_from: str
    effective_to: str
    pfof_tiers: List[PfofTier]
    routing_fee_bps: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    client_ref: str
    symbol: str
    side: str
    quantity: int
    order_type: str
    limit_price_cents: Optional[int]
    arrival_nbbo_bid_cents: int
    arrival_nbbo_ask_cents: int
    arrangement_id: Optional[str]
    status: str
    routed_at: Optional[str]
    executed_price_cents: Optional[int]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExecutionQualitySnapshot(TypedDict, total=False):
    id: str
    venue_id: str
    order_type: str
    period_month: str
    variant: str
    status: str
    order_count: int
    total_quantity: int
    total_improvement_cents: float
    avg_improvement_cents_per_share: float
    created_at: str
    updated_at: str
    version: int


class VenueLine(TypedDict, total=False):
    venue_id: str
    arrangement_id: str
    arrangement_version: int
    total_shares: int
    pfof_cents: int


class PfofDisclosure(TypedDict, total=False):
    id: str
    quarter: str
    pricing_variant: str
    revision_number: int
    supersedes_id: Optional[str]
    has_pending_revision: bool
    status: str
    venue_lines: List[VenueLine]
    total_pfof_cents: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BestExReview(TypedDict, total=False):
    id: str
    quarter: str
    snapshot_ids: List[str]
    venue_decisions: List[Dict[str, str]]
    created_by_user_id: str
    voter_user_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveillanceAlert(TypedDict, total=False):
    id: str
    alert_type: str
    subject_employee_id: Optional[str]
    related_order_id: Optional[str]
    related_trade_id: Optional[str]
    case_id: Optional[str]
    score: int
    score_inputs: Dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveillanceCase(TypedDict, total=False):
    id: str
    subject_employee_id: Optional[str]
    opened_from: str
    source_comm_item_id: Optional[str]
    linked_alert_ids: List[str]
    review_status: str
    disposition: Optional[str]
    dispositioned_at: Optional[str]
    filing_status: str
    filing_due_at: Optional[str]
    filing_submitted_at: Optional[str]
    late_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class PersonalTrade(TypedDict, total=False):
    id: str
    employee_id: str
    symbol: str
    side: str
    quantity: int
    status: str
    decided_at: Optional[str]
    denial_reason: Optional[str]
    expires_at: Optional[str]
    executed_price_cents: Optional[int]
    executed_at: Optional[str]
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RestrictedListEntry(TypedDict, total=False):
    id: str
    symbol: str
    restriction_kind: str
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CommReviewItem(TypedDict, total=False):
    id: str
    channel: str
    author_employee_id: str
    body_text: str
    captured_at: str
    score: int
    matched_terms: List[str]
    scored_policy_version: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class LexiconPolicy(TypedDict, total=False):
    id: str
    name: str
    terms: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class CompliancePolicy(TypedDict, total=False):
    id: str
    policy_code: str
    title: str
    version_label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingAssignment(TypedDict, total=False):
    id: str
    employee_id: str
    policy_id: str
    due_date: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
