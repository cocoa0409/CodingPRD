"""Domain types: entity TypedDicts, status enums, role enum for SNAP/EBT."""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    CASEWORKER = "Caseworker"
    HOUSEHOLD_HEAD = "HouseholdHead"
    MERCHANT = "Merchant"
    FRAUD_INVESTIGATOR = "FraudInvestigator"
    STATE_ADMINISTRATOR = "StateAdministrator"
    SYSTEM_TEST = "SystemTest"


# ---------------------------------------------------------------------------
# Enumerations (from PRD §2.11)
# ---------------------------------------------------------------------------

class HouseholdCertificationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class AbawdStatus(str, Enum):
    NOT_ABAWD = "NOT_ABAWD"
    ABAWD_EXEMPT = "ABAWD_EXEMPT"
    ABAWD_WAIVED = "ABAWD_WAIVED"
    ABAWD_SUBJECT = "ABAWD_SUBJECT"


class ApplicationState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDING_INTERVIEW = "PENDING_INTERVIEW"
    INTERVIEW_DONE = "INTERVIEW_DONE"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class DenialReason(str, Enum):
    INCOME_OVER_LIMIT = "INCOME_OVER_LIMIT"
    INCOMPLETE_INFO = "INCOMPLETE_INFO"
    IDENTITY_FAILURE = "IDENTITY_FAILURE"
    OTHER = "OTHER"


class EbtCardStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REPLACED = "REPLACED"
    CLOSED = "CLOSED"


class LedgerEntryType(str, Enum):
    REGULAR_ALLOTMENT = "REGULAR_ALLOTMENT"
    EMERGENCY_ALLOTMENT = "EMERGENCY_ALLOTMENT"
    PURCHASE = "PURCHASE"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"


class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    REVERSED = "REVERSED"


class DeclineReason(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    CARD_NOT_ACTIVE = "CARD_NOT_ACTIVE"
    MERCHANT_NOT_AUTHORIZED = "MERCHANT_NOT_AUTHORIZED"
    ALL_ITEMS_INELIGIBLE = "ALL_ITEMS_INELIGIBLE"


class ItemCategory(str, Enum):
    STAPLE = "STAPLE"
    PRODUCE = "PRODUCE"
    DAIRY = "DAIRY"
    MEAT = "MEAT"
    BREAD = "BREAD"
    COLD_PREPARED = "COLD_PREPARED"
    HOT_PREPARED = "HOT_PREPARED"
    NON_FOOD = "NON_FOOD"
    ALCOHOL = "ALCOHOL"
    TOBACCO = "TOBACCO"


class MerchantAuthorizationStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class FraudCaseState(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNFOUNDED = "UNFOUNDED"
    APPEAL_PENDING = "APPEAL_PENDING"
    CLOSED = "CLOSED"


class FraudTriggerReason(str, Enum):
    TRAFFICKING_PATTERN = "TRAFFICKING_PATTERN"
    DUPLICATE_BENEFITS = "DUPLICATE_BENEFITS"
    IDENTITY_MISMATCH = "IDENTITY_MISMATCH"
    MANUAL_REPORT = "MANUAL_REPORT"


class AbawdWaiverState(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AbawdWaiverKind(str, Enum):
    WORK_TRAINING_ENROLLED = "WORK_TRAINING_ENROLLED"
    MEDICALLY_UNFIT = "MEDICALLY_UNFIT"
    CAREGIVER = "CAREGIVER"
    AREA_HIGH_UNEMPLOYMENT = "AREA_HIGH_UNEMPLOYMENT"


class AbawdWaiverDecisionReason(str, Enum):
    INSUFFICIENT_DOCS = "INSUFFICIENT_DOCS"
    INELIGIBLE_CATEGORY = "INELIGIBLE_CATEGORY"
    OTHER = "OTHER"


class EmergencyAllotmentState(str, Enum):
    DRAFT = "DRAFT"
    DECLARED = "DECLARED"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields=true carries id+created_at+updated_at+version
# ---------------------------------------------------------------------------

class Household(TypedDict):
    id: str
    case_number: str
    state_code: str
    address_zip: str
    household_size: int
    gross_monthly_income_cents: int
    net_monthly_income_cents: int
    monthly_allotment_cents: int
    certification_status: Optional[str]
    certification_period_end: Optional[str]
    dependent_care_expense_cents: int
    shelter_expense_cents: int
    has_elderly_or_disabled: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    household_id: str
    full_name: str
    date_of_birth: str
    is_disabled: bool
    is_pregnant: bool
    earned_income_cents: int
    unearned_income_cents: int
    abawd_status: str
    abawd_countable_months_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    household_id: str
    state: str
    submitted_at: Optional[str]
    interview_completed_at: Optional[str]
    decision_at: Optional[str]
    certification_period_start_at: Optional[str]
    certification_period_end_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EbtCard(TypedDict):
    id: str
    household_id: str
    card_number_last4: str
    status: str
    issued_at: str
    activated_at: Optional[str]
    balance_cents: int
    replaced_by_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# BenefitLedger is append-only (common_fields=false): only id + created_at
class BenefitLedger(TypedDict):
    id: str
    household_id: str
    card_id: str
    entry_type: str
    amount_cents: int
    benefit_month: str
    reference_id: Optional[str]
    created_at: str


# Transaction is append-only (common_fields=false): only id + created_at
class Transaction(TypedDict):
    id: str
    card_id: str
    merchant_id: str
    requested_amount_cents: int
    eligible_amount_cents: int
    ineligible_amount_cents: int
    status: str
    decline_reason: Optional[str]
    line_items: list
    posted_at: Optional[str]
    created_at: str


class Merchant(TypedDict):
    id: str
    name: str
    snap_authorization_status: str
    authorization_expires_at: str
    hot_food_pilot: bool
    created_at: str
    updated_at: str
    version: int


class FraudCase(TypedDict):
    id: str
    household_id: str
    state: str
    trigger_reason: str
    suspicious_score: float
    investigator_user_id: Optional[str]
    opened_at: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AbawdWaiver(TypedDict):
    id: str
    member_id: str
    waiver_kind: str
    state: str
    effective_from: str
    effective_to: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmergencyAllotment(TypedDict):
    id: str
    state_code: str
    benefit_month: str
    state: str
    max_allotment_table_version: int
    declared_at: Optional[str]
    disbursed_at: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Clock is a singleton with only id + now (no created_at/updated_at/version)
class Clock(TypedDict):
    id: str
    now: str
