"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain are mutable and therefore carry id, created_at,
updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    POOL_ADMIN = "PoolAdmin"
    POOL_OPERATOR = "PoolOperator"
    PARTICIPANT = "Participant"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class PoolPolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AssetTypeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class LocationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EquityStatus(str, Enum):
    BALANCED = "BALANCED"
    SHORT = "SHORT"
    SURPLUS = "SURPLUS"


class AssetCondition(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_HIRE = "ON_HIRE"
    IN_TRANSIT = "IN_TRANSIT"
    DAMAGED = "DAMAGED"
    IN_REPAIR = "IN_REPAIR"
    LOST = "LOST"


class TransferOrderKind(str, Enum):
    ISSUANCE = "ISSUANCE"
    RETURN = "RETURN"
    TRANSFER = "TRANSFER"


class TransferOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class HireLifecycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class HireSettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class AuditStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class LossBasis(str, Enum):
    REPLACEMENT = "REPLACEMENT"
    NET_BOOK = "NET_BOOK"


class VoucherStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class CollectionRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COLLECTED = "COLLECTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RepairJobStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    SCRAPPED = "SCRAPPED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceLineKind(str, Enum):
    HIRE = "HIRE"
    LOSS = "LOSS"
    REPAIR = "REPAIR"
    CREDIT = "CREDIT"


class AccountRoleType(str, Enum):
    MANUFACTURER = "MANUFACTURER"
    DISTRIBUTOR = "DISTRIBUTOR"
    RETAILER = "RETAILER"


class DemandForecastStatus(str, Enum):
    COMPUTED = "COMPUTED"


# --------------------------------------------------------------------------
# Entity TypedDicts (all carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class PoolPolicy(TypedDict):
    id: str
    name: str
    currency: str
    equity_warn_threshold: int
    voucher_expiry_days: int
    audit_min_interval_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AssetType(TypedDict):
    id: str
    code: str
    name: str
    base_daily_rate_cents: int
    replacement_cost_cents: int
    useful_life_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    legal_name: str
    role_type: str
    credit_limit_cents: int
    outstanding_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    account_id: str
    name: str
    physical_balance: int
    equity_balance: int
    equity_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    asset_type_id: str
    serial: str
    in_service_at: str
    current_location_id: Optional[str]
    current_hire_id: Optional[str]
    condition: str
    created_at: str
    updated_at: str
    version: int


class TransferOrder(TypedDict):
    id: str
    from_location_id: str
    to_location_id: str
    kind: str
    asset_ids: List[str]
    quantity: int
    dispatched_at: Optional[str]
    received_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Hire(TypedDict):
    id: str
    account_id: str
    location_id: str
    asset_type_id: str
    asset_ids: List[str]
    on_hire_at: Optional[str]
    off_hire_at: Optional[str]
    expected_location_version: int
    accrued_charge_cents: int
    final_charge_cents: Optional[int]
    lifecycle_status: str
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class AuditReconciliation(TypedDict):
    id: str
    location_id: str
    window_start: str
    window_end: str
    counted_physical: int
    loss_basis: str
    declared_loss_qty: int
    declared_loss_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict):
    id: str
    from_location_id: str
    to_account_id: str
    asset_type_id: str
    quantity: int
    issued_at: Optional[str]
    redeem_location_id: Optional[str]
    expected_from_location_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CollectionRequest(TypedDict):
    id: str
    location_id: str
    asset_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairJob(TypedDict):
    id: str
    collection_request_id: str
    asset_ids: List[str]
    repair_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    account_id: str
    subtotal_cents: int
    credit_cents: int
    total_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    id: str
    invoice_id: str
    kind: str
    source_hire_id: Optional[str]
    source_audit_id: Optional[str]
    source_voucher_id: Optional[str]
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class DemandForecast(TypedDict):
    id: str
    location_id: str
    asset_type_id: str
    horizon_days: int
    projected_demand: int
    recommended_reposition: int
    status: str
    created_at: str
    updated_at: str
    version: int
