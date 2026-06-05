"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the full system-managed quartet
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────

class TrustStatus(str, Enum):
    DRAFT = "DRAFT"
    FUNDED = "FUNDED"
    ACTIVE = "ACTIVE"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"
    REVOKED = "REVOKED"


class TrusteeAppointmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"


class TrustAccountStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FILED = "FILED"


class DistributionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class TaxFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    AMENDED = "AMENDED"
    SUPERSEDED = "SUPERSEDED"


class GstExemptionAllocationStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    RELEASED = "RELEASED"


# ─── Enumerated value sets ────────────────────────────────────

class TrustType(str, Enum):
    REVOCABLE = "REVOCABLE"
    IRREVOCABLE = "IRREVOCABLE"


class ReceiptKind(str, Enum):
    INTEREST = "INTEREST"
    DIVIDEND_ORDINARY = "DIVIDEND_ORDINARY"
    DIVIDEND_QUALIFIED = "DIVIDEND_QUALIFIED"
    CAPITAL_GAIN = "CAPITAL_GAIN"
    CONTRIBUTION = "CONTRIBUTION"


class ExpenseKind(str, Enum):
    TRUSTEE_FEE = "TRUSTEE_FEE"
    INVESTMENT_FEE = "INVESTMENT_FEE"
    TAX_PAYMENT = "TAX_PAYMENT"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class DistributionKind(str, Enum):
    MANDATORY = "MANDATORY"
    DISCRETIONARY = "DISCRETIONARY"


class LedgerSide(str, Enum):
    INCOME = "INCOME"
    PRINCIPAL = "PRINCIPAL"


class GstEventType(str, Enum):
    TAXABLE_DISTRIBUTION = "TAXABLE_DISTRIBUTION"
    TAXABLE_TERMINATION = "TAXABLE_TERMINATION"


# ─── Role enum ────────────────────────────────────────────────

class UserRole(str, Enum):
    TRUST_ADMIN = "TrustAdmin"
    GRANTOR = "Grantor"
    TRUSTEE = "Trustee"
    BENEFICIARY = "Beneficiary"


# ─── Entity TypedDicts (all common_fields: true → full quartet) ─

class Grantor(TypedDict):
    id: str
    full_name: str
    generation_level: int
    gst_exemption_total_cents: int
    gst_exemption_remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class Trustee(TypedDict):
    id: str
    full_name: str
    is_corporate: bool
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict):
    id: str
    full_name: str
    grantor_id: str
    generation_level: int
    is_skip_person: bool
    created_at: str
    updated_at: str
    version: int


class Trust(TypedDict):
    id: str
    name: str
    grantor_id: str
    trust_type: str
    is_grantor_trust: bool
    capital_gains_to_income: bool
    status: str
    principal_balance_cents: int
    income_balance_cents: int
    gst_exemption_allocated_cents: int
    inclusion_ratio: float
    created_at: str
    updated_at: str
    version: int


class TrusteeAppointment(TypedDict):
    id: str
    trust_id: str
    trustee_id: str
    term_start: str
    term_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TrustAccount(TypedDict):
    id: str
    trust_id: str
    tax_year: int
    period_start: str
    period_end: str
    status: str
    dni_cents: int
    dni_carried_out_cents: int
    taxable_income_cents: int
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    receipt_kind: str
    ledger_side: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    expense_kind: str
    ledger_side: str
    is_system_generated: bool
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict):
    id: str
    account_id: str
    beneficiary_id: str
    amount_cents: int
    distribution_kind: str
    proposer_trustee_id: str
    approver_trustee_id: Optional[str]
    status: str
    funded_from_income_cents: int
    funded_from_principal_cents: int
    dni_carried_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class K1(TypedDict):
    id: str
    account_id: str
    beneficiary_id: str
    ordinary_income_cents: int
    qualified_dividend_cents: int
    capital_gain_cents: int
    total_carried_cents: int
    created_at: str
    updated_at: str
    version: int


class TaxFiling(TypedDict):
    id: str
    account_id: str
    taxable_income_snapshot_cents: int
    tax_due_cents: int
    status: str
    supersedes_filing_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GstExemptionAllocation(TypedDict):
    id: str
    trust_id: str
    grantor_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GstEvent(TypedDict):
    id: str
    trust_id: str
    beneficiary_id: str
    distribution_id: Optional[str]
    event_type: str
    taxable_amount_cents: int
    gst_tax_cents: int
    inclusion_ratio_snapshot: float
    created_at: str
    updated_at: str
    version: int
