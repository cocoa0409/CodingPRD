"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Enumerations ─────────────────────────────────────

class UserRole(str, Enum):
    PATIENT = "Patient"
    FINANCIAL_COUNSELOR = "FinancialCounselor"
    ASSISTANCE_REVIEWER = "AssistanceReviewer"
    BILLING_ADMINISTRATOR = "BillingAdministrator"
    COLLECTIONS_AGENT = "CollectionsAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class CollectionPosture(str, Enum):
    NOT_IN_COLLECTIONS = "NOT_IN_COLLECTIONS"
    NOTICE_PERIOD = "NOTICE_PERIOD"
    ECA_ELIGIBLE = "ECA_ELIGIBLE"
    ECA_ACTIVE = "ECA_ACTIVE"
    ASSISTANCE_HOLD = "ASSISTANCE_HOLD"
    RESOLVED = "RESOLVED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CHECK = "CHECK"
    ACH = "ACH"
    CASH = "CASH"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    FULLY_REFUNDED = "FULLY_REFUNDED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    PENDING_DOCUMENTS = "PENDING_DOCUMENTS"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class ScreeningSource(str, Enum):
    STANDARD = "STANDARD"
    PRESUMPTIVE = "PRESUMPTIVE"


class Relationship(str, Enum):
    SELF = "SELF"
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    OTHER_DEPENDENT = "OTHER_DEPENDENT"


class DocType(str, Enum):
    PAY_STUB = "PAY_STUB"
    TAX_RETURN = "TAX_RETURN"
    BENEFIT_LETTER = "BENEFIT_LETTER"
    BANK_STATEMENT = "BANK_STATEMENT"
    IDENTITY = "IDENTITY"


class DocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ScreeningOutcome(str, Enum):
    ELIGIBLE_FULL = "ELIGIBLE_FULL"
    ELIGIBLE_PARTIAL = "ELIGIBLE_PARTIAL"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class DeterminationBasis(str, Enum):
    VERIFIED_APPLICATION = "VERIFIED_APPLICATION"
    PRESUMPTIVE_SCORE = "PRESUMPTIVE_SCORE"


class DeterminationTier(str, Enum):
    TIER_FULL = "TIER_FULL"
    TIER_PARTIAL = "TIER_PARTIAL"
    INELIGIBLE = "INELIGIBLE"


class DeterminationStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"
    REVERSED = "REVERSED"


class AdjustmentType(str, Enum):
    WRITE_OFF = "WRITE_OFF"
    REFUND = "REFUND"


class AdjustmentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class NoticeType(str, Enum):
    FIRST_STATEMENT = "FIRST_STATEMENT"
    PLAIN_LANGUAGE_SUMMARY = "PLAIN_LANGUAGE_SUMMARY"
    ECA_WARNING = "ECA_WARNING"
    DETERMINATION_LETTER = "DETERMINATION_LETTER"
    DOC_REQUEST = "DOC_REQUEST"


class DeliveryChannel(str, Enum):
    MAIL = "MAIL"
    PORTAL = "PORTAL"
    EMAIL = "EMAIL"


class CollectionActionType(str, Enum):
    CREDIT_REPORT = "CREDIT_REPORT"
    LAWSUIT = "LAWSUIT"
    WAGE_GARNISHMENT = "WAGE_GARNISHMENT"
    LIEN = "LIEN"
    SALE_TO_AGENCY = "SALE_TO_AGENCY"


class CollectionActionStatus(str, Enum):
    INITIATED = "INITIATED"
    HALTED = "HALTED"
    COMPLETED = "COMPLETED"


class ReportStatus(str, Enum):
    OPEN = "OPEN"
    FILED = "FILED"
    REOPENED = "REOPENED"


# ─── Entity TypedDicts ────────────────────────────────
# Resources with the full common property set (PRD §2.5) carry
# id + created_at + updated_at + version. HouseholdMember,
# PresumptiveScreening, and NotificationRecord carry only id + created_at.

class FinancialAssistancePolicy(TypedDict, total=False):
    id: str
    policy_code: str
    fpl_base_cents: int
    fpl_increment_cents: int
    full_discount_max_fpl_pct: int
    partial_discount_max_fpl_pct: int
    partial_discount_floor_pct: float
    asset_limit_cents: int
    retroactive_window_days: int
    notification_period_days: int
    eca_notice_days: int
    doc_response_days: int
    presumptive_partial_score_threshold: float
    presumptive_full_score_threshold: float
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    ssn_last4: str
    mrn: str
    contact_email: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PatientAccount(TypedDict, total=False):
    id: str
    patient_id: str
    encounter_date: str
    total_charges_cents: int
    insurance_paid_cents: int
    patient_responsibility_cents: int
    adjusted_balance_cents: int
    effective_payments_cents: int
    amount_outstanding_cents: int
    overpayment_cents: int
    first_statement_at: Optional[str]
    collection_posture: str
    created_at: str
    updated_at: str
    version: int


class AccountPayment(TypedDict, total=False):
    id: str
    account_id: str
    amount_cents: int
    paid_at: str
    method: str
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AssistanceApplication(TypedDict, total=False):
    id: str
    patient_id: str
    screening_source: str
    reported_annual_income_cents: int
    reported_liquid_assets_cents: int
    policy_id: Optional[str]
    policy_version: Optional[int]
    household_size: int
    annualized_verified_income_cents: int
    verified_liquid_assets_cents: int
    requested_doc_types: List[str]
    doc_response_deadline: Optional[str]
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; carries ONLY id + created_at
class HouseholdMember(TypedDict, total=False):
    id: str
    application_id: str
    full_name: str
    relationship: str
    age: int
    created_at: str


class VerificationDocument(TypedDict, total=False):
    id: str
    application_id: str
    household_member_id: Optional[str]
    doc_type: str
    period_start: str
    period_end: str
    amount_cents: int
    rejection_reason: Optional[str]
    verified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at
class PresumptiveScreening(TypedDict, total=False):
    id: str
    application_id: str
    income_band_score: Optional[int]
    payment_history_score: Optional[int]
    utilization_score: Optional[int]
    public_benefit_score: Optional[int]
    housing_stability_score: Optional[int]
    present_factor_count: int
    thin_file: bool
    propensity_score: float
    outcome: str
    screened_by_user_id: str
    model_version: str
    created_at: str


class DiscountDetermination(TypedDict, total=False):
    id: str
    application_id: str
    basis: str
    covered_account_ids: List[str]
    policy_id: str
    policy_version: int
    fpl_pct_snapshot: Optional[float]
    tier: str
    discount_pct: float
    decided_by_user_id: Optional[str]
    finalized_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccountAdjustment(TypedDict, total=False):
    id: str
    account_id: str
    determination_id: str
    adjustment_type: str
    amount_cents: int
    payment_id: Optional[str]
    reversed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — carries ONLY id + created_at
class NotificationRecord(TypedDict, total=False):
    id: str
    account_id: Optional[str]
    application_id: Optional[str]
    notice_type: str
    delivery_channel: str
    is_plain_language: bool
    issued_at: str
    created_at: str


class CollectionAction(TypedDict, total=False):
    id: str
    account_id: str
    action_type: str
    initiated_at: str
    initiated_by_user_id: str
    halted_at: Optional[str]
    halt_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommunityBenefitReport(TypedDict, total=False):
    id: str
    reporting_year: int
    total_write_offs_cents: int
    total_standard_write_offs_cents: int
    total_presumptive_write_offs_cents: int
    total_refunds_cents: int
    accounts_assisted_count: int
    totals_stale: bool
    filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
