"""Domain types: entity TypedDicts, status enums, role enum.

Field names and shapes mirror the PRD exactly. Append-only audit records
(MIBCheck, PremiumPayment, CashValueEntry) carry only id + created_at — they
have neither updated_at nor version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    ADMIN = "Admin"
    UNDERWRITER = "Underwriter"
    POLICY_OWNER = "PolicyOwner"


# ─── Status enums ─────────────────────────────────────
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    EXAM_PENDING = "EXAM_PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED_OFFER = "APPROVED_OFFER"
    POSTPONED = "POSTPONED"
    DECLINED = "DECLINED"
    ISSUED = "ISSUED"
    EXPIRED = "EXPIRED"


class ParamedExamStatus(str, Enum):
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MIBResult(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"


class RiskClass(str, Enum):
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    TABLE_1 = "TABLE_1"
    TABLE_2 = "TABLE_2"
    TABLE_3 = "TABLE_3"
    TABLE_4 = "TABLE_4"
    TABLE_5 = "TABLE_5"
    TABLE_6 = "TABLE_6"
    TABLE_7 = "TABLE_7"
    TABLE_8 = "TABLE_8"


class PolicyLifecycleStatus(str, Enum):
    IN_FORCE = "IN_FORCE"
    GRACE = "GRACE"
    LAPSED = "LAPSED"
    REINSTATED = "REINSTATED"
    TERMINATED = "TERMINATED"


class ContestabilityStatus(str, Enum):
    CONTESTABLE = "CONTESTABLE"
    INCONTESTABLE = "INCONTESTABLE"


class BeneficiaryDesignation(str, Enum):
    PRIMARY = "PRIMARY"
    CONTINGENT = "CONTINGENT"


class PolicyLoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPAID = "REPAID"


class Sex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class CashValueReason(str, Enum):
    PREMIUM_ACCRUAL = "PREMIUM_ACCRUAL"
    LOAN_REVERSAL = "LOAN_REVERSAL"
    LAPSE_FORFEIT = "LAPSE_FORFEIT"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ───
class Product(TypedDict):
    id: str
    code: str
    base_annual_rate_per_thousand_cents: int
    max_face_amount_cents: int
    cash_value_accrual_rate_bps: int
    contestability_months: int
    grace_period_days: int
    max_loan_to_cash_value_pct: int
    exam_validity_days: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    sex: str
    tobacco_use: bool
    email: str
    created_at: str
    updated_at: str
    version: int


class Underwriter(TypedDict):
    id: str
    name: str
    license_id: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    applicant_id: str
    product_id: str
    ordering_underwriter_id: Optional[str]
    deciding_underwriter_id: Optional[str]
    requested_face_amount_cents: int
    status: str
    offer_expires_at: Optional[str]
    provisional_annual_premium_cents: Optional[int]
    final_annual_premium_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ParamedExam(TypedDict):
    id: str
    application_id: str
    height_inches: int
    weight_pounds: int
    systolic_bp: int
    exam_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict):
    id: str
    application_id: str
    build_debits: int
    total_debits: int
    risk_class: str
    table_rating: int
    finalized: bool
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    application_id: str
    face_amount_cents: int
    annual_premium_cents: int
    issue_date: str
    lifecycle_status: str
    contestability_status: str
    next_premium_due_date: str
    cumulative_premium_paid_cents: int
    gross_cash_value_cents: int
    outstanding_loan_principal_cents: int
    net_cash_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict):
    id: str
    policy_id: str
    full_name: str
    designation: str
    share_pct: int
    created_at: str
    updated_at: str
    version: int


class PolicyLoan(TypedDict):
    id: str
    policy_id: str
    principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only audit records (common_fields: false → id + created_at only) ───
class MIBCheck(TypedDict):
    id: str
    application_id: str
    mib_hit: bool
    rx_flag_count: int
    result: str
    created_at: str


class PremiumPayment(TypedDict):
    id: str
    policy_id: str
    amount_cents: int
    paid_at: str
    applied_to_due_date: str
    coverage_period_start: str
    coverage_period_end: str
    created_at: str


class CashValueEntry(TypedDict):
    id: str
    policy_id: str
    amount_cents: int
    reason: str
    created_at: str
