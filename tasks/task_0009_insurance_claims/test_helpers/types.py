"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


# ─── Role enum (PRD §2.1: exactly five roles) ─────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    ADJUSTER = "Adjuster"
    REVIEWER = "Reviewer"
    PAYOUT_OFFICER = "PayoutOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status enums (PRD §3, state machines) ────────────────────────────
class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CoverageType(str, Enum):
    AUTO = "AUTO"
    PROPERTY = "PROPERTY"
    LIABILITY = "LIABILITY"


class AdjusterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RepairShopStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLACKLISTED = "BLACKLISTED"


class ClaimStatus(str, Enum):
    INTAKE = "INTAKE"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


class ReportChannel(str, Enum):
    WEB = "WEB"
    MOBILE = "MOBILE"
    PHONE = "PHONE"
    AGENT = "AGENT"


class ReviewPath(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class ReviewLevel(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class ReviewOutcome(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_RECONSIDERATION = "UNDER_RECONSIDERATION"
    UPHELD_DENIAL = "UPHELD_DENIAL"
    OVERTURNED = "OVERTURNED"
    WITHDRAWN = "WITHDRAWN"


class AppealOutcome(str, Enum):
    OVERTURN = "OVERTURN"
    UPHOLD = "UPHOLD"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class FraudSignal(str, Enum):
    DUPLICATE_PATTERN = "DUPLICATE_PATTERN"
    REPAIR_SHOP_COLLUSION = "REPAIR_SHOP_COLLUSION"
    DOCUMENT_FORGERY = "DOCUMENT_FORGERY"
    RAPID_RESUBMISSION = "RAPID_RESUBMISSION"


class AuditEventType(str, Enum):
    STATUS_CHANGE = "STATUS_CHANGE"
    REVIEW_DECISION = "REVIEW_DECISION"
    APPEAL_DECISION = "APPEAL_DECISION"
    PAYOUT_EVENT = "PAYOUT_EVENT"
    FRAUD_FLAG_ADDED = "FRAUD_FLAG_ADDED"


# ─── Entity TypedDicts ─────────────────────────────────────────────────
# common_fields: true entities carry id + created_at + updated_at + version

class Policy(TypedDict):
    id: str
    policy_number: str
    insured_party_id: str
    coverage_type: str
    coverage_limit_cents: int
    deductible_cents: int
    coinsurance_ratio: float
    effective_from: str
    effective_to: str
    reporting_window_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Adjuster(TypedDict):
    id: str
    full_name: str
    license_number: str
    specialty: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairShop(TypedDict):
    id: str
    name: str
    tax_id: str
    trust_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    claim_number: str
    policy_id: str
    claimant_id: str
    report_channel: str
    idempotency_key: str
    loss_date: str
    reported_at: str
    incident_description: str
    claimed_amount_cents: int
    assessed_loss_cents: int
    salvage_value_cents: int
    subrogation_recovery_cents: int
    status: str
    review_path: Optional[str]
    gross_payout_cents: Optional[int]
    net_payout_cents: Optional[int]
    denial_reason: Optional[str]
    fraud_score: float
    created_at: str
    updated_at: str
    version: int


class Investigation(TypedDict):
    id: str
    claim_id: str
    adjuster_id: str
    photo_urls: List[str]
    assessed_loss_cents: int
    document_authenticity_passed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    claim_id: str
    requestor_id: str
    grounds: str
    secondary_reviewer_id: Optional[str]
    status: str
    final_decision_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    claim_id: str
    amount_cents: int
    bank_reference: Optional[str]
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — ONLY id + created_at, no updated_at/version

class EstimateLineItem(TypedDict):
    id: str
    investigation_id: str
    repair_shop_id: str
    description: str
    amount_cents: int
    created_at: str


class ReviewDecision(TypedDict):
    id: str
    claim_id: str
    reviewer_id: str
    review_level: str
    outcome: str
    rationale: str
    decided_at: str
    created_at: str


class FraudFlag(TypedDict):
    id: str
    claim_id: str
    signal: str
    severity: float
    created_at: str


class AuditLogEntry(TypedDict):
    id: str
    claim_id: str
    actor_id: str
    actor_role: str
    event_type: str
    from_state: Optional[str]
    to_state: Optional[str]
    payload: Dict[str, Any]
    created_at: str
