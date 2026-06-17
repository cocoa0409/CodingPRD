"""Domain types: entity TypedDicts, status enums, role enum.

All field names, enum values, and field presence follow the PRD contract.
Append-only event records (DamageReport, ChargeLedgerEntry) carry only
id + created_at — no updated_at, no version — per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    FLEET_MANAGER = "FleetManager"
    LOCATION_AGENT = "LocationAgent"
    CUSTOMER = "Customer"


# ── Status / category enums ──────────────────────────────────────────────
class LocationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EquipmentCategory(str, Enum):
    TRUCK = "TRUCK"
    TRAILER = "TRAILER"
    TOW = "TOW"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class TripType(str, Enum):
    ONE_WAY = "ONE_WAY"
    ROUND_TRIP = "ROUND_TRIP"


class CoverageChoice(str, Enum):
    SELECTED = "SELECTED"
    DECLINED = "DECLINED"


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class FulfillmentStatus(str, Enum):
    AWAITING_DISPATCH = "AWAITING_DISPATCH"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED_CLEAN = "RETURNED_CLEAN"
    RETURNED_DAMAGED = "RETURNED_DAMAGED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class TransferReason(str, Enum):
    ONE_WAY_REBALANCE = "ONE_WAY_REBALANCE"
    FLEET_REBALANCE = "FLEET_REBALANCE"


class AddOnType(str, Enum):
    UTILITY_DOLLY = "UTILITY_DOLLY"
    APPLIANCE_DOLLY = "APPLIANCE_DOLLY"
    FURNITURE_PAD_DOZEN = "FURNITURE_PAD_DOZEN"


class LedgerKind(str, Enum):
    BASE_DAYS = "BASE_DAYS"
    MILEAGE = "MILEAGE"
    ONE_WAY_FLAT = "ONE_WAY_FLAT"
    ADDON = "ADDON"
    COVERAGE = "COVERAGE"
    FUEL_SHORTFALL = "FUEL_SHORTFALL"
    LATE_RETURN = "LATE_RETURN"
    DAMAGE = "DAMAGE"
    SUPPLY = "SUPPLY"
    SUPPLY_REFUND = "SUPPLY_REFUND"


# ── Entity TypedDicts (common_fields: true) ──────────────────────────────
class RentalLocation(TypedDict):
    id: str
    name: str
    state_code: str
    lot_capacity: int
    on_lot_count: int
    accepts_one_way_dropoff: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentClass(TypedDict):
    id: str
    code: str
    category: str
    daily_rate_cents: int
    mileage_rate_cents: int
    one_way_flat_cents: int
    fuel_capacity_gallons: float
    requires_coverage: bool
    created_at: str
    updated_at: str
    version: int


class CoveragePlan(TypedDict):
    id: str
    code: str
    daily_fee_cents: int
    damage_deductible_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class MovingSupply(TypedDict):
    id: str
    sku: str
    unit_price_cents: int
    stock_qty: int
    returnable: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    license_verified: bool
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    customer_id: str
    equipment_class_id: str
    pickup_location_id: str
    dropoff_location_id: str
    coverage_plan_id: Optional[str]
    trip_type: str
    coverage_choice: str
    scheduled_pickup_at: str
    scheduled_return_at: str
    planned_days: int
    booking_status: str
    fulfillment_status: str
    assigned_equipment_id: Optional[str]
    quoted_total_cents: int
    created_at: str
    updated_at: str
    version: int


class EquipmentAddOn(TypedDict):
    id: str
    reservation_id: str
    addon_type: str
    quantity: int
    daily_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class SupplyLineItem(TypedDict):
    id: str
    reservation_id: str
    supply_id: str
    quantity: int
    unit_price_cents: int
    refunded_units: int
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    equipment_class_id: str
    home_location_id: str
    current_location_id: Optional[str]
    status: str
    odometer_miles: int
    fuel_level_eighths: int
    created_at: str
    updated_at: str
    version: int


class RentalContract(TypedDict):
    id: str
    reservation_id: str
    equipment_id: str
    pickup_odometer_miles: int
    pickup_fuel_eighths: int
    return_odometer_miles: Optional[int]
    return_fuel_eighths: Optional[int]
    miles_driven: Optional[int]
    actual_return_at: Optional[str]
    status: str
    settlement_total_cents: Optional[int]
    damage_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class DropOffTransfer(TypedDict):
    id: str
    equipment_id: str
    from_location_id: str
    to_location_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ── Append-only event records (common_fields: false) ─────────────────────
class DamageReport(TypedDict):
    id: str
    contract_id: str
    assessed_cost_cents: int
    description: str
    created_at: str


class ChargeLedgerEntry(TypedDict):
    id: str
    contract_id: str
    kind: str
    amount_cents: int
    created_at: str
