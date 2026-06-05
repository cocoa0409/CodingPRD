"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum values are PRD-exact (Insurance Agency Management API).
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    PRODUCER = "Producer"
    ACCOUNT_MANAGER = "AccountManager"
    TRUST_ACCOUNTANT = "TrustAccountant"


# ---------------------------------------------------------------------------
# Status / enum value sets
# ---------------------------------------------------------------------------
class CarrierStatus(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LineOfBusiness(str, Enum):
    AUTO = "AUTO"
    HOME = "HOME"
    GL = "GL"
    WC = "WC"
    UMBRELLA = "UMBRELLA"


class CancellationBasis(str, Enum):
    PRO_RATA = "PRO_RATA"
    SHORT_RATE = "SHORT_RATE"


class ProducerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    PENDING = "PENDING"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class AccountType(str, Enum):
    PERSONAL = "PERSONAL"
    COMMERCIAL = "COMMERCIAL"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    ACTIVE = "ACTIVE"
    PENDING_RENEWAL = "PENDING_RENEWAL"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REINSTATED = "REINSTATED"
    NON_RENEWED = "NON_RENEWED"


class TermKind(str, Enum):
    NEW_BUSINESS = "NEW_BUSINESS"
    RENEWAL = "RENEWAL"


class CancellationReason(str, Enum):
    INSURED_REQUEST = "INSURED_REQUEST"
    NON_PAYMENT = "NON_PAYMENT"
    UNDERWRITING = "UNDERWRITING"


class DownloadSource(str, Enum):
    MANUAL = "MANUAL"
    ACORD_DOWNLOAD = "ACORD_DOWNLOAD"


class SplitRole(str, Enum):
    WRITING = "WRITING"
    SERVICING = "SERVICING"
    OVERRIDE = "OVERRIDE"


class SplitStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"


class LedgerEntryType(str, Enum):
    PREMIUM_RECEIPT = "PREMIUM_RECEIPT"
    CARRIER_REMITTANCE = "CARRIER_REMITTANCE"
    COMMISSION_DISBURSEMENT = "COMMISSION_DISBURSEMENT"
    RETURN_PREMIUM_REFUND = "RETURN_PREMIUM_REFUND"
    OPENING_BALANCE = "OPENING_BALANCE"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    PAID = "PAID"


class RenewalStage(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    REVIEW = "REVIEW"
    QUOTED = "QUOTED"
    OFFERED = "OFFERED"
    COMPLETED = "COMPLETED"
    LOST = "LOST"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Entities with the full quartet (id/created_at/updated_at/version) per PRD §2.4.
# ---------------------------------------------------------------------------
class Carrier(TypedDict):
    id: str
    name: str
    naic_code: str
    status: str
    download_supported: bool
    default_new_business_commission_pct: float
    default_renewal_commission_pct: float
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    carrier_id: str
    line_of_business: str
    name: str
    new_business_commission_pct: Optional[float]
    renewal_commission_pct: Optional[float]
    cancellation_basis: str
    created_at: str
    updated_at: str
    version: int


class Producer(TypedDict):
    id: str
    full_name: str
    npn: str
    status: str
    default_split_pct: float
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    producer_id: str
    state_code: str
    line_of_business: str
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    carrier_id: str
    producer_id: str
    state_code: str
    status: str
    requested_at: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    name: str
    servicing_producer_id: str
    account_type: str
    active_policy_count: int
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    account_id: str
    product_id: str
    writing_producer_id: str
    renewed_from_policy_id: Optional[str]
    state_code: str
    annual_premium_cents: int
    effective_date: str
    expiration_date: str
    term_kind: str
    status: str
    cancellation_date: Optional[str]
    cancellation_reason: Optional[str]
    return_premium_cents: int
    earned_premium_cents: int
    download_source: str
    created_at: str
    updated_at: str
    version: int


class CommissionSplit(TypedDict):
    id: str
    policy_id: str
    producer_id: str
    split_pct: float
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TrustAccount(TypedDict):
    id: str
    name: str
    state_code: str
    balance_cents: int
    minimum_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict):
    id: str
    producer_id: str
    period_start: str
    period_end: str
    gross_commission_cents: int
    chargeback_cents: int
    net_payable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RenewalTask(TypedDict):
    id: str
    policy_id: str
    stage: str
    target_effective_date: str
    requote_count: int
    successor_policy_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at (PRD §2.4).
class TrustLedgerEntry(TypedDict):
    id: str
    trust_account_id: str
    policy_id: Optional[str]
    entry_type: str
    amount_cents: int
    created_at: str


# Singleton control record — carries only its current_utc value (PRD §2.4).
class SystemClock(TypedDict):
    current_utc: str
