"""Domain types: entity TypedDicts, status enums, role enum (PRD §1, §2.4)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ── Status enums ──────────────────────────────────────────────────────────

class LoanStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    FORBEARANCE = "FORBEARANCE"
    FORECLOSURE = "FORECLOSURE"
    REINSTATED = "REINSTATED"
    PAID_OFF = "PAID_OFF"


class PmiStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVAL_PENDING = "REMOVAL_PENDING"
    REMOVED = "REMOVED"
    AUTO_TERMINATED = "AUTO_TERMINATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    SUSPENSE = "SUSPENSE"
    REVERSED = "REVERSED"


class PostingStrategy(str, Enum):
    STANDARD_WATERFALL = "STANDARD_WATERFALL"
    PRINCIPAL_CURTAILMENT = "PRINCIPAL_CURTAILMENT"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class DisbursementKind(str, Enum):
    TAX = "TAX"
    INSURANCE = "INSURANCE"


class FailureReason(str, Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    NONE = "NONE"


class AnalysisVariant(str, Enum):
    ACTUAL_TRAILING_12 = "ACTUAL_TRAILING_12"
    FORECAST_NEXT_12 = "FORECAST_NEXT_12"


class ForbearanceStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED_EARLY = "TERMINATED_EARLY"


class ForeclosureStatus(str, Enum):
    FILED = "FILED"
    MEDIATION_REQUIRED = "MEDIATION_REQUIRED"
    IN_MEDIATION = "IN_MEDIATION"
    MEDIATION_FAILED = "MEDIATION_FAILED"
    SALE_SCHEDULED = "SALE_SCHEDULED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class MediationOutcome(str, Enum):
    PENDING = "PENDING"
    MODIFICATION_AGREED = "MODIFICATION_AGREED"
    FORBEARANCE_AGREED = "FORBEARANCE_AGREED"
    NO_AGREEMENT = "NO_AGREEMENT"


class PmiRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PmiDenialReason(str, Enum):
    LTV_TOO_HIGH = "LTV_TOO_HIGH"
    PAYMENT_HISTORY_NOT_CLEAN = "PAYMENT_HISTORY_NOT_CLEAN"
    IN_DELINQUENCY = "IN_DELINQUENCY"
    NONE = "NONE"


class UserRole(str, Enum):
    LOAN_SERVICER = "LoanServicer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BORROWER = "Borrower"


# ── Entity TypedDicts ─────────────────────────────────────────────────────
# Per PRD §2.4: every persisted resource carries id + created_at. Payment is
# the sole append-only row (no updated_at, no version); every other entity
# carries the full quartet id/created_at/updated_at/version.

class Borrower(TypedDict):
    id: str
    email: str
    full_name: str
    ssn_last4: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    borrower_id: str
    origination_date: str
    original_principal_cents: int
    original_property_value_cents: int
    current_appraised_value_cents: Optional[int]
    interest_rate_bps: int
    term_months: int
    scheduled_monthly_pi_cents: int
    principal_balance_cents: int
    accrued_interest_cents: int
    escrow_monthly_cents: int
    total_monthly_payment_cents: int
    status: str
    days_past_due: int
    next_due_date: str
    pmi_required: bool
    pmi_monthly_cents: int
    pmi_status: str
    last_payment_posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscrowAccount(TypedDict, total=False):
    id: str
    loan_id: str
    balance_cents: int
    annual_tax_cents: int
    annual_insurance_cents: int
    cushion_months: int
    shortage_cents: int
    surplus_cents: int
    created_at: str
    updated_at: str
    version: int


class PaymentAllocation(TypedDict, total=False):
    interest_cents: int
    principal_cents: int
    escrow_cents: int
    pmi_cents: int
    late_fee_cents: int
    suspense_cents: int


# Payment is append-only per PRD §2.4 — carries only id + created_at,
# plus its own event-immutable fields. No updated_at, no version.
class Payment(TypedDict, total=False):
    id: str
    loan_id: str
    amount_cents: int
    received_at: str
    posting_strategy: str
    allocation: PaymentAllocation
    status: str
    posted_at: str
    created_at: str


class EscrowDisbursement(TypedDict, total=False):
    id: str
    escrow_account_id: str
    kind: str
    amount_cents: int
    scheduled_for: str
    status: str
    failure_reason: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscrowAnalysis(TypedDict, total=False):
    id: str
    loan_id: str
    as_of_date: str
    variant: str
    projected_low_point_cents: int
    required_low_point_cents: int
    shortage_cents: int
    surplus_cents: int
    new_escrow_monthly_cents: int
    created_at: str
    updated_at: str
    version: int


class ForbearancePlan(TypedDict, total=False):
    id: str
    loan_id: str
    start_date: str
    end_date: str
    reduced_payment_cents: int
    deferred_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ForeclosureCase(TypedDict, total=False):
    id: str
    loan_id: str
    initiated_at: str
    status: str
    sale_date: Optional[str]
    cure_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class MediationSession(TypedDict, total=False):
    id: str
    foreclosure_case_id: str
    scheduled_for: str
    outcome: str
    modification_pi_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PMIRemovalRequest(TypedDict, total=False):
    id: str
    loan_id: str
    requested_at: str
    appraisal_value_cents: Optional[int]
    status: str
    denial_reason: str
    computed_ltv_bps: int
    created_at: str
    updated_at: str
    version: int
