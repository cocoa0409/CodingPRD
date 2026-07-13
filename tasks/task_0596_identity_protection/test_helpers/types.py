"""Domain types for the Identity Theft Protection API.

Entity TypedDicts, status enums and the role enum, as described in the PRD.
Every persisted resource carries id / created_at / updated_at / version (PRD §2.4).
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    SUBSCRIBER = "Subscriber"
    RESTORATION_SPECIALIST = "RestorationSpecialist"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Enums ────────────────────────────────────────────────────────────────────

class PlanTier(str, Enum):
    STANDARD = "STANDARD"
    ADVANTAGE = "ADVANTAGE"
    ULTIMATE = "ULTIMATE"


class BureauScope(str, Enum):
    SINGLE = "SINGLE"
    TRI = "TRI"


class SpecialistTier(str, Enum):
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    TIER3 = "TIER3"


class EnrollmentStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MonitoringStatus(str, Enum):
    NOT_ENROLLED = "NOT_ENROLLED"
    PENDING_DATA = "PENDING_DATA"
    MONITORED = "MONITORED"
    PAUSED = "PAUSED"


class InsuranceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    EXHAUSTED = "EXHAUSTED"


class Relationship(str, Enum):
    ADULT = "ADULT"
    CHILD = "CHILD"


class FamilyMonitoringStatus(str, Enum):
    MONITORED = "MONITORED"
    NOT_COVERED = "NOT_COVERED"


class Bureau(str, Enum):
    EQUIFAX = "EQUIFAX"
    EXPERIAN = "EXPERIAN"
    TRANSUNION = "TRANSUNION"


class FreezeStatus(str, Enum):
    UNFROZEN = "UNFROZEN"
    FREEZE_PENDING = "FREEZE_PENDING"
    FROZEN = "FROZEN"
    THAW_PENDING = "THAW_PENDING"


class FreezeAction(str, Enum):
    FREEZE = "FREEZE"
    THAW = "THAW"


class AlertType(str, Enum):
    DARK_WEB = "DARK_WEB"
    SSN_TRACE = "SSN_TRACE"
    ACCOUNT_TAKEOVER = "ACCOUNT_TAKEOVER"
    CREDIT_INQUIRY = "CREDIT_INQUIRY"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CONFIRMED_FRAUD = "CONFIRMED_FRAUD"
    DISMISSED = "DISMISSED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class SpecialistStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    AT_CAPACITY = "AT_CAPACITY"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_SUBSCRIBER = "PENDING_SUBSCRIBER"
    RESOLVED = "RESOLVED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    REVERSED = "REVERSED"
    SUPERSEDED = "SUPERSEDED"


class ExpenseCategory(str, Enum):
    LEGAL_FEES = "LEGAL_FEES"
    LOST_WAGES = "LOST_WAGES"
    TRAVEL = "TRAVEL"
    CHILDCARE = "CHILDCARE"
    NOTARY = "NOTARY"
    POSTAGE = "POSTAGE"


class WalletItemType(str, Enum):
    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    DRIVERS_LICENSE = "DRIVERS_LICENSE"
    PASSPORT = "PASSPORT"
    SSN_CARD = "SSN_CARD"
    INSURANCE_CARD = "INSURANCE_CARD"


class WalletItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPORTED_LOST = "REPORTED_LOST"


# ─── Entity TypedDicts ────────────────────────────────────────────────────────

class Plan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    insurance_limit_cents: int
    max_family_members: int
    child_monitoring_included: bool
    bureau_scope: str
    min_specialist_tier: str
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    ssn_last4: str
    plan_id: str
    enrollment_status: str
    monitoring_status: str
    verification_token: str
    composite_credit_score: Optional[int]
    baseline_composite_credit_score: Optional[int]
    risk_score: int
    underwriting_risk_score: int
    insurance_remaining_cents: int
    insurance_status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FamilyMember(TypedDict):
    id: str
    subscriber_id: str
    full_name: str
    date_of_birth: str
    ssn_last4: str
    relationship: str
    monitoring_status: str
    created_at: str
    updated_at: str
    version: int


class BureauProfile(TypedDict):
    id: str
    subscriber_id: str
    bureau: str
    credit_score: Optional[int]
    score_pulled_at: Optional[str]
    freeze_status: str
    created_at: str
    updated_at: str
    version: int


class ThawWindow(TypedDict):
    id: str
    bureau_profile_id: str
    window_start: str
    window_end: str
    purpose: str
    is_currently_open: bool
    created_at: str
    updated_at: str
    version: int


class Alert(TypedDict):
    id: str
    subscriber_id: str
    family_member_id: Optional[str]
    alert_type: str
    severity: str
    source_detail: str
    status: str
    escalation_tier: Optional[str]
    escalation_deadline: Optional[str]
    dismissal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Specialist(TypedDict):
    id: str
    full_name: str
    tier: str
    max_caseload: int
    max_concurrent_engagements: int
    active_case_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RestorationCase(TypedDict):
    id: str
    subscriber_id: str
    origin_alert_id: str
    specialist_id: Optional[str]
    status: str
    required_specialist_tier: str
    info_request: Optional[str]
    info_response: Optional[str]
    resolution_summary: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecialistEngagement(TypedDict):
    id: str
    specialist_id: str
    case_id: str
    window_start: str
    window_end: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict):
    id: str
    case_id: str
    subscriber_id: str
    expenses: List[dict]
    provisional_amount_cents: Optional[int]
    approved_cents: Optional[int]
    status: str
    approved_by_user_id: Optional[str]
    denial_reason: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WalletItem(TypedDict):
    id: str
    subscriber_id: str
    item_type: str
    issuer: str
    last4: str
    status: str
    reported_lost_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
