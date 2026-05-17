"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 common-fields split:

- Borrower, Loan, Payment, Disbursement, ForbearancePlan,
  PmiRemovalRequest, ForeclosureCase, MediationCase all carry id +
  created_at + updated_at + version. (PRD §2.4: "All resources except
  EscrowAnalysis additionally carry an updated_at timestamp ... and an
  integer version that starts at 1 on creation and increases by exactly
  1 on each mutation.")

- EscrowAnalysis is an immutable snapshot once FINALIZED — it carries
  ONLY id + created_at (no updated_at, no version). (PRD §2.4:
  "EscrowAnalysis is an immutable snapshot once it has been finalised,
  and therefore exposes only id and created_at; it has neither
  updated_at nor version.")
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BORROWER = "Borrower"
    SERVICER = "Servicer"
    LOSS_MITIGATION_UNDERWRITER = "LossMitigationUnderwriter"
    PMI_UNDERWRITER = "PmiUnderwriter"
    FORECLOSURE_ATTORNEY = "ForeclosureAttorney"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Loan posture — PRD §3.4
# ---------------------------------------------------------------------------
class LoanPosture(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    FORBEARANCE = "FORBEARANCE"
    DEFAULT = "DEFAULT"
    FORECLOSURE = "FORECLOSURE"
    REINSTATED = "REINSTATED"
    PAID_OFF = "PAID_OFF"


class PmiStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVAL_REQUESTED = "REMOVAL_REQUESTED"
    REMOVED = "REMOVED"
    AUTO_TERMINATED = "AUTO_TERMINATED"


# ---------------------------------------------------------------------------
# Payment — PRD §3.2
# ---------------------------------------------------------------------------
class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# EscrowAnalysis — PRD §3.3
# ---------------------------------------------------------------------------
class EscrowAnalysisStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Disbursement — PRD §3.3
# ---------------------------------------------------------------------------
class DisbursementType(str, Enum):
    PROPERTY_TAX = "PROPERTY_TAX"
    HAZARD_INSURANCE = "HAZARD_INSURANCE"
    SURPLUS_REFUND = "SURPLUS_REFUND"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class DisbursementFailureReason(str, Enum):
    INSUFFICIENT_ESCROW = "INSUFFICIENT_ESCROW"


# ---------------------------------------------------------------------------
# ForbearancePlan — PRD §3.4
# ---------------------------------------------------------------------------
class ForbearanceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    BREACHED = "BREACHED"
    CANCELED = "CANCELED"


class ForbearanceRepaymentMethod(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    REPAYMENT_PLAN_12M = "REPAYMENT_PLAN_12M"
    DEFERRAL = "DEFERRAL"


# ---------------------------------------------------------------------------
# PMI removal — PRD §3.5
# ---------------------------------------------------------------------------
class PmiRemovalTrigger(str, Enum):
    BORROWER_REQUEST = "BORROWER_REQUEST"
    AUTO_TERMINATION = "AUTO_TERMINATION"


class PmiRemovalDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PmiDenialReason(str, Enum):
    LTV_TOO_HIGH = "LTV_TOO_HIGH"
    PAYMENT_HISTORY_INSUFFICIENT = "PAYMENT_HISTORY_INSUFFICIENT"
    LOAN_NOT_CURRENT = "LOAN_NOT_CURRENT"


# ---------------------------------------------------------------------------
# ForeclosureCase — PRD §3.6
# ---------------------------------------------------------------------------
class ForeclosureStatus(str, Enum):
    NOI_ISSUED = "NOI_ISSUED"
    MEDIATION_OPEN = "MEDIATION_OPEN"
    FILED = "FILED"
    AUCTION_SCHEDULED = "AUCTION_SCHEDULED"
    CLOSED_REINSTATED = "CLOSED_REINSTATED"
    CLOSED_MODIFIED = "CLOSED_MODIFIED"
    CLOSED_SOLD = "CLOSED_SOLD"


# ---------------------------------------------------------------------------
# MediationCase — PRD §3.7
# ---------------------------------------------------------------------------
class MediationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    OPEN = "OPEN"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_REJECTED = "OFFER_REJECTED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"


class MediationRejectionReason(str, Enum):
    DTI_TOO_HIGH = "DTI_TOO_HIGH"
    AFFORDABILITY_FLOOR = "AFFORDABILITY_FLOOR"
    BORROWER_REFUSED = "BORROWER_REFUSED"


# ===========================================================================
# Top-level resources (common_fields: true) — PRD §2.4
# Carry id + created_at + updated_at + version.
# ===========================================================================
class Borrower(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    hardship_attested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    borrower_id: str
    origination_date: str
    original_principal_cents: int
    original_appraised_value_cents: int
    interest_rate_bps: int
    term_months: int
    scheduled_payment_cents: int
    principal_balance_cents: int
    escrow_balance_cents: int
    monthly_escrow_payment_cents: int
    pmi_monthly_cents: int
    pmi_status: str
    next_due_date: str
    posture: str
    delinquency_days: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    loan_id: str
    received_date: str
    amount_cents: int
    allocation_principal_cents: int
    allocation_interest_cents: int
    allocation_escrow_cents: int
    allocation_late_fee_cents: int
    allocation_suspense_cents: int
    status: str
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    loan_id: str
    type: str
    scheduled_date: str
    amount_cents: int
    status: str
    paid_at: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ForbearancePlan(TypedDict, total=False):
    id: str
    loan_id: str
    start_date: str
    months: int
    end_date: str
    total_paused_cents: int
    repayment_method: str
    status: str
    cure_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class PmiRemovalRequest(TypedDict, total=False):
    id: str
    loan_id: str
    trigger: str
    current_appraised_value_cents: Optional[int]
    evaluated_ltv_bps: int
    decision: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ForeclosureCase(TypedDict, total=False):
    id: str
    loan_id: str
    opened_at: str
    status: str
    noi_sent_at: str
    filed_at: Optional[str]
    auction_date: Optional[str]
    reinstatement_quote_cents: int
    foreclosure_costs_cents: int
    created_at: str
    updated_at: str
    version: int


class MediationCase(TypedDict, total=False):
    id: str
    foreclosure_case_id: str
    opened_at: Optional[str]
    status: str
    offered_new_rate_bps: Optional[int]
    offered_term_extension_months: Optional[int]
    offered_principal_forbearance_cents: int
    target_payment_cents: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Immutable snapshot — PRD §2.4: EscrowAnalysis carries ONLY id + created_at
# ===========================================================================
class EscrowAnalysis(TypedDict, total=False):
    id: str
    loan_id: str
    analysis_date: str
    status: str
    projected_disbursements_cents: int
    required_cushion_cents: int
    starting_balance_cents: int
    shortage_cents: int
    surplus_cents: int
    new_monthly_escrow_cents: int
    finalized_at: Optional[str]
    created_at: str
    # NO updated_at, NO version — PRD §2.4


__all__ = [
    "UserRole",
    "LoanPosture",
    "PmiStatus",
    "PaymentStatus",
    "EscrowAnalysisStatus",
    "DisbursementType",
    "DisbursementStatus",
    "DisbursementFailureReason",
    "ForbearanceStatus",
    "ForbearanceRepaymentMethod",
    "PmiRemovalTrigger",
    "PmiRemovalDecision",
    "PmiDenialReason",
    "ForeclosureStatus",
    "MediationStatus",
    "MediationRejectionReason",
    "Borrower",
    "Loan",
    "Payment",
    "Disbursement",
    "ForbearancePlan",
    "PmiRemovalRequest",
    "ForeclosureCase",
    "MediationCase",
    "EscrowAnalysis",
]
