"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §3 (entities) and §3.2/§3.3/§3.4/§3.5/§3.6/§3.7/§3.8/§3.9/§3.10
(state machines). UDAAPCheck is append-only per PRD §2.4 — only id and created_at
are surfaced (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------
class LoanApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    PREQUALIFIED = "PREQUALIFIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CLEAR_TO_CLOSE = "CLEAR_TO_CLOSE"
    CLOSED = "CLOSED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class PrequalDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class IncomeVerificationStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AssetVerificationStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AppraisalStatus(str, Enum):
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"
    RECONSIDERED = "RECONSIDERED"


class TitleSearchStatus(str, Enum):
    ORDERED = "ORDERED"
    CLEAR = "CLEAR"
    EXCEPTIONS_FOUND = "EXCEPTIONS_FOUND"
    CURED = "CURED"


class RateLockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUPERSEDED = "SUPERSEDED"


class DisclosureType(str, Enum):
    LOAN_ESTIMATE = "LOAN_ESTIMATE"
    CLOSING_DISCLOSURE = "CLOSING_DISCLOSURE"


class LoanPurpose(str, Enum):
    PURCHASE = "PURCHASE"
    REFINANCE = "REFINANCE"


class DocumentType(str, Enum):
    W2 = "W2"
    PAYSTUB = "PAYSTUB"
    TAX_RETURN = "TAX_RETURN"
    BANK_DEPOSITS = "BANK_DEPOSITS"


class AssetType(str, Enum):
    CHECKING = "CHECKING"
    SAVINGS = "SAVINGS"
    BROKERAGE = "BROKERAGE"
    RETIREMENT = "RETIREMENT"


class UDAAPReviewOutcome(str, Enum):
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class UDAAPFlagReason(str, Enum):
    HIDDEN_FEES = "HIDDEN_FEES"
    MISLEADING_RATE = "MISLEADING_RATE"
    STEERING = "STEERING"
    PRESSURE_TACTICS = "PRESSURE_TACTICS"


class UserRole(str, Enum):
    LOAN_OFFICER = "LoanOfficer"
    UNDERWRITER = "Underwriter"
    CLOSER = "Closer"
    APPRAISER = "Appraiser"
    TITLE_AGENT = "TitleAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    APPLICANT = "Applicant"


# ---------------------------------------------------------------------
# Entity TypedDicts — common-field carriers (id, created_at, updated_at, version)
# ---------------------------------------------------------------------
class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    ssn_last4: str
    annual_income_cents: int
    monthly_debt_cents: int
    credit_score: int
    state_code: str
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict, total=False):
    id: str
    applicant_id: str
    property_address: str
    property_state_code: str
    loan_purpose: str
    requested_loan_amount_cents: int
    property_value_cents: int
    loan_term_months: int
    status: str
    prequal_decision: Optional[str]
    front_end_dti: Optional[float]
    back_end_dti: Optional[float]
    ltv_ratio: Optional[float]
    provisional_apr: Optional[float]
    final_apr: Optional[float]
    clear_to_close_at: Optional[str]
    earliest_consummation_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncomeVerification(TypedDict, total=False):
    id: str
    application_id: str
    document_type: str
    verified_annual_income_cents: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssetVerification(TypedDict, total=False):
    id: str
    application_id: str
    asset_type: str
    verified_balance_cents: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict, total=False):
    id: str
    application_id: str
    appraised_value_cents: Optional[int]
    status: str
    reconsideration_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TitleSearch(TypedDict, total=False):
    id: str
    application_id: str
    status: str
    exception_summary: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateLock(TypedDict, total=False):
    id: str
    application_id: str
    locked_rate_bps: int
    lock_term_days: int
    locked_at: str
    expires_at: str
    extension_count: int
    extension_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Disclosure(TypedDict, total=False):
    id: str
    application_id: str
    disclosure_type: str
    status: str
    delivered_at: Optional[str]
    acknowledged_at: Optional[str]
    apr_at_issuance: Optional[float]
    change_requires_redisclose: bool
    earliest_consummation_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------
# Append-only entity (PRD §2.4) — no updated_at, no version
# ---------------------------------------------------------------------
class UDAAPCheck(TypedDict, total=False):
    id: str
    application_id: str
    review_outcome: str
    flagged_reasons: List[str]
    reviewer_user_id: str
    created_at: str
