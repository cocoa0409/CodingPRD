"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    REVENUE_OFFICER = "RevenueOfficer"
    CASE_REVIEWER = "CaseReviewer"


class CollectionStatus(str, Enum):
    ACTIVE_COLLECTION = "ACTIVE_COLLECTION"
    IN_AGREEMENT = "IN_AGREEMENT"
    CNC = "CNC"
    OIC_PENDING = "OIC_PENDING"
    RESOLVED = "RESOLVED"


class FilingStatus(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    BUSINESS = "BUSINESS"


class PeriodStatus(str, Enum):
    ASSESSED = "ASSESSED"
    IN_COLLECTION = "IN_COLLECTION"
    SATISFIED = "SATISFIED"
    WRITTEN_OFF = "WRITTEN_OFF"
    ABATED = "ABATED"


class SuspensionReason(str, Enum):
    AGREEMENT_PENDING = "AGREEMENT_PENDING"
    OIC_EVALUATION = "OIC_EVALUATION"
    MANUAL = "MANUAL"


class AgreementType(str, Enum):
    SHORT_TERM = "SHORT_TERM"
    LONG_TERM = "LONG_TERM"
    PPIA = "PPIA"


class PaymentMethod(str, Enum):
    DIRECT_DEBIT = "DIRECT_DEBIT"
    MANUAL = "MANUAL"


class AgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEFAULTED = "DEFAULTED"
    REINSTATED = "REINSTATED"
    CLOSED = "CLOSED"


class PaymentSource(str, Enum):
    DDIA_DEBIT = "DDIA_DEBIT"
    MANUAL = "MANUAL"
    OIC_LUMP_SUM = "OIC_LUMP_SUM"


class OfferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    EVALUATING = "EVALUATING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DEFAULTED = "DEFAULTED"


class LienStatus(str, Enum):
    FILED = "FILED"
    RELEASE_PENDING = "RELEASE_PENDING"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class CncStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class HardshipReason(str, Enum):
    NO_DISPOSABLE_INCOME = "NO_DISPOSABLE_INCOME"
    HARDSHIP = "HARDSHIP"
    UNABLE_TO_LOCATE = "UNABLE_TO_LOCATE"


class AccountEventType(str, Enum):
    CSED_SUSPEND_START = "CSED_SUSPEND_START"
    CSED_SUSPEND_END = "CSED_SUSPEND_END"
    AGREEMENT_DEFAULT = "AGREEMENT_DEFAULT"
    RECOMPUTE = "RECOMPUTE"
    MISSED_DEBIT = "MISSED_DEBIT"
    OIC_DECISION = "OIC_DECISION"


# --- Entities with common_fields: true (id + created_at + updated_at + version) ---

class TaxAccount(TypedDict):
    id: str
    taxpayer_name: str
    tin: str
    filing_status: str
    monthly_disposable_income_cents: int
    collection_status: str
    total_balance_cents: int
    csed_protection_count: int
    created_at: str
    updated_at: str
    version: int


class TaxPeriod(TypedDict):
    id: str
    tax_account_id: str
    tax_year: int
    assessed_tax_cents: int
    assessment_date: str
    csed_date: str
    penalty_accrued_cents: int
    interest_accrued_cents: int
    balance_due_cents: int
    paid_to_principal_cents: int
    period_status: str
    created_at: str
    updated_at: str
    version: int


class CsedSuspension(TypedDict):
    id: str
    tax_period_id: str
    reason: str
    start_at: str
    end_at: Optional[str]
    days_counted: int
    created_at: str
    updated_at: str
    version: int


class InstallmentAgreement(TypedDict):
    id: str
    tax_account_id: str
    active_from: str
    active_to: str
    agreement_type: str
    payment_method: str
    monthly_payment_cents: int
    setup_fee_cents: int
    low_income_flag: bool
    term_months: int
    status: str
    approved_by_user_id: Optional[str]
    missed_debit_count: int
    created_at: str
    updated_at: str
    version: int


class OfferInCompromise(TypedDict):
    id: str
    tax_account_id: str
    offer_amount_cents: int
    rcp_cents: int
    net_realizable_equity_cents: int
    status: str
    submitted_by_user_id: Optional[str]
    accepted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FederalTaxLien(TypedDict):
    id: str
    tax_account_id: str
    filed_amount_cents: int
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CncDetermination(TypedDict):
    id: str
    tax_account_id: str
    hardship_reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Entities with common_fields: false (id + created_at ONLY) ---

class Payment(TypedDict):
    id: str
    tax_account_id: str
    tax_period_id: Optional[str]
    amount_cents: int
    payment_source: str
    posted_at: str
    created_at: str


class AccountEvent(TypedDict):
    id: str
    tax_account_id: str
    event_type: str
    tax_period_id: Optional[str]
    suspension_days: int
    created_at: str
