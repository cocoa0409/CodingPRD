"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3).

Every resource carries id, created_at, updated_at, version (PRD §2.5).
Optional/nullable fields are marked with NotRequired so assertions never
demand fields the PRD leaves unset (e.g. rated_contract_id before rating).
"""
from enum import Enum
from typing import List, Optional, TypedDict

try:
    from typing import NotRequired
except ImportError:  # Python < 3.11
    from typing_extensions import NotRequired


class ClientStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CarrierStatus(str, Enum):
    PENDING_ONBOARD = "PENDING_ONBOARD"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    DISCARDED = "DISCARDED"


class ShipmentStatus(str, Enum):
    REGISTERED = "REGISTERED"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class AuditStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CAPTURED = "CAPTURED"
    RATED = "RATED"
    CLEARED = "CLEARED"
    EXCEPTION = "EXCEPTION"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    SHORT_PAID = "SHORT_PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class DuplicateFlag(str, Enum):
    NONE = "NONE"
    FUZZY = "FUZZY"


class ChargeCode(str, Enum):
    BASE_FREIGHT = "BASE_FREIGHT"
    FUEL_SURCHARGE = "FUEL_SURCHARGE"
    LIFTGATE = "LIFTGATE"
    RESIDENTIAL = "RESIDENTIAL"
    INSIDE_DELIVERY = "INSIDE_DELIVERY"
    DETENTION = "DETENTION"
    STORAGE = "STORAGE"
    OTHER = "OTHER"


class ShipmentMode(str, Enum):
    PARCEL = "PARCEL"
    LTL = "LTL"
    FTL = "FTL"
    AIR = "AIR"
    OCEAN = "OCEAN"


class ExceptionCode(str, Enum):
    RATE_MISMATCH = "RATE_MISMATCH"
    DUPLICATE_FUZZY = "DUPLICATE_FUZZY"
    INVALID_ACCESSORIAL = "INVALID_ACCESSORIAL"
    NO_CONTRACT = "NO_CONTRACT"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    CARRIER_NOTIFIED = "CARRIER_NOTIFIED"
    CARRIER_RESPONDED = "CARRIER_RESPONDED"
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_CONCEDED = "RESOLVED_CONCEDED"
    ESCALATED = "ESCALATED"
    EXPIRED = "EXPIRED"


class RoutedQueue(str, Enum):
    AUDIT_TEAM = "AUDIT_TEAM"
    CARRIER = "CARRIER"
    FINANCE = "FINANCE"


class PaymentRunStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    RELEASED = "RELEASED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class PaymentRunItemStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    PAID = "PAID"


class RemittanceStatus(str, Enum):
    GENERATED = "GENERATED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class FxSource(str, Enum):
    ECB = "ECB"
    MANUAL = "MANUAL"


class RecoveryChannel(str, Enum):
    CREDIT_MEMO = "CREDIT_MEMO"
    REFUND = "REFUND"
    OFFSET = "OFFSET"


class RecoveryStatus(str, Enum):
    DRAFTED = "DRAFTED"
    FILED = "FILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REBUTTED = "REBUTTED"
    COLLECTED = "COLLECTED"
    ABANDONED = "ABANDONED"


class ExportStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class UserRole(str, Enum):
    FAP_ADMIN = "FapAdmin"
    AUDIT_ANALYST = "AuditAnalyst"
    FINANCE_CONTROLLER = "FinanceController"
    TREASURY_APPROVER = "TreasuryApprover"
    CARRIER_REP = "CarrierRep"
    CLIENT_VIEWER = "ClientViewer"
    SYSTEM = "System"


class ClientAccount(TypedDict, total=False):
    id: str
    name: str
    home_country: str
    home_currency: str
    audit_tolerance_minor: int
    audit_tolerance_pct_bp: int
    dispute_window_days: int
    status: str
    savings_realized_minor: int
    outstanding_liability_minor: int
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict, total=False):
    id: str
    client_id: str
    scac_code: str
    legal_name: str
    country: str
    billing_currency: str
    payment_terms_days: int
    remit_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RateContract(TypedDict, total=False):
    id: str
    client_id: str
    carrier_id: str
    name: str
    currency: str
    lanes: list
    effective_from: str
    effective_to: str
    supersedes_contract_id: Optional[str]
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShipmentRecord(TypedDict, total=False):
    id: str
    client_id: str
    carrier_id: str
    pro_number: str
    ship_date: str
    origin_country: str
    dest_country: str
    mode: str
    actual_weight_kg: float
    accessorials_rendered: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarrierInvoice(TypedDict, total=False):
    id: str
    client_id: str
    carrier_id: str
    shipment_id: Optional[str]
    rated_contract_id: Optional[str]
    invoice_number: str
    invoice_date: str
    currency: str
    billed_total_minor: int
    audit_status: str
    payment_status: str
    duplicate_flag: str
    rated_total_minor: int
    variance_minor: int
    variance_pct_bp: int
    approved_amount_minor: int
    home_total_minor: int
    scheduled_minor: int
    paid_minor: int
    due_date: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    id: str
    invoice_id: str
    gl_account_id: Optional[str]
    charge_code: str
    billed_amount_minor: int
    rated_amount_minor: int
    variance_minor: int
    created_at: str
    updated_at: str
    version: int


class AuditException(TypedDict, total=False):
    id: str
    invoice_id: str
    client_id: str
    code: str
    disputed_amount_minor: int
    resolution_credit_minor: int
    routed_queue: str
    round_count: int
    opened_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GLAccount(TypedDict, total=False):
    id: str
    client_id: str
    code: str
    business_unit: str
    country: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class CostAllocation(TypedDict, total=False):
    id: str
    invoice_line_id: str
    gl_account_id: str
    percentage_bp: int
    allocated_minor: int
    created_at: str
    updated_at: str
    version: int


class PaymentRun(TypedDict, total=False):
    id: str
    client_id: str
    run_date: str
    currency: str
    country_scope: Optional[str]
    status: str
    gross_total_minor: int
    discount_total_minor: int
    total_minor: int
    created_by_user_id: str
    locked_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentRunItem(TypedDict, total=False):
    id: str
    payment_run_id: str
    invoice_id: str
    scheduled_amount_minor: int
    discount_minor: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RemittanceAdvice(TypedDict, total=False):
    id: str
    payment_run_id: str
    carrier_id: str
    total_minor: int
    item_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FxRate(TypedDict, total=False):
    id: str
    client_id: str
    from_currency: str
    to_currency: str
    effective_date: str
    rate_ppm: int
    source: str
    created_at: str
    updated_at: str
    version: int


class RecoveryClaim(TypedDict, total=False):
    id: str
    client_id: str
    invoice_id: str
    claimed_amount_minor: int
    channel: str
    recovered_minor: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AnalyticsExport(TypedDict, total=False):
    id: str
    client_id: str
    date_from: str
    date_to: str
    include_statuses: List[str]
    row_count: int
    checksum: str
    status: str
    created_at: str
    updated_at: str
    version: int
