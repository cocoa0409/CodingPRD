"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class StationPosture(str, Enum):
    NORMAL = "NORMAL"
    FLUID_CONSTRAINED = "FLUID_CONSTRAINED"
    PERMIT_SUSPENDED = "PERMIT_SUSPENDED"


class PadStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class PadSizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class WeatherPrecipType(str, Enum):
    SNOW = "SNOW"
    FREEZING_FOG = "FREEZING_FOG"
    FREEZING_RAIN = "FREEZING_RAIN"
    MIXED = "MIXED"


class WeatherPrecipRate(str, Enum):
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    HEAVY = "HEAVY"


class WeatherSeverity(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class WeatherStatus(str, Enum):
    FORECASTED = "FORECASTED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class StaffingStatus(str, Enum):
    ADEQUATE = "ADEQUATE"
    SHORT = "SHORT"


class FluidType(str, Enum):
    TYPE_I = "TYPE_I"
    TYPE_IV = "TYPE_IV"


class TankStatus(str, Enum):
    EMPTY = "EMPTY"
    REORDER_PENDING = "REORDER_PENDING"
    OK = "OK"


class RequestStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    DEFERRED = "DEFERRED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    EXPIRED = "EXPIRED"


class RequestPriority(str, Enum):
    EMERGENCY = "EMERGENCY"
    SCHEDULED = "SCHEDULED"
    FLEXIBLE = "FLEXIBLE"


class FluidReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    UNRESERVED = "UNRESERVED"


class OperationStatus(str, Enum):
    PLANNED = "PLANNED"
    SPRAYING = "SPRAYING"
    AWAITING_INSPECTION = "AWAITING_INSPECTION"
    CLEARED = "CLEARED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    CANCELLED = "CANCELLED"
    VOIDED = "VOIDED"


class HoldoverVariant(str, Enum):
    TABLE = "TABLE"
    RATE_ADJUSTED = "RATE_ADJUSTED"


class CollectionFlag(str, Enum):
    OK = "OK"
    BELOW_MINIMUM = "BELOW_MINIMUM"


class InspectionKind(str, Enum):
    ACCEPTANCE = "ACCEPTANCE"
    POST_TREATMENT = "POST_TREATMENT"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class SpillClassification(str, Enum):
    REPORTABLE = "REPORTABLE"
    MINOR = "MINOR"


class SpillStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FULFILLED = "FULFILLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"
    SUPERSEDED = "SUPERSEDED"


class PricingVariant(str, Enum):
    MARGINAL_TIER = "MARGINAL_TIER"
    FLAT_TIER = "FLAT_TIER"


class UserRole(str, Enum):
    STATION_ADMIN = "StationAdmin"
    AIRLINE_REP = "AirlineRep"
    PAD_OPERATOR = "PadOperator"
    INSPECTOR = "Inspector"
    ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
    BILLING_CLERK = "BillingClerk"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true entities carry id, created_at, updated_at, version.
# common_fields: false entities (Inspection, EffluentReading) carry only
# id and created_at; they omit updated_at and version entirely.


class DeiceStation(TypedDict, total=False):
    id: str
    code: str
    name: str
    min_collection_pct: float
    fluid_ops_minimum_liters: int
    storm_surcharge_pct: float
    posture: str
    active_supply_alert: bool
    collected_pool_liters: float
    ops_epoch_index: int
    created_at: str
    updated_at: str
    version: int


class DeicePad(TypedDict, total=False):
    id: str
    station_id: str
    code: str
    max_size_class: str
    rated_collection_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherEvent(TypedDict, total=False):
    id: str
    station_id: str
    precip_type: str
    precip_rate: str
    severity: str
    started_at: str
    ended_at: Optional[str]
    required_crew_count: int
    assigned_crew_count: int
    staffing_status: str
    escalation_level: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FluidTank(TypedDict, total=False):
    id: str
    station_id: str
    fluid_type: str
    concentration_pct: int
    capacity_liters: int
    on_hand_liters: float
    reserved_liters: float
    available_liters: float
    reorder_threshold_liters: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Airline(TypedDict, total=False):
    id: str
    code: str
    name: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    monthly_billed_liters: int
    month_key: str
    created_at: str
    updated_at: str
    version: int


class DeiceRequest(TypedDict, total=False):
    id: str
    airline_id: str
    station_id: str
    flight_number: str
    aircraft_type: str
    size_class: str
    scheduled_departure: str
    fluid_type: str
    priority: str
    estimated_liters: int
    assigned_tank_id: Optional[str]
    fluid_reservation_status: str
    assigned_pad_id: Optional[str]
    epochs_in_queue: int
    defer_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeiceOperation(TypedDict, total=False):
    id: str
    request_id: str
    station_id: str
    pad_id: str
    tank_id: str
    parent_operation_id: Optional[str]
    window_start: str
    window_end: str
    oat_celsius: float
    estimated_liters: int
    actual_liters: float
    collected_liters: float
    collection_pct: float
    collection_flag: str
    holdover_minutes: int
    holdover_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    created_at: str
    operation_id: str
    kind: str
    result: str
    findings: str
    inspector_id: str
    # NO updated_at, NO version (common_fields: false)


class DischargePermit(TypedDict, total=False):
    id: str
    station_id: str
    permit_number: str
    effective_from: str
    effective_to: str
    max_single_reading_mg_l: float
    rolling_window_days: int
    rolling_window_max_liters: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EffluentReading(TypedDict, total=False):
    id: str
    created_at: str
    permit_id: str
    measured_at: str
    concentration_mg_l: float
    volume_liters: int
    violation: bool
    # NO updated_at, NO version (common_fields: false)


class SpillReport(TypedDict, total=False):
    id: str
    station_id: str
    tank_id: str
    quantity_liters: float
    occurred_at: str
    classification: str
    reporter_id: str
    confirmed_by: Optional[str]
    closed_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecyclingContract(TypedDict, total=False):
    id: str
    station_id: str
    vendor_name: str
    min_concentration_pct: float
    price_per_liter_cents: int
    contracted_min_liters: int
    delivered_liters: float
    total_revenue_cents: int
    last_shipment_revenue_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    airline_id: str
    station_id: str
    operation_id: str
    supersedes_invoice_id: Optional[str]
    pad_fee_cents: int
    fluid_charge_cents: int
    storm_surcharge_cents: int
    total_cents: int
    pricing_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int
