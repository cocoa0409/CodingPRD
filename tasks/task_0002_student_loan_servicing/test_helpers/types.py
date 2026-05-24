"""Domain types: entity TypedDicts, status enums, role enum.

All primary entities (Borrower, Loan, RepaymentPlan, Payment, EmploymentCertification,
PSLFTracker, DischargeApplication) carry id + created_at + updated_at + version.
ServicingEvent and DelinquencyRecord are immutable event records carrying only
id + created_at (no updated_at, no version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status Enums ─────────────────────────────────────

class LoanStatus(str, Enum):
    IN_SCHOOL = "IN_SCHOOL"
    GRACE = "GRACE"
    REPAYMENT = "REPAYMENT"
    DEFERMENT = "DEFERMENT"
    FORBEARANCE = "FORBEARANCE"
    DELINQUENT = "DELINQUENT"
    PAID_OFF = "PAID_OFF"
    DEFAULT = "DEFAULT"
    DISCHARGED = "DISCHARGED"


class LoanType(str, Enum):
    DIRECT_SUBSIDIZED = "DIRECT_SUBSIDIZED"
    DIRECT_UNSUBSIDIZED = "DIRECT_UNSUBSIDIZED"
    DIRECT_PLUS = "DIRECT_PLUS"


class BorrowerStatus(str, Enum):
    CURRENT = "CURRENT"
    AT_RISK = "AT_RISK"
    IN_DEFAULT = "IN_DEFAULT"
    CLEARED = "CLEARED"


class MilitaryStatus(str, Enum):
    NONE = "NONE"
    ACTIVE_DUTY = "ACTIVE_DUTY"
    VETERAN = "VETERAN"
    DISABLED_VETERAN = "DISABLED_VETERAN"


class RepaymentPlanType(str, Enum):
    STANDARD_10YR = "STANDARD_10YR"
    IBR = "IBR"
    PAYE = "PAYE"
    SAVE = "SAVE"


class RepaymentPlanStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class StateOfResidence(str, Enum):
    CONTIGUOUS = "CONTIGUOUS"
    AK = "AK"
    HI = "HI"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PaymentSource(str, Enum):
    ACH = "ACH"
    CHECK = "CHECK"
    PAYROLL_DEDUCT = "PAYROLL_DEDUCT"
    EMPLOYER_BENEFIT = "EMPLOYER_BENEFIT"
    TREASURY_OFFSET = "TREASURY_OFFSET"


class ServicingEventType(str, Enum):
    GRACE_BEGIN = "GRACE_BEGIN"
    REPAYMENT_BEGIN = "REPAYMENT_BEGIN"
    DEFERMENT_BEGIN = "DEFERMENT_BEGIN"
    DEFERMENT_END = "DEFERMENT_END"
    FORBEARANCE_BEGIN = "FORBEARANCE_BEGIN"
    FORBEARANCE_END = "FORBEARANCE_END"
    DELINQUENT_BEGIN = "DELINQUENT_BEGIN"
    REPAYMENT_RESUME = "REPAYMENT_RESUME"
    DEFAULT_DECLARED = "DEFAULT_DECLARED"
    CAPITALIZATION = "CAPITALIZATION"
    RECERTIFY_IDR = "RECERTIFY_IDR"


class ServicingReasonCode(str, Enum):
    SCHOOL_ENROLLMENT = "SCHOOL_ENROLLMENT"
    ECONOMIC_HARDSHIP = "ECONOMIC_HARDSHIP"
    MILITARY_SERVICE = "MILITARY_SERVICE"
    MEDICAL = "MEDICAL"
    NATURAL_DISASTER = "NATURAL_DISASTER"
    ADMIN_FORBEARANCE = "ADMIN_FORBEARANCE"
    GRACE_EXPIRY = "GRACE_EXPIRY"
    MISSED_PAYMENTS_270D = "MISSED_PAYMENTS_270D"
    IDR_ANNUAL_RECERT = "IDR_ANNUAL_RECERT"
    OTHER = "OTHER"


class EmployerType(str, Enum):
    GOVERNMENT_FEDERAL = "GOVERNMENT_FEDERAL"
    GOVERNMENT_STATE_LOCAL_TRIBAL = "GOVERNMENT_STATE_LOCAL_TRIBAL"
    NONPROFIT_501C3 = "NONPROFIT_501C3"
    OTHER_NONPROFIT_QUALIFYING = "OTHER_NONPROFIT_QUALIFYING"
    FOR_PROFIT = "FOR_PROFIT"
    NOT_QUALIFYING = "NOT_QUALIFYING"


class EmploymentCertificationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PSLFTrackerStatus(str, Enum):
    TRACKING = "TRACKING"
    ELIGIBLE_FOR_FORGIVENESS = "ELIGIBLE_FOR_FORGIVENESS"
    FORGIVEN = "FORGIVEN"
    DENIED = "DENIED"


class DischargeType(str, Enum):
    VETERAN_TOTAL_PERMANENT_DISABILITY = "VETERAN_TOTAL_PERMANENT_DISABILITY"
    PSLF_FORGIVENESS = "PSLF_FORGIVENESS"
    DEATH = "DEATH"
    CLOSED_SCHOOL = "CLOSED_SCHOOL"


class DischargeApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DelinquencyOutcome(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    FORBORNE = "FORBORNE"
    DEFAULTED = "DEFAULTED"


class UserRole(str, Enum):
    BORROWER = "Borrower"
    LOAN_SERVICER = "LoanServicer"
    PSLF_ADJUDICATOR = "PSLFAdjudicator"
    VA_DISCHARGE_OFFICER = "VADischargeOfficer"


# ─── Entity TypedDicts ────────────────────────────────
# Mutable entities carry id + created_at + updated_at + version.


class Borrower(TypedDict, total=False):
    id: str
    ssn_last4: str
    full_name: str
    date_of_birth: str
    email: str
    military_status: str
    aggregate_outstanding_principal_cents: int
    borrower_status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    borrower_id: str
    loan_type: str
    original_principal_cents: int
    outstanding_principal_cents: int
    accrued_interest_cents: int
    interest_rate_bps: int
    disbursement_date: str
    status: str
    subsidy_active: bool
    days_delinquent: int
    capitalized_interest_cents: int
    created_at: str
    updated_at: str
    version: int


class RepaymentPlan(TypedDict, total=False):
    id: str
    loan_id: str
    plan_type: str
    agi_cents: Optional[int]
    family_size: Optional[int]
    state_of_residence: str
    monthly_payment_cents: int
    status: str
    certification_expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    loan_id: str
    amount_cents: int
    posted_on: str
    source: str
    applied_to_interest_cents: int
    applied_to_principal_cents: int
    applied_to_fees_cents: int
    status: str
    recorded_by_user_id: str
    pslf_qualifying: bool
    created_at: str
    updated_at: str
    version: int


class EmploymentCertification(TypedDict, total=False):
    id: str
    borrower_id: str
    employer_ein: str
    employer_type: str
    period_start_on: str
    period_end_on: str
    weekly_hours: float
    status: str
    pslf_qualifying_employer: bool
    created_at: str
    updated_at: str
    version: int


class PSLFTracker(TypedDict, total=False):
    id: str
    borrower_id: str
    qualifying_payment_count: int
    required_payment_count: int
    status: str
    last_recount_on: str
    created_at: str
    updated_at: str
    version: int


class DischargeApplication(TypedDict, total=False):
    id: str
    borrower_id: str
    discharge_type: str
    va_certification_doc_id: Optional[str]
    filed_on: str
    status: str
    approved_by_user_id: Optional[str]
    total_discharged_principal_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only event records — only id + created_at, no updated_at, no version
# (per PRD §2.4).

class ServicingEvent(TypedDict, total=False):
    id: str
    loan_id: str
    event_type: str
    effective_on: str
    reason_code: str
    created_by_user_id: str
    created_at: str


class DelinquencyRecord(TypedDict, total=False):
    id: str
    loan_id: str
    opened_on: str
    closed_on: Optional[str]
    cumulative_days: int
    outcome: str
    created_at: str
