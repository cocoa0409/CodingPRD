"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.10, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CONSUMER = "Consumer"
    BUSINESS = "Business"
    INTAKE_OFFICER = "IntakeOfficer"
    MEDIATOR = "Mediator"
    ENFORCEMENT_ATTORNEY = "EnforcementAttorney"
    UNIT_DIRECTOR = "UnitDirector"


# ---------------------------------------------------------------------------
# Status enums (PRD §2.10, §3)
# ---------------------------------------------------------------------------
class CaseStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    BUSINESS_NOTIFIED = "BUSINESS_NOTIFIED"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    RESPONSE_OVERDUE = "RESPONSE_OVERDUE"
    MEDIATION_OFFERED = "MEDIATION_OFFERED"
    MEDIATION_ACTIVE = "MEDIATION_ACTIVE"
    MEDIATION_IMPASSE = "MEDIATION_IMPASSE"
    SETTLEMENT_PENDING = "SETTLEMENT_PENDING"
    SETTLED = "SETTLED"
    REFERRED_ENFORCEMENT = "REFERRED_ENFORCEMENT"
    CLOSED_UNRESOLVED = "CLOSED_UNRESOLVED"
    DECLINED = "DECLINED"


class PublicationStatus(str, Enum):
    UNPUBLISHED = "UNPUBLISHED"
    EMBARGOED = "EMBARGOED"
    PUBLISHED = "PUBLISHED"
    SUPPRESSED = "SUPPRESSED"
    REDACTED = "REDACTED"


class ResponseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT_RETURNED = "INSUFFICIENT_RETURNED"


class MediatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RoomStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class SessionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class SessionOutcome(str, Enum):
    PROGRESS = "PROGRESS"
    IMPASSE = "IMPASSE"
    SETTLEMENT_REACHED = "SETTLEMENT_REACHED"


class OfferStatus(str, Enum):
    TENDERED = "TENDERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    RESCINDED = "RESCINDED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    FULFILLED = "FULFILLED"
    BREACHED = "BREACHED"
    SUPERSEDED = "SUPERSEDED"


class PaymentStatus(str, Enum):
    PLEDGED = "PLEDGED"
    ALLOCATED = "ALLOCATED"
    DISBURSED = "DISBURSED"
    RETURNED = "RETURNED"


class ReferralStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    RETURNED_TO_MEDIATION = "RETURNED_TO_MEDIATION"


class AlertStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class WatchStatus(str, Enum):
    CLEAR = "CLEAR"
    WATCHLIST = "WATCHLIST"
    FLAGGED = "FLAGGED"


class RatingTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class SizeTier(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class RatingMethod(str, Enum):
    LIFETIME = "LIFETIME"
    ROLLING_12M = "ROLLING_12M"


class ComplaintCategory(str, Enum):
    DECEPTIVE_PRACTICE = "DECEPTIVE_PRACTICE"
    REFUND_REFUSAL = "REFUND_REFUSAL"
    DEFECTIVE_PRODUCT = "DEFECTIVE_PRODUCT"
    BILLING_DISPUTE = "BILLING_DISPUTE"
    WARRANTY_DENIED = "WARRANTY_DENIED"
    CONTRACT_VIOLATION = "CONTRACT_VIOLATION"
    OTHER = "OTHER"


class DeclineReason(str, Enum):
    NO_JURISDICTION = "NO_JURISDICTION"
    OUT_OF_AUTHORITY = "OUT_OF_AUTHORITY"
    DUPLICATE = "DUPLICATE"
    WITHDRAWN = "WITHDRAWN"


class AllocationMethod(str, Enum):
    CHRONOLOGICAL = "CHRONOLOGICAL"
    PRO_RATA = "PRO_RATA"


class ScamCategory(str, Enum):
    PHISHING = "PHISHING"
    IMPERSONATION = "IMPERSONATION"
    ADVANCE_FEE = "ADVANCE_FEE"
    FAKE_CHARITY = "FAKE_CHARITY"
    TECH_SUPPORT = "TECH_SUPPORT"
    ROMANCE = "ROMANCE"
    OTHER = "OTHER"


class Severity(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlternativeOption(str, Enum):
    SMALL_CLAIMS = "SMALL_CLAIMS"
    PRIVATE_ATTORNEY = "PRIVATE_ATTORNEY"
    BBB = "BBB"
    FEDERAL_AGENCY = "FEDERAL_AGENCY"
    CLASS_ACTION = "CLASS_ACTION"


class EventType(str, Enum):
    CREATED = "CREATED"
    STATE_CHANGED = "STATE_CHANGED"
    RESPONSE_FILED = "RESPONSE_FILED"
    RESPONSE_REVIEWED = "RESPONSE_REVIEWED"
    SESSION_SCHEDULED = "SESSION_SCHEDULED"
    SESSION_CONFIRMED = "SESSION_CONFIRMED"
    SESSION_COMPLETED = "SESSION_COMPLETED"
    OFFER_TENDERED = "OFFER_TENDERED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_RESCINDED = "OFFER_RESCINDED"
    SETTLEMENT_CREATED = "SETTLEMENT_CREATED"
    SETTLEMENT_EXECUTED = "SETTLEMENT_EXECUTED"
    SETTLEMENT_BREACHED = "SETTLEMENT_BREACHED"
    PAYMENT_ALLOCATED = "PAYMENT_ALLOCATED"
    PAYMENT_RETURNED = "PAYMENT_RETURNED"
    PAYMENT_DISBURSED = "PAYMENT_DISBURSED"
    REFERRAL_FILED = "REFERRAL_FILED"
    REFERRAL_RETURNED = "REFERRAL_RETURNED"
    CASE_CLOSED = "CASE_CLOSED"
    PUBLISHED = "PUBLISHED"
    REDACTED = "REDACTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 common fields; informational shapes)
# ---------------------------------------------------------------------------
class Consumer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    state_code: str
    phone: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Business(TypedDict, total=False):
    id: str
    legal_name: str
    dba_name: Optional[str]
    home_state: str
    operates_in_states: List[str]
    naics_code: str
    size_tier: str
    rating_method: str
    watch_status: str
    pattern_score: int
    published_complaint_count: int
    rating_score: int
    rating_tier: str
    overdue_response_count: int
    next_filing_seq: int
    created_at: str
    updated_at: str
    version: int


class JurisdictionFactors(TypedDict):
    incident_in_state: bool
    business_operates_in_state: bool
    within_filing_window: bool


class Complaint(TypedDict, total=False):
    id: str
    consumer_id: str
    business_id: str
    incident_date: str
    incident_state: str
    category: str
    description: str
    amount_in_dispute_cents: int
    publication_consent: bool
    filing_seq: int
    filed_at: str
    case_status: str
    publication_status: str
    decline_reason: Optional[str]
    appeal_used: bool
    jurisdiction_factors: JurisdictionFactors
    accepted_by_officer_id: Optional[str]
    closed_by_officer_id: Optional[str]
    closed_at: Optional[str]
    response_deadline: Optional[str]
    response_received_at: Optional[str]
    response_attempts: int
    latest_response_id: Optional[str]
    ever_response_overdue: bool
    active_settlement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplaintEvent(TypedDict, total=False):
    # Append-only audit entry: carries ONLY id + created_at as common fields
    # (no updated_at, no version — PRD §2.4).
    id: str
    created_at: str
    complaint_id: str
    event_type: str
    from_status: Optional[str]
    to_status: Optional[str]
    actor_role: str
    actor_id: str
    note: Optional[str]


class BusinessResponse(TypedDict, total=False):
    id: str
    complaint_id: str
    business_id: str
    response_text: str
    submitted_at: str
    is_late: bool
    response_status: str
    attempt_number: int
    created_at: str
    updated_at: str
    version: int


class Mediator(TypedDict, total=False):
    id: str
    full_name: str
    employee_ref: str
    mediator_status: str
    conflicted_business_ids: List[str]
    max_concurrent_cases: int
    active_case_count: int
    created_at: str
    updated_at: str
    version: int


class MediationRoom(TypedDict, total=False):
    id: str
    room_name: str
    capacity: int
    location: str
    room_status: str
    created_at: str
    updated_at: str
    version: int


class MediationSession(TypedDict, total=False):
    id: str
    complaint_id: str
    mediator_id: str
    room_id: str
    starts_at: str
    ends_at: str
    session_status: str
    consumer_confirmed: bool
    business_confirmed: bool
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SettlementOffer(TypedDict, total=False):
    id: str
    complaint_id: str
    parent_offer_id: Optional[str]
    offer_seq: int
    offered_by_role: str
    offered_by_id: str
    restitution_amount_cents: int
    non_monetary_terms: Optional[str]
    offer_status: str
    tendered_at: str
    expires_at: str
    accepted_at: Optional[str]
    cooling_off_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    complaint_id: str
    source_offer_id: str
    business_id: str
    consumer_id: str
    restitution_amount_cents: int
    mediation_fee_cents: int
    total_due_cents: int
    fulfilled_cents: int
    outstanding_cents: int
    settlement_status: str
    executed_at: Optional[str]
    due_date: Optional[str]
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentAllocation(TypedDict):
    settlement_id: str
    complaint_id: str
    filing_seq: int
    allocated_cents: int


class RestitutionPayment(TypedDict, total=False):
    id: str
    business_id: str
    amount_cents: int
    allocation_method: str
    payment_status: str
    allocations: List[PaymentAllocation]
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementReferral(TypedDict, total=False):
    id: str
    complaint_id: str
    business_id: str
    referred_by_user_id: str
    referred_by_role: str
    reason: str
    pattern_score_at_referral: int
    referral_status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScamAlert(TypedDict, total=False):
    id: str
    title: str
    body: str
    scam_category: str
    severity: str
    related_business_id: Optional[str]
    related_complaint_id: Optional[str]
    education_topics: Optional[List[str]]
    drafted_by_user_id: str
    alert_status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
