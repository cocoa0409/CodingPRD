"""Domain types: entity TypedDicts, status enums, role enum.

These mirror PRD §2 (Global Specifications) and §3 (Business Logic). Entities
that PRD §2.4 declares as carrying only `id` and `created_at` (EligibleItemCategory,
SystemClock) deliberately omit `updated_at` and `version` from their TypedDicts.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ───────────────────────────────────────────────────────

class HouseholdStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class HouseholdMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class EBTCardStatus(str, Enum):
    PENDING_ISSUE = "PENDING_ISSUE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REPLACED = "REPLACED"
    CANCELLED = "CANCELLED"


class MonthlyAllotmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    EXPUNGED = "EXPUNGED"
    ADJUSTED = "ADJUSTED"


class PurchaseTransactionStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class FraudFlagStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class FraudTriggerRule(str, Enum):
    VELOCITY_SPIKE = "VELOCITY_SPIKE"
    OUT_OF_STATE = "OUT_OF_STATE"
    DUPLICATE_HH_MEMBER = "DUPLICATE_HH_MEMBER"
    CARD_REPLACE_ABUSE = "CARD_REPLACE_ABUSE"


class ABAWDWaiverStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class EmergencyAllotmentProclamationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class HouseholdMemberRelationship(str, Enum):
    HEAD = "HEAD"
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    PARENT = "PARENT"
    OTHER = "OTHER"


class StateCode(str, Enum):
    CA = "CA"
    TX = "TX"
    NY = "NY"
    FL = "FL"
    IL = "IL"
    PA = "PA"
    OH = "OH"
    GA = "GA"
    NC = "NC"
    MI = "MI"


# ─── Role enum (PRD §2.1) ───────────────────────────────────────────────

class UserRole(str, Enum):
    Caseworker = "Caseworker"
    Applicant = "Applicant"
    Cardholder = "Cardholder"
    BenefitIssuer = "BenefitIssuer"
    FraudInvestigator = "FraudInvestigator"
    Merchant = "Merchant"
    PolicyAdmin = "PolicyAdmin"


# ─── Common-fields TypedDicts (PRD §2.4: id + created_at + updated_at + version) ──

class Household(TypedDict, total=False):
    id: str
    case_number: str
    state_code: str
    address_line: str
    size: int
    gross_income_cents: int
    net_income_cents: int
    status: str
    certification_end_date: Optional[str]
    heap_recipient: bool
    created_at: str
    updated_at: str
    version: int


class HouseholdMember(TypedDict, total=False):
    id: str
    household_id: str
    full_name: str
    date_of_birth: str
    relationship: str
    monthly_earned_income_cents: int
    monthly_unearned_income_cents: int
    disabled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    household_id: str
    applied_at: Optional[str]
    status: str
    caseworker_id: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EBTCard(TypedDict, total=False):
    id: str
    household_id: str
    pan_last4: Optional[str]
    status: str
    replaced_by_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonthlyAllotment(TypedDict, total=False):
    id: str
    household_id: str
    benefit_month: str
    standard_allotment_cents: int
    emergency_supplement_cents: int
    issued_total_cents: int
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseTransaction(TypedDict, total=False):
    id: str
    ebt_card_id: str
    household_id: str
    merchant_id: str
    total_cents: int
    line_items: List[dict]
    ineligible_line_codes: List[str]
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FraudFlag(TypedDict, total=False):
    id: str
    household_id: str
    trigger_rule: str
    status: str
    investigator_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ABAWDWaiver(TypedDict, total=False):
    id: str
    household_member_id: str
    quarter: str
    county_unemployment_pct: float
    monthly_work_hours: int
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmergencyAllotmentProclamation(TypedDict, total=False):
    id: str
    state_code: str
    benefit_month: str
    min_supplement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── PRD §2.4 lighter entities (id + created_at only — NO updated_at/version) ───

class EligibleItemCategory(TypedDict, total=False):
    id: str
    code: str
    name: str
    eligible: bool
    created_at: str


class SystemClock(TypedDict, total=False):
    id: str
    current_utc: str
    created_at: str
