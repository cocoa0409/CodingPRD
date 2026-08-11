"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    ACCOUNT_MANAGER = "AccountManager"
    INTAKE_OPERATOR = "IntakeOperator"
    DESTRUCTION_TECHNICIAN = "DestructionTechnician"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AccountTier(str, Enum):
    STANDARD = "STANDARD"
    VOLUME = "VOLUME"
    ENTERPRISE = "ENTERPRISE"


class CertificationStandard(str, Enum):
    R2 = "R2"
    E_STEWARDS = "E_STEWARDS"


class ManifestMode(str, Enum):
    PICKUP = "PICKUP"
    DROPOFF = "DROPOFF"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    RECEIVED = "RECEIVED"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ItemCategory(str, Enum):
    LAPTOP = "LAPTOP"
    DESKTOP = "DESKTOP"
    SERVER = "SERVER"
    PHONE = "PHONE"
    TABLET = "TABLET"
    MONITOR = "MONITOR"
    BATTERY = "BATTERY"
    OTHER = "OTHER"


class ItemGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class Disposition(str, Enum):
    NONE = "NONE"
    RESALE = "RESALE"
    REFURB = "REFURB"
    RECYCLE = "RECYCLE"


class ProcessingStatus(str, Enum):
    INTAKE = "INTAKE"
    FOR_RESALE = "FOR_RESALE"
    FOR_REFURB = "FOR_REFURB"
    FOR_RECYCLE = "FOR_RECYCLE"
    LISTED = "LISTED"
    SOLD = "SOLD"
    BATCHED = "BATCHED"
    DOWNSTREAM = "DOWNSTREAM"
    COMPLETE = "COMPLETE"


class DataStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    SANITIZED = "SANITIZED"
    VERIFIED = "VERIFIED"


class SanitizationMethod(str, Enum):
    CRYPTO_ERASE = "CRYPTO_ERASE"
    NIST_CLEAR = "NIST_CLEAR"
    NIST_PURGE = "NIST_PURGE"
    PHYSICAL_DESTROY = "PHYSICAL_DESTROY"


class SanitizationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SanitizationStatus(str, Enum):
    LOGGED = "LOGGED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ListingChannel(str, Enum):
    B2B_AUCTION = "B2B_AUCTION"
    RETAIL = "RETAIL"


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    RETURNED = "RETURNED"
    WITHDRAWN = "WITHDRAWN"


class BatchStatus(str, Enum):
    STAGING = "STAGING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    PROCESSED = "PROCESSED"


class CustodySubjectType(str, Enum):
    MANIFEST = "MANIFEST"
    ITEM = "ITEM"
    BATCH = "BATCH"


class CustodyEventType(str, Enum):
    RECEIVED_FACILITY = "RECEIVED_FACILITY"
    TRANSFERRED = "TRANSFERRED"
    SHIPPED_DOWNSTREAM = "SHIPPED_DOWNSTREAM"
    DELIVERED_DOWNSTREAM = "DELIVERED_DOWNSTREAM"
    PROCESSED = "PROCESSED"


class CertType(str, Enum):
    DATA_DESTRUCTION = "DATA_DESTRUCTION"
    RECYCLING = "RECYCLING"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class SettlementKind(str, Enum):
    QUOTE = "QUOTE"
    FINAL = "FINAL"


class SettlementStatus(str, Enum):
    QUOTE_OPEN = "QUOTE_OPEN"
    SUPERSEDED = "SUPERSEDED"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class LedgerEntryType(str, Enum):
    BUYBACK_CREDIT = "BUYBACK_CREDIT"
    FEE_DEBIT = "FEE_DEBIT"
    BONUS_CREDIT = "BONUS_CREDIT"
    PAYOUT_DEBIT = "PAYOUT_DEBIT"
    REVERSAL = "REVERSAL"


class BusinessAccount(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    tier: str
    status: str
    credit_balance_cents: int
    lifetime_diverted_kg: float
    created_at: str
    updated_at: str
    version: int


class Recycler(TypedDict, total=False):
    id: str
    name: str
    certification_standard: str
    certification_expires_at: str
    accepted_categories: List[str]
    daily_intake_capacity_kg: float
    violation_count: int
    total_processed_kg: float
    risk_score: float
    created_at: str
    updated_at: str
    version: int


class CompliancePolicy(TypedDict, total=False):
    id: str
    standard: str
    sanitization_methods_allowed: List[str]
    export_allowed: bool
    resale_requires_verified_sanitization: bool
    is_active: bool
    weight_cert_freshness: float
    weight_volume: float
    weight_violations: float
    created_at: str
    updated_at: str
    version: int


class Manifest(TypedDict, total=False):
    id: str
    account_id: str
    mode: str
    pickup_route: Optional[str]
    scheduled_start: str
    scheduled_end: str
    declared_item_count: int
    received_item_count: int
    discrepancy_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    manifest_id: str
    serial_number: str
    category: str
    weight_kg: float
    data_bearing: bool
    hazmat_flag: bool
    declared_grade: str
    disposition: str
    processing_status: str
    data_status: str
    recycle_batch_id: Optional[str]
    provisional_value_cents: int
    final_value_cents: int
    created_at: str
    updated_at: str
    version: int


class DataSanitization(TypedDict, total=False):
    id: str
    item_id: str
    method: str
    outcome: str
    logged_by_id: str
    verified_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ResaleListing(TypedDict, total=False):
    id: str
    item_id: str
    asking_price_cents: int
    floor_price_cents: int
    channel: str
    sale_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecycleBatch(TypedDict, total=False):
    id: str
    recycler_id: str
    scheduled_delivery_date: str
    is_export: bool
    status: str
    gross_weight_kg: float
    item_count: int
    created_at: str
    updated_at: str
    version: int


class CustodyEvent(TypedDict, total=False):
    # Append-only record (PRD §2.4): carries only id and created_at, no updated_at/version.
    id: str
    subject_type: str
    subject_id: str
    event_type: str
    from_location: Optional[str]
    to_location: Optional[str]
    actor_id: str
    created_at: str


class Certificate(TypedDict, total=False):
    id: str
    cert_type: str
    item_id: Optional[str]
    batch_id: Optional[str]
    certificate_number: str
    issued_by_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    manifest_id: str
    kind: str
    status: str
    supersedes_settlement_id: Optional[str]
    gross_buyback_cents: int
    total_fees_cents: int
    volume_rebate_cents: int
    net_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    # Append-only record (PRD §2.4): carries only id and created_at, no updated_at/version.
    id: str
    account_id: str
    settlement_id: str
    entry_type: str
    amount_cents: int
    balance_after_cents: int
    created_at: str
