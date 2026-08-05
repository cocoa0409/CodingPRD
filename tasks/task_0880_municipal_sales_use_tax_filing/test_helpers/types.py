"""Domain types: entity TypedDicts, status enums, role enum.

Every primary resource in the Municipal Sales/Use Tax Filing API carries the
full common set (id, created_at, updated_at, version) — none is an immutable
value object.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    TAXPAYER = "Taxpayer"
    TAX_AUDITOR = "TaxAuditor"
    APPEALS_OFFICER = "AppealsOfficer"
    TAX_ADMIN = "TaxAdmin"


class AccountStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class NexusStatus(str, Enum):
    NONE = "NONE"
    ESTABLISHED = "ESTABLISHED"


class EntityType(str, Enum):
    SOLE_PROP = "SOLE_PROP"
    LLC = "LLC"
    CORP = "CORP"
    PARTNERSHIP = "PARTNERSHIP"


class FilingFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class ReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    AMENDING = "AMENDING"
    ASSESSED = "ASSESSED"


class ExemptionType(str, Enum):
    RESALE = "RESALE"
    GOVERNMENT = "GOVERNMENT"
    NONPROFIT = "NONPROFIT"
    MANUFACTURING = "MANUFACTURING"


class RemittanceType(str, Enum):
    PAYMENT = "PAYMENT"
    PREPAYMENT = "PREPAYMENT"


class AuditType(str, Enum):
    FIELD_AUDIT = "FIELD_AUDIT"
    NEXUS_DISCOVERY = "NEXUS_DISCOVERY"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_ASSESSED = "CLOSED_ASSESSED"
    CLOSED_NO_CHANGE = "CLOSED_NO_CHANGE"


class AssessmentType(str, Enum):
    AUDIT_DEFICIENCY = "AUDIT_DEFICIENCY"
    LATE_FILING = "LATE_FILING"


class AssessmentStatus(str, Enum):
    ISSUED = "ISSUED"
    ABATED = "ABATED"
    AFFIRMED = "AFFIRMED"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    ALLOWED = "ALLOWED"
    DENIED = "DENIED"


class RefundStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class Taxpayer(TypedDict):
    id: str
    legal_name: str
    entity_type: str
    email: str
    filing_frequency: str
    account_status: str
    nexus_status: str
    suspend_reason: Optional[str]
    activated_at: Optional[str]
    account_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Jurisdiction(TypedDict):
    id: str
    code: str
    name: str
    rate_bps: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict):
    id: str
    taxpayer_id: str
    exemption_certificate_id: Optional[str]
    period_key: str
    period_start_date: str
    period_end_date: str
    filing_due_date: str
    lines: list
    status: str
    filed_at: Optional[str]
    total_taxable_cents: int
    tax_due_cents: int
    vendor_discount_cents: int
    net_return_due_cents: int
    created_at: str
    updated_at: str
    version: int


class ExemptionCertificate(TypedDict):
    id: str
    taxpayer_id: str
    exemption_type: str
    certificate_number: str
    effective_date: str
    expiry_date: str
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict):
    id: str
    taxpayer_id: str
    applied_return_id: Optional[str]
    remittance_type: str
    amount_cents: int
    applied_amount_cents: int
    unapplied_amount_cents: int
    received_at: str
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict):
    id: str
    taxpayer_id: str
    audit_type: str
    period_key: str
    gross_receipts_cents: Optional[int]
    nexus_established: Optional[bool]
    status: str
    opened_by_user_id: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    taxpayer_id: str
    audit_id: Optional[str]
    return_id: Optional[str]
    assessment_type: str
    tax_deficiency_cents: int
    original_due_date: str
    penalty_cents: int
    interest_cents: int
    total_due_cents: int
    status: str
    issued_by_user_id: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    assessment_id: str
    grounds: str
    status: str
    info_request_note: Optional[str]
    filed_at: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundClaim(TypedDict):
    id: str
    taxpayer_id: str
    return_id: str
    claim_amount_cents: int
    reason: str
    overpayment_date: str
    status: str
    interest_cents: Optional[int]
    refund_total_cents: Optional[int]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
