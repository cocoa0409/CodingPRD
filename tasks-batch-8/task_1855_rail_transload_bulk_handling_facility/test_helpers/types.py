"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    FACILITY_ADMIN = "FacilityAdmin"
    YARD_MASTER = "YardMaster"
    SAFETY_OFFICER = "SafetyOfficer"
    TRANSFER_OPERATOR = "TransferOperator"
    BILLING_CLERK = "BillingClerk"
    CUSTOMER_REP = "CustomerRep"


class SafetyPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    SUSPENDED = "SUSPENDED"


class ContaminationPolicy(str, Enum):
    STRICT_MATRIX = "STRICT_MATRIX"
    WEIGHTED_SCORE = "WEIGHTED_SCORE"


class CreditStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    CREDIT_WATCH = "CREDIT_WATCH"
    CREDIT_HOLD = "CREDIT_HOLD"


class DemurrageBasis(str, Enum):
    CONSTRUCTIVE = "CONSTRUCTIVE"
    ACTUAL = "ACTUAL"


class SitDayBasis(str, Enum):
    CALENDAR = "CALENDAR"
    BUSINESS = "BUSINESS"


class HazardClass(str, Enum):
    NON_HAZARDOUS = "NON_HAZARDOUS"
    HAZARDOUS = "HAZARDOUS"
    FOOD_GRADE = "FOOD_GRADE"


class SegregationGroup(str, Enum):
    FERTILIZER = "FERTILIZER"
    FOOD_GRAIN = "FOOD_GRAIN"
    CHEMICAL = "CHEMICAL"
    PETROLEUM = "PETROLEUM"


class TrackStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class DerailProtection(str, Enum):
    ENGAGED = "ENGAGED"
    DISENGAGED = "DISENGAGED"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    CLEANING = "CLEANING"


class EquipmentType(str, Enum):
    CONVEYOR = "CONVEYOR"
    PUMP = "PUMP"
    HOSE = "HOSE"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class RailcarPlacement(str, Enum):
    REGISTERED = "REGISTERED"
    ARRIVED = "ARRIVED"
    SPOTTED = "SPOTTED"
    IN_TRANSFER = "IN_TRANSFER"
    EMPTY_AWAITING_CLEANING = "EMPTY_AWAITING_CLEANING"
    CLEANING = "CLEANING"
    READY_FOR_RELEASE = "READY_FOR_RELEASE"
    RELEASED = "RELEASED"
    DEPARTED = "DEPARTED"


class HoldStatus(str, Enum):
    NONE = "NONE"
    SAFETY_HOLD = "SAFETY_HOLD"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class SpotOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class MoveType(str, Enum):
    SPOT = "SPOT"
    PULL = "PULL"


class SwitchOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TransferOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WeightTicketStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    VOIDED = "VOIDED"


class ChargeType(str, Enum):
    DEMURRAGE = "DEMURRAGE"
    SWITCHING = "SWITCHING"
    CLEANING = "CLEANING"
    STORAGE_IN_TRANSIT = "STORAGE_IN_TRANSIT"


class ChargeStatus(str, Enum):
    ACCRUED = "ACCRUED"
    INVOICED = "INVOICED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class WashType(str, Enum):
    RINSE = "RINSE"
    DETERGENT = "DETERGENT"
    STEAM = "STEAM"


# --- Entity TypedDicts (PRD §2.4: most resources carry id + created_at +
# updated_at + version; SafetyIncident and SwitchOrder carry only id +
# created_at) ---


class Facility(TypedDict):
    id: str
    name: str
    free_demurrage_hours: int
    sit_free_days: int
    switch_buffer_minutes: int
    free_switches_per_period: int
    contamination_policy: str
    safety_posture: str
    open_incident_count: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    credit_standing: str
    demurrage_basis: str
    sit_day_basis: str
    allocated_car_spots: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    name: str
    hazard_class: str
    segregation_group: str
    requires_full_clean: bool
    created_at: str
    updated_at: str
    version: int


class Track(TypedDict):
    id: str
    name: str
    spot_capacity: int
    status: str
    derail_protection: str
    occupied_spots: int
    reserved_spots: int
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    name: str
    equipment_type: str
    status: str
    last_product_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyIncident(TypedDict):
    # PRD §2.4: carries only id and created_at — NO updated_at, NO version
    id: str
    severity: str
    description: str
    status: str
    created_at: str


class Railcar(TypedDict):
    id: str
    car_initials: str
    car_number: str
    customer_id: str
    product_id: str
    lot_id: str
    quantity_loaded_tons: float
    quantity_remaining_tons: float
    track_id: Optional[str]
    spot_number: Optional[int]
    placement_status: str
    hold_status: str
    arrival_timestamp: Optional[str]
    placed_timestamp: Optional[str]
    released_timestamp: Optional[str]
    departed_timestamp: Optional[str]
    demurrage_billable_days: int
    demurrage_accrued_cents: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    customer_id: str
    product_id: str
    status: str
    quantity_received_tons: float
    quantity_shipped_tons: float
    quantity_rejected_tons: float
    quantity_on_hand_tons: float
    sit_start_timestamp: str
    sit_free_days: int
    sit_day_basis: str
    sit_daily_rate_cents: int
    sit_billable_days: int
    sit_accrued_cents: int
    close_timestamp: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpotOrder(TypedDict):
    id: str
    railcar_id: str
    track_id: str
    spot_number: int
    window_start: str
    window_end: str
    status: str
    switch_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SwitchOrder(TypedDict):
    # PRD §2.4: carries only id and created_at — NO updated_at, NO version
    id: str
    track_id: str
    move_type: str
    railcar_id: str
    customer_id: str
    window_start: str
    window_end: str
    sequence_number: int
    fee_cents: int
    status: str
    created_at: str


class TransferOrder(TypedDict):
    id: str
    railcar_id: str
    equipment_id: str
    quantity_planned_tons: float
    quantity_completed_tons: float
    risk_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WeightTicket(TypedDict):
    id: str
    transfer_order_id: str
    railcar_id: str
    truck_reference: str
    gross_weight_tons: float
    tare_weight_tons: float
    truck_max_payload_tons: float
    net_weight_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargeEntry(TypedDict):
    id: str
    customer_id: str
    railcar_id: Optional[str]
    invoice_id: Optional[str]
    charge_type: str
    quantity: float
    unit_rate_cents: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    customer_id: str
    period_start: str
    period_end: str
    charge_count: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
