"""Domain types: entity TypedDicts, status enums, role enum.

Field names and the carried-field sets follow the Online Teletherapy PRD.
Two entities — SessionCredit and Message — are intentionally lightweight and
carry only id + created_at (no updated_at, no version per PRD §2.4); every
other entity carries the full common-field set.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Status / enum vocabularies (PRD §2.9)
# --------------------------------------------------------------------------
class ClientStatus(str, Enum):
    PENDING_INTAKE = "PENDING_INTAKE"
    AWAITING_MATCH = "AWAITING_MATCH"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class FinancialAidTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class RiskFlag(str, Enum):
    NONE = "NONE"
    ELEVATED = "ELEVATED"
    ACUTE = "ACUTE"


class StateCode(str, Enum):
    CA = "CA"
    NY = "NY"
    TX = "TX"
    FL = "FL"
    WA = "WA"
    IL = "IL"


class TherapistStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACCEPTING = "ACCEPTING"
    FULL = "FULL"
    INACTIVE = "INACTIVE"


class Specialty(str, Enum):
    ANXIETY = "ANXIETY"
    DEPRESSION = "DEPRESSION"
    TRAUMA = "TRAUMA"
    COUPLES = "COUPLES"
    GRIEF = "GRIEF"
    ADHD = "ADHD"


class LicenseStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class MatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SWITCH_REQUESTED = "SWITCH_REQUESTED"
    ENDED = "ENDED"


class SwitchReason(str, Enum):
    FIT = "FIT"
    AVAILABILITY = "AVAILABILITY"
    CLINICAL = "CLINICAL"
    OTHER = "OTHER"


class SubscriptionStatus(str, Enum):
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCEL_SCHEDULED = "CANCEL_SCHEDULED"
    CANCELLED = "CANCELLED"


class BillingCycleStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class SessionCreditStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class LiveSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class MessageThreadStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    ARCHIVED = "ARCHIVED"


class SenderRole(str, Enum):
    CLIENT = "CLIENT"
    THERAPIST = "THERAPIST"


class CrisisRaisedByRole(str, Enum):
    CLIENT = "CLIENT"
    THERAPIST = "THERAPIST"
    SYSTEM = "SYSTEM"


class CrisisSeverity(str, Enum):
    ELEVATED = "ELEVATED"
    ACUTE = "ACUTE"


class CrisisStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class FinancialAidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class SuperbillStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"


class UserRole(str, Enum):
    CLIENT = "Client"
    THERAPIST = "Therapist"
    CLINICAL_ADMIN = "ClinicalAdmin"
    BILLING_ADMIN = "BillingAdmin"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version)
# --------------------------------------------------------------------------
class Client(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    state_code: str
    status: str
    financial_aid_tier: str
    wallet_credit_cents: int
    risk_flag: str
    created_at: str
    updated_at: str
    version: int


class Therapist(TypedDict, total=False):
    id: str
    full_name: str
    status: str
    max_active_caseload: int
    active_caseload: int
    specialties: List[str]
    created_at: str
    updated_at: str
    version: int


class TherapistLicense(TypedDict, total=False):
    id: str
    therapist_id: str
    state_code: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IntakeQuestionnaire(TypedDict, total=False):
    id: str
    client_id: str
    presenting_concerns: List[str]
    severity_score: int
    crisis_indicator: bool
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict, total=False):
    id: str
    client_id: str
    therapist_id: str
    status: str
    match_score: int
    switch_reason: Optional[str]
    superseded_by_match_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    client_id: str
    status: str
    base_weekly_fee_cents: int
    weekly_credit_grant: int
    current_period_start: str
    pause_resumes_on: Optional[str]
    cancel_effective_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict, total=False):
    id: str
    subscription_id: str
    period_start: str
    period_end: str
    list_amount_cents: int
    wallet_applied_cents: int
    charged_amount_cents: int
    status: str
    credits_granted: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only (no updated_at, no version)
class SessionCredit(TypedDict, total=False):
    id: str
    client_id: str
    billing_cycle_id: str
    status: str
    expires_on: str
    live_session_id: Optional[str]
    created_at: str


class LiveSession(TypedDict, total=False):
    id: str
    match_id: str
    session_credit_id: Optional[str]
    starts_at: str
    ends_at: str
    status: str
    cancelled_within_window: bool
    created_at: str
    updated_at: str
    version: int


class MessageThread(TypedDict, total=False):
    id: str
    match_id: str
    status: str
    unread_for_therapist: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> id + created_at only (no updated_at, no version)
class Message(TypedDict, total=False):
    id: str
    thread_id: str
    sender_role: str
    body: str
    created_at: str


class CrisisEscalation(TypedDict, total=False):
    id: str
    client_id: str
    raised_by_role: str
    severity: str
    status: str
    safety_resources_sent: bool
    created_at: str
    updated_at: str
    version: int


class FinancialAidApplication(TypedDict, total=False):
    id: str
    client_id: str
    annual_income_cents: int
    household_size: int
    status: str
    awarded_tier: str
    created_at: str
    updated_at: str
    version: int


class Superbill(TypedDict, total=False):
    id: str
    client_id: str
    period_start: str
    period_end: str
    status: str
    session_count: int
    reimbursable_amount_cents: int
    created_at: str
    updated_at: str
    version: int
