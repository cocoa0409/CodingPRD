"""Domain types: entity TypedDicts, status enums, role enum.

TypedDicts use total=False so computed/nullable PRD fields can be absent or
null without type noise; runtime shape is enforced by assertions.py.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class AllocationPosture(str, Enum):
    NORMAL = "NORMAL"
    CURTAILED = "CURTAILED"


class SeasonPosture(str, Enum):
    SUMMER_BUILD = "SUMMER_BUILD"
    WINTER_DRAW = "WINTER_DRAW"


class SupplyContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class RailShipmentStatus(str, Enum):
    TENDERED = "TENDERED"
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    UNLOADED = "UNLOADED"
    CANCELLED = "CANCELLED"


class CreditStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class DealerContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PricingMode(str, Enum):
    INDEX = "INDEX"
    FIXED = "FIXED"
    SPOT = "SPOT"


class IndexName(str, Enum):
    MT_BELVIEU = "MT_BELVIEU"
    CONWAY = "CONWAY"


class TruckStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class FulfillmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ALLOCATED = "ALLOCATED"
    SHORTED = "SHORTED"
    SCHEDULED = "SCHEDULED"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    NOT_READY = "NOT_READY"
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


class ColdSnapSeverity(str, Enum):
    WATCH = "WATCH"
    WARNING = "WARNING"
    EMERGENCY = "EMERGENCY"


class ColdSnapStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class AllocationRunStatus(str, Enum):
    OPEN = "OPEN"
    COMPUTED = "COMPUTED"
    RATIFIED = "RATIFIED"
    SUPERSEDED = "SUPERSEDED"


class PaymentMethod(str, Enum):
    ACH = "ACH"
    CHECK = "CHECK"
    WIRE = "WIRE"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    RETURNED = "RETURNED"


class UserRole(str, Enum):
    SUPPLY_ADMIN = "SupplyAdmin"
    SUPPLY_PLANNER = "SupplyPlanner"
    PRICING_DESK = "PricingDesk"
    CREDIT_MANAGER = "CreditManager"
    DISPATCHER = "Dispatcher"
    DEALER_USER = "DealerUser"
    SYSTEM_ADMIN = "SystemAdmin"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version except
# PriceIndexPublication, which is append-only: id + created_at only) ---


class Terminal(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    storage_capacity_gal: int
    reserve_floor_gal: int
    winter_reserve_floor_gal: int
    rack_bay_count: int
    on_hand_gal: int
    allocation_posture: str
    ops_epoch: int
    season_posture: str
    reserved_gal: int
    effective_reserve_floor_gal: int
    available_to_promise_gal: int
    created_at: str
    updated_at: str
    version: int


class SupplyContract(TypedDict, total=False):
    id: str
    terminal_id: str
    supplier_name: str
    contracted_volume_gal: int
    delivered_volume_gal: int
    receipt_window_start: str
    receipt_window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RailShipment(TypedDict, total=False):
    id: str
    supply_contract_id: str
    terminal_id: str
    volume_gal: int
    railcar_count: int
    scheduled_arrival_date: str
    unloaded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Dealer(TypedDict, total=False):
    id: str
    legal_name: str
    credit_limit_cents: int
    fee_balance_cents: int
    ledger_exposure_cents: int
    committed_exposure_cents: int
    credit_status: str
    created_at: str
    updated_at: str
    version: int


class DealerContract(TypedDict, total=False):
    id: str
    dealer_id: str
    terminal_id: str
    pricing_mode: str
    fixed_price_mc_per_gal: Optional[int]
    volume_committed_gal: int
    volume_drawn_gal: int
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceIndexPublication(TypedDict, total=False):
    # Append-only configuration: id + created_at only; NO updated_at, NO version.
    id: str
    index_name: str
    effective_date: str
    price_mc_per_gal: int
    created_at: str


class FreightZone(TypedDict, total=False):
    id: str
    terminal_id: str
    zone_code: str
    one_way_drive_minutes: int
    freight_mc_per_gal: int
    min_freight_cents: int
    created_at: str
    updated_at: str
    version: int


class TransportTruck(TypedDict, total=False):
    id: str
    terminal_id: str
    unit_number: str
    capacity_gal: int
    weekly_hours_limit_minutes: int
    status: str
    weekly_committed_minutes: int
    created_at: str
    updated_at: str
    version: int


class DeliveryOrder(TypedDict, total=False):
    id: str
    dealer_id: str
    dealer_contract_id: Optional[str]
    terminal_id: str
    freight_zone_id: str
    truck_id: Optional[str]
    requested_gal: int
    allocated_gal: Optional[int]
    pricing_mode: str
    provisional_total_cents: Optional[int]
    final_total_cents: Optional[int]
    open_balance_cents: Optional[int]
    fulfillment_status: str
    invoice_status: str
    planned_load_start: Optional[str]
    planned_load_end: Optional[str]
    est_trip_minutes: Optional[int]
    invoiced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ColdSnapEvent(TypedDict, total=False):
    id: str
    terminal_id: str
    severity: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationRun(TypedDict, total=False):
    id: str
    terminal_id: str
    run_index: int
    status: str
    pool_gal: Optional[int]
    results: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class DealerPayment(TypedDict, total=False):
    id: str
    dealer_id: str
    amount_cents: int
    method: str
    status: str
    applications: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int
