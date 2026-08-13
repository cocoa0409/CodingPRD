"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER_ADMIN = "CustomerAdmin"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    QUALITY_MANAGER = "QualityManager"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    BILLING_ADMIN = "BillingAdmin"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RateCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class StorageMethod(str, Enum):
    DAILY_PRORATED = "DAILY_PRORATED"
    FULL_MONTH = "FULL_MONTH"


class LiabilityModel(str, Enum):
    DECLARED_VALUE = "DECLARED_VALUE"
    LIMITED_LIABILITY = "LIMITED_LIABILITY"


class TempClass(str, Enum):
    FROZEN = "FROZEN"
    CHILLED = "CHILLED"


class ZonePosture(str, Enum):
    OPEN = "OPEN"
    TIGHT = "TIGHT"
    FULL = "FULL"


class ReceiptStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL_HOLD = "PARTIAL_HOLD"
    FULL_HOLD = "FULL_HOLD"
    DEPLETED = "DEPLETED"
    RECALLED = "RECALLED"


class PalletStatus(str, Enum):
    STORED = "STORED"
    IN_BLAST_FREEZE = "IN_BLAST_FREEZE"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    DISPOSITIONED = "DISPOSITIONED"


class PalletQuality(str, Enum):
    OK = "OK"
    QUARANTINED = "QUARANTINED"
    RECALLED = "RECALLED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ALLOCATED = "ALLOCATED"
    SHORTED = "SHORTED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    FULFILLED = "FULFILLED"


class BookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ExcursionStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED_BREACH = "CONFIRMED_BREACH"
    CLEARED = "CLEARED"


class RecallStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REOPENED = "REOPENED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


# All resources carry the common fields of PRD §2.5:
# id, created_at, updated_at, version.


class Customer(TypedDict):
    id: str
    name: str
    credit_limit_cents: int
    status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    customer_id: str
    storage_method: str
    frozen_storage_cents_per_pallet_month: int
    chilled_storage_cents_per_pallet_month: int
    handling_in_cents_per_pallet: int
    handling_out_cents_per_pallet: int
    blast_base_cents: int
    blast_per_pallet_cents: int
    liability_model: str
    liability_per_pallet_cents: int
    dwell_exempt: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TemperatureZone(TypedDict):
    id: str
    zone_code: str
    temp_class: str
    capacity_pallets: int
    dock_doors: int
    in_use_pallets: int
    reserved_pallets: int
    free_pallets: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class InboundReceipt(TypedDict):
    id: str
    customer_id: str
    zone_id: str
    lot_id: Optional[str]
    product_code: str
    lot_code: str
    production_date: str
    temp_class: str
    expected_pallets: int
    actual_pallets: Optional[int]
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    customer_id: str
    product_code: str
    lot_code: str
    production_date: str
    on_hand_pallets: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Pallet(TypedDict):
    id: str
    lot_id: str
    receipt_id: str
    zone_id: str
    customer_id: str
    status: str
    quality: str
    received_at: str
    last_blast_frozen_at: Optional[str]
    out_at: Optional[str]
    out_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutboundOrder(TypedDict):
    id: str
    customer_id: str
    product_code: str
    lot_code: Optional[str]
    requested_pallets: int
    allocated_pallets: int
    estimated_handling_out_cents: Optional[int]
    final_handling_out_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    order_id: str
    pallet_id: str
    lot_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BlastFreezeCell(TypedDict):
    id: str
    cell_code: str
    capacity_pallets: int
    turnaround_minutes: int
    created_at: str
    updated_at: str
    version: int


class BlastFreezeBooking(TypedDict):
    id: str
    cell_id: str
    lot_id: str
    customer_id: str
    pallet_count: int
    window_start: str
    window_end: str
    fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TemperatureExcursion(TypedDict):
    id: str
    zone_id: str
    observed_temp_c: float
    window_start: str
    window_end: str
    reported_by_user_id: str
    quarantined_pallet_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallEvent(TypedDict):
    id: str
    customer_id: str
    product_code: str
    lot_code: str
    lot_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    customer_id: str
    excursion_id: str
    affected_pallet_count: int
    declared_value_cents: int
    settlement_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    customer_id: str
    period_start: str
    period_end: str
    status: str
    storage_cents: int
    handling_in_cents: int
    handling_out_cents: int
    blast_freeze_cents: int
    dwell_surcharge_cents: int
    claim_credit_cents: int
    total_cents: int
    rate_card_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
