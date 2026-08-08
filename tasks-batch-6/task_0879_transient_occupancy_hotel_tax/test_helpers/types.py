"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    TAX_ADMIN = "TaxAdmin"
    OPERATOR = "Operator"
    AUDITOR = "Auditor"


class OperatorStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    CLOSED = "CLOSED"


class FilingFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class OTAAgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class CollectionMethod(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class ReturnFilingStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    AMENDED = "AMENDED"
    SUPERSEDED = "SUPERSEDED"


class ReturnSettlementStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID = "PAID"


class ReportingMethod(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class ExemptionType(str, Enum):
    LONG_TERM_30DAY = "LONG_TERM_30DAY"
    GOVERNMENT = "GOVERNMENT"
    NONPROFIT = "NONPROFIT"


class ExemptionStatus(str, Enum):
    CLAIMED = "CLAIMED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class Remitter(str, Enum):
    OPERATOR = "OPERATOR"
    OTA = "OTA"


class RemittanceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CLEARED = "CLEARED"
    REVERSED = "REVERSED"


class AuditClassification(str, Enum):
    NONE = "NONE"
    NEGLIGENCE = "NEGLIGENCE"
    FRAUD = "FRAUD"


class AuditStatus(str, Enum):
    OPENED = "OPENED"
    FIELDWORK = "FIELDWORK"
    PROPOSED = "PROPOSED"
    RESPONSE = "RESPONSE"
    ISSUED = "ISSUED"
    CLOSED_NO_CHANGE = "CLOSED_NO_CHANGE"


class AssessmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ISSUED = "ISSUED"
    APPEALED = "APPEALED"
    FINAL = "FINAL"
    ABATED = "ABATED"
    SETTLED = "SETTLED"


class AppealDecision(str, Enum):
    UPHELD = "UPHELD"
    REDUCED = "REDUCED"
    ABATED = "ABATED"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    DECIDED = "DECIDED"


class LienStatus(str, Enum):
    RECORDED = "RECORDED"
    RELEASED = "RELEASED"


class RefundReason(str, Enum):
    OVERPAYMENT = "OVERPAYMENT"
    AUDIT_ADJUSTMENT = "AUDIT_ADJUSTMENT"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class LedgerEntryType(str, Enum):
    TAX_DUE = "TAX_DUE"
    PENALTY = "PENALTY"
    INTEREST = "INTEREST"
    REMITTANCE = "REMITTANCE"
    REMITTANCE_REVERSAL = "REMITTANCE_REVERSAL"
    ASSESSMENT = "ASSESSMENT"
    ABATEMENT = "ABATEMENT"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true unless marked otherwise)
# --------------------------------------------------------------------------
class Jurisdiction(TypedDict):
    id: str
    name: str
    tax_rate_bps: int
    interest_rate_monthly_bps: int
    refund_interest_monthly_bps: int
    lien_threshold_cents: int
    exemption_min_stay_nights: int
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict):
    id: str
    jurisdiction_id: str
    legal_name: str
    filing_frequency: str
    certificate_number: Optional[str]
    status: str
    account_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    operator_id: str
    name: str
    address: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class OTAPlatform(TypedDict):
    id: str
    name: str
    registered: bool
    created_at: str
    updated_at: str
    version: int


class OTAAgreement(TypedDict):
    id: str
    operator_id: str
    platform_id: str
    collection_method: str
    effective_date: str
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict):
    id: str
    operator_id: str
    period_start: str
    period_end: str
    reporting_method: str
    line_items: list
    gross_receipts_cents: int
    exempt_receipts_cents: int
    taxable_receipts_cents: int
    tax_due_cents: int
    penalty_cents: int
    interest_cents: int
    total_due_cents: int
    amount_paid_cents: int
    due_date: str
    filed_at: Optional[str]
    filing_status: str
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class ExemptionClaim(TypedDict):
    id: str
    tax_return_id: str
    exemption_type: str
    guest_ref: str
    stay_nights: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict):
    id: str
    tax_return_id: str
    ota_agreement_id: Optional[str]
    remitter: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict):
    id: str
    operator_id: str
    period_start: str
    period_end: str
    classification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    audit_id: str
    audited_taxable_cents: int
    assessed_tax_cents: int
    self_reported_tax_cents: int
    deficiency_cents: int
    penalty_cents: int
    interest_cents: int
    total_assessed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    assessment_id: str
    grounds: str
    round_count: int
    decision: Optional[str]
    reduced_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict):
    id: str
    operator_id: str
    amount_cents: int
    status: str
    recorded_at: str
    created_at: str
    updated_at: str
    version: int


class RefundClaim(TypedDict):
    id: str
    operator_id: str
    tax_return_id: Optional[str]
    reason: str
    principal_cents: int
    overpayment_date: str
    interest_cents: int
    total_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger entry: only id + created_at
class LedgerEntry(TypedDict):
    id: str
    operator_id: str
    entry_type: str
    amount_signed_cents: int
    source_ref: str
    created_at: str
