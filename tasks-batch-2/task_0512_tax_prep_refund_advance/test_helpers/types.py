"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Tax-Prep Refund Advance PRD (§2.4, §3).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class OfficeEfinStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ReturnKind(str, Enum):
    ORIGINAL = "ORIGINAL"
    PRIOR_YEAR = "PRIOR_YEAR"
    AMENDED_1040X = "AMENDED_1040X"


class ComplexityBand(str, Enum):
    SIMPLE = "SIMPLE"
    STANDARD = "STANDARD"
    COMPLEX = "COMPLEX"


class TaxReturnStatus(str, Enum):
    INTAKE = "INTAKE"
    DOCS_PENDING = "DOCS_PENDING"
    IN_PREP = "IN_PREP"
    PREPARED = "PREPARED"
    EFILED_PENDING = "EFILED_PENDING"
    EFILED_ACCEPTED = "EFILED_ACCEPTED"
    EFILED_REJECTED = "EFILED_REJECTED"
    CANCELLED = "CANCELLED"


class DocType(str, Enum):
    W2 = "W2"
    F1099 = "1099"
    ID = "ID"
    PRIOR_RETURN = "PRIOR_RETURN"
    OTHER = "OTHER"


class DocumentStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    WAIVED = "WAIVED"


class FeeLineKind(str, Enum):
    BASE_1040 = "BASE_1040"
    SCHEDULE = "SCHEDULE"
    STATE_RETURN = "STATE_RETURN"
    DISCOUNT = "DISCOUNT"


class AuditProtectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class AckStatus(str, Enum):
    TRANSMITTED = "TRANSMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RefundTransferStatus(str, Enum):
    PENDING_FUNDING = "PENDING_FUNDING"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"


class RefundAdvanceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    REPAID = "REPAID"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class UserRole(str, Enum):
    OFFICE_MANAGER = "OfficeManager"
    FRONT_DESK_AGENT = "FrontDeskAgent"
    TAX_PREPARER = "TaxPreparer"
    BANK_PRODUCT_OFFICER = "BankProductOfficer"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# All persisted entities below carry the four common fields
# (id, created_at, updated_at, version) per PRD §2.4 — except ComplianceClock,
# which carries only id + created_at.

class Office(TypedDict):
    id: str
    name: str
    efin: str
    state_code: str
    efin_status: str
    bank_product_enabled: bool
    open_return_count: int
    created_at: str
    updated_at: str
    version: int


class ComplianceCredential(TypedDict):
    id: str
    office_id: str
    ptin: str
    holder_name: str
    status: str
    expires_on: str
    created_at: str
    updated_at: str
    version: int


class Preparer(TypedDict):
    id: str
    office_id: str
    credential_id: str
    full_name: str
    assigned_open_returns: int
    max_open_returns: int
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    office_id: str
    full_name: str
    ssn_last4: str
    risk_band: str
    is_returning: bool
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    office_id: str
    client_id: str
    preparer_id: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxReturn(TypedDict):
    id: str
    office_id: str
    client_id: str
    preparer_id: Optional[str]
    amends_return_id: Optional[str]
    tax_year: int
    return_kind: str
    complexity_band: str
    schedules: List[str]
    state_return_count: int
    expected_refund_cents: int
    prep_fee_cents: int
    status: str
    reject_count: int
    created_at: str
    updated_at: str
    version: int


class DocumentIntake(TypedDict):
    id: str
    tax_return_id: str
    doc_type: str
    is_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeLine(TypedDict):
    id: str
    tax_return_id: str
    line_kind: str
    label: str
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class AuditProtection(TypedDict):
    id: str
    tax_return_id: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EfileSubmission(TypedDict):
    id: str
    tax_return_id: str
    efin_used: str
    ptin_used: str
    ack_status: str
    reject_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundTransfer(TypedDict):
    id: str
    tax_return_id: str
    bank_product_fee_cents: int
    estimated_refund_cents: int
    disbursed_refund_cents: int
    net_to_taxpayer_cents: int
    fee_shortfall_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundAdvance(TypedDict):
    id: str
    tax_return_id: str
    requested_cents: int
    approved_cents: int
    repaid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ComplianceClock is the singleton config row — id + created_at only (PRD §2.4).
class ComplianceClock(TypedDict):
    id: str
    current_utc: str
    created_at: str
