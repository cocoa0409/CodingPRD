"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entities and lifecycle states described in the Student Loan Refi PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums (lifecycle states)
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PREQUALIFIED = "PREQUALIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class OfferStatus(str, Enum):
    PRESENTED = "PRESENTED"
    LOCKED = "LOCKED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class CosignerConsentStatus(str, Enum):
    INVITED = "INVITED"
    CONSENTED = "CONSENTED"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"


class LoanRepaymentStatus(str, Enum):
    CURRENT = "CURRENT"
    FORBEARANCE = "FORBEARANCE"
    DELINQUENT = "DELINQUENT"
    PAID_OFF = "PAID_OFF"
    CHARGED_OFF = "CHARGED_OFF"


class CosignerReleaseStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    RELEASED = "RELEASED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SENT = "SENT"
    CONFIRMED = "CONFIRMED"
    RETURNED = "RETURNED"


class ForbearancePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class AbsPoolStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FicoBand(str, Enum):
    SUBPRIME = "SUBPRIME"
    NEAR_PRIME = "NEAR_PRIME"
    PRIME = "PRIME"
    SUPER_PRIME = "SUPER_PRIME"


class MemberTier(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class RateType(str, Enum):
    FIXED = "FIXED"
    VARIABLE = "VARIABLE"


class AllowedRateType(str, Enum):
    FIXED = "FIXED"
    VARIABLE = "VARIABLE"
    ANY = "ANY"


class ReasonCode(str, Enum):
    JOB_LOSS = "JOB_LOSS"
    MEDICAL = "MEDICAL"
    NATURAL_DISASTER = "NATURAL_DISASTER"
    OTHER = "OTHER"


class AuditSubjectType(str, Enum):
    APPLICATION = "APPLICATION"
    LOAN = "LOAN"
    COSIGNER = "COSIGNER"
    DISBURSEMENT = "DISBURSEMENT"


class UserRole(str, Enum):
    BORROWER = "Borrower"
    COSIGNER = "Cosigner"
    UNDERWRITER = "Underwriter"
    DISBURSEMENT_OFFICER = "DisbursementOfficer"
    SERVICING_AGENT = "ServicingAgent"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true -> id + created_at + updated_at + version
class Borrower(TypedDict):
    id: str
    email: str
    full_name: str
    annual_income_cents: int
    fico_band: str
    member_tier: str
    created_at: str
    updated_at: str
    version: int


class AbsPool(TypedDict):
    id: str
    pool_code: str
    max_principal_cents: int
    min_fico_band: str
    allowed_rate_type: str
    committed_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only, carries ONLY id + created_at
class RateGridEntry(TypedDict):
    id: str
    rate_type: str
    term_months: int
    min_fico_band: str
    base_apr_bps: int
    index_apr_bps: int
    created_at: str


class Application(TypedDict):
    id: str
    borrower_id: str
    requested_principal_cents: int
    requested_term_months: int
    requested_rate_type: str
    soft_pull_fico_band: Optional[str]
    dti_ratio: Optional[float]
    status: str
    approved_underwriter_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    application_id: str
    rate_grid_entry_index: int
    term_months: int
    rate_type: str
    estimated_apr_bps: int
    locked_apr_bps: Optional[int]
    autopay_elected: bool
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Cosigner(TypedDict):
    id: str
    application_id: str
    cosigner_email: str
    cosigner_annual_income_cents: int
    consent_status: str
    on_time_streak: int
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    application_id: str
    offer_id: str
    abs_pool_id: Optional[str]
    original_principal_cents: int
    principal_balance_cents: int
    accrued_interest_cents: int
    last_accrual_at: str
    locked_apr_bps: int
    term_months: int
    repayment_status: str
    cosigner_release_status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    loan_id: str
    prior_servicer_name: str
    payoff_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    loan_id: str
    amount_cents: int
    due_date: str
    paid_at: str
    on_time: bool
    interest_portion_cents: int
    principal_portion_cents: int
    created_at: str
    updated_at: str
    version: int


class ForbearancePlan(TypedDict):
    id: str
    loan_id: str
    reason_code: str
    months_requested: int
    interest_capitalized_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only, carries ONLY id + created_at
class AuditEvent(TypedDict):
    id: str
    subject_type: str
    subject_id: str
    action: str
    actor_role: str
    actor_user_id: str
    created_at: str
