"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 — common-fields entities (id, created_at, updated_at, version):
    Taxpayer, TaxLiability, InstallmentAgreement, OfferInCompromise,
    FederalTaxLien, CNCStatus, ReconsiderationRequest.

PRD §2.4 — append-only entities (id and created_at only; NO updated_at,
NO version):
    Payment, CSEDTollingEvent.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TAXPAYER = "Taxpayer"
    IRS_OFFICER = "IRSOfficer"
    OIC_OFFICER = "OICOfficer"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class TaxpayerFilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED_JOINT = "MARRIED_JOINT"
    MARRIED_SEPARATE = "MARRIED_SEPARATE"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"


class TaxpayerCollectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IN_AGREEMENT = "IN_AGREEMENT"
    IN_OIC_REVIEW = "IN_OIC_REVIEW"
    IN_COMPROMISE = "IN_COMPROMISE"
    CNC = "CNC"
    PAID_IN_FULL = "PAID_IN_FULL"


class TaxLiabilityStatus(str, Enum):
    OPEN = "OPEN"
    IN_AGREEMENT = "IN_AGREEMENT"
    IN_COMPROMISE = "IN_COMPROMISE"
    CNC = "CNC"
    EXPIRED = "EXPIRED"
    PAID = "PAID"


class InstallmentAgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"


class InstallmentAgreementType(str, Enum):
    SHORT_TERM = "SHORT_TERM"
    LONG_TERM = "LONG_TERM"
    PPIA = "PPIA"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    DDIA = "DDIA"
    PAYROLL_DEDUCTION = "PAYROLL_DEDUCTION"


class PaymentKind(str, Enum):
    INSTALLMENT = "INSTALLMENT"
    OIC_DEPOSIT = "OIC_DEPOSIT"
    OIC_INSTALLMENT = "OIC_INSTALLMENT"
    LUMP_SUM = "LUMP_SUM"


class OfferInCompromiseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class OICDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class FederalTaxLienStatus(str, Enum):
    FILED = "FILED"
    WITHDRAWN = "WITHDRAWN"
    RELEASED = "RELEASED"


class LienReleaseReason(str, Enum):
    PAID_IN_FULL = "PAID_IN_FULL"
    OIC_ACCEPTED = "OIC_ACCEPTED"
    CSED_EXPIRED = "CSED_EXPIRED"
    ADMIN_RELEASE = "ADMIN_RELEASE"


class CSEDTollingEventKind(str, Enum):
    OIC_PENDING = "OIC_PENDING"
    CNC_HARDSHIP = "CNC_HARDSHIP"
    INSTALLMENT_PENDING = "INSTALLMENT_PENDING"
    BANKRUPTCY = "BANKRUPTCY"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class ReconsiderationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReconsiderationReason(str, Enum):
    HARDSHIP = "HARDSHIP"
    INCOME_CHANGE = "INCOME_CHANGE"
    OIC_DENIED_REVERT = "OIC_DENIED_REVERT"
    MISSED_PAYMENT_CURE = "MISSED_PAYMENT_CURE"


class CNCStatusValue(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"
    EXPIRED = "EXPIRED"


class HardshipReason(str, Enum):
    UNEMPLOYMENT = "UNEMPLOYMENT"
    MEDICAL = "MEDICAL"
    NEGATIVE_DISPOSABLE_INCOME = "NEGATIVE_DISPOSABLE_INCOME"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common-fields entities (PRD §2.4)
# ---------------------------------------------------------------------------
class Taxpayer(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tin: str
    filing_status: str
    monthly_disposable_income_cents: int
    total_assessed_debt_cents: int
    collection_status: str


class TaxLiability(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    taxpayer_id: str
    tax_year: int
    assessment_date: str
    original_assessed_amount_cents: int
    accrued_interest_cents: int
    accrued_penalty_cents: int
    payments_applied_cents: int
    current_balance_cents: int
    csed_base_date: str
    csed_effective_date: str
    status: str
    last_accrual_cycle_date: Optional[str]


class InstallmentAgreement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    taxpayer_id: str
    liability_ids: List[str]
    agreement_type: str
    proposed_monthly_payment_cents: int
    payment_method: str
    ddia_bank_account_last4: Optional[str]
    next_due_date: Optional[str]
    planned_payoff_date: Optional[str]
    missed_payment_count: int
    status: str


class OfferInCompromise(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    taxpayer_id: str
    liability_ids: List[str]
    offer_amount_cents: int
    deposit_paid_cents: int
    rcp_cents: int
    status: str
    decision_officer_id: Optional[str]
    submitted_at: Optional[str]


class FederalTaxLien(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    taxpayer_id: str
    liability_ids: List[str]
    filed_date: str
    status: str
    released_at: Optional[str]
    release_reason: Optional[str]


class CNCStatus(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    taxpayer_id: str
    liability_ids: List[str]
    hardship_reason: str
    effective_date: str
    review_due_date: str
    status: str


class ReconsiderationRequest(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    agreement_id: str
    prior_request_id: Optional[str]
    reason: str
    status: str
    decision_officer_id: Optional[str]


# ---------------------------------------------------------------------------
# Append-only entities (PRD §2.4 — only id + created_at)
# ---------------------------------------------------------------------------
class PaymentAllocationRow(TypedDict):
    liability_id: str
    applied_cents: int


class Payment(TypedDict, total=False):
    id: str
    created_at: str
    agreement_id: Optional[str]
    taxpayer_id: str
    amount_cents: int
    received_at: str
    payment_kind: str
    allocation: List[PaymentAllocationRow]
    # NOTE: PRD §2.4 — no updated_at, no version on Payment.


class CSEDTollingEvent(TypedDict, total=False):
    id: str
    created_at: str
    liability_id: str
    event_kind: str
    start_date: str
    end_date: Optional[str]
    source_ref: Optional[str]
    # NOTE: PRD §2.4 — no updated_at, no version on CSEDTollingEvent.


__all__ = [
    "UserRole",
    "TaxpayerFilingStatus",
    "TaxpayerCollectionStatus",
    "TaxLiabilityStatus",
    "InstallmentAgreementStatus",
    "InstallmentAgreementType",
    "PaymentMethod",
    "PaymentKind",
    "OfferInCompromiseStatus",
    "OICDecision",
    "FederalTaxLienStatus",
    "LienReleaseReason",
    "CSEDTollingEventKind",
    "ReconsiderationStatus",
    "ReconsiderationReason",
    "CNCStatusValue",
    "HardshipReason",
    "Taxpayer",
    "TaxLiability",
    "InstallmentAgreement",
    "OfferInCompromise",
    "FederalTaxLien",
    "CNCStatus",
    "ReconsiderationRequest",
    "PaymentAllocationRow",
    "Payment",
    "CSEDTollingEvent",
]
