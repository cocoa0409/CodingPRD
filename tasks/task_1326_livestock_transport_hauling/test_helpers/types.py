"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CARRIER_ADMIN = "CarrierAdmin"
    DISPATCHER = "Dispatcher"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    DRIVER = "Driver"
    CONSIGNEE_AGENT = "ConsigneeAgent"
    WASHOUT_OPERATOR = "WashoutOperator"


class Species(str, Enum):
    CATTLE = "CATTLE"
    SWINE = "SWINE"
    SHEEP = "SHEEP"
    HORSES = "HORSES"


class LoadStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    PAPERWORK_VERIFIED = "PAPERWORK_VERIFIED"
    ASSIGNED = "ASSIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    WEATHER_HOLD = "WEATHER_HOLD"
    REST_UNLOAD = "REST_UNLOAD"
    ARRIVED = "ARRIVED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class HosStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    BREAK_REQUIRED = "BREAK_REQUIRED"
    SESSION_EXHAUSTED = "SESSION_EXHAUSTED"
    WINDOW_CLOSED = "WINDOW_CLOSED"
    CYCLE_EXHAUSTED = "CYCLE_EXHAUSTED"


class DutyEventType(str, Enum):
    DUTY_ON = "DUTY_ON"
    DUTY_OFF = "DUTY_OFF"
    DRIVING_ON = "DRIVING_ON"
    DRIVING_OFF = "DRIVING_OFF"
    BREAK_START = "BREAK_START"
    BREAK_END = "BREAK_END"


class DutyEventSource(str, Enum):
    MANUAL = "MANUAL"
    SYSTEM = "SYSTEM"


class WashoutStatus(str, Enum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"
    STALE = "STALE"


class WashoutMethod(str, Enum):
    HIGH_PRESSURE = "HIGH_PRESSURE"
    STEAM = "STEAM"
    CHEMICAL = "CHEMICAL"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ReleaseReason(str, Enum):
    REPLANNED = "REPLANNED"
    CANCELLED = "CANCELLED"
    DELIVERED = "DELIVERED"


class PaperStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class TicketType(str, Enum):
    ORIGIN = "ORIGIN"
    DELIVERY = "DELIVERY"


class SettlementStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    PENDING = "PENDING"
    DISPUTED = "DISPUTED"
    COUNTERED = "COUNTERED"
    RESOLVED = "RESOLVED"
    PAID = "PAID"


class IncidentType(str, Enum):
    INJURY = "INJURY"
    DOWNER = "DOWNER"
    DEAD_ON_ARRIVAL = "DEAD_ON_ARRIVAL"
    ESCAPE = "ESCAPE"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class HoldType(str, Enum):
    HEAT = "HEAT"
    COLD = "COLD"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


# --- Entities carrying the full standard set: id + created_at + updated_at + version ---

class Shipper(TypedDict):
    id: str
    name: str
    contact_email: str
    default_shrink_allowance_pct: float
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    name: str
    license_no: str
    status: str
    session_driving_minutes: int
    calendar_day_driving_minutes: int
    cycle_on_duty_minutes_8d: int
    driving_since_break_minutes: int
    duty_window_expires_at: Optional[str]
    hos_status: str
    critical_incident_count_90d: int
    created_at: str
    updated_at: str
    version: int


class Trailer(TypedDict):
    id: str
    trailer_no: str
    max_gross_weight_lb: int
    washout_status: str
    last_washed_at: Optional[str]
    washout_valid_until: Optional[str]
    dirtied_at: Optional[str]
    reserved_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrailerCompartment(TypedDict):
    id: str
    trailer_id: str
    compartment_index: int
    max_head_count: int
    max_weight_lb: int
    occupied_head_count: int
    occupied_weight_lb: int
    created_at: str
    updated_at: str
    version: int


class Load(TypedDict):
    id: str
    shipper_id: str
    species: str
    declared_head_count: int
    declared_weight_lb: int
    origin: str
    destination: str
    planned_departure_at: str
    planned_duration_hours: int
    rate_per_loaded_mile_cents: int
    loaded_miles: int
    shrink_allowance_pct: Optional[float]
    effective_shrink_pct: float
    backhaul_of_load_id: Optional[str]
    is_backhaul: bool
    driver_id: Optional[str]
    trailer_id: Optional[str]
    status: str
    allocated_head_count: int
    allocated_weight_lb: int
    confinement_anchor_at: Optional[str]
    rest_unload_started_at: Optional[str]
    departed_at: Optional[str]
    arrived_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompartmentAllocation(TypedDict):
    id: str
    load_id: str
    trailer_compartment_id: str
    head_count: int
    avg_weight_lb: float
    weight_lb: int
    status: str
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HealthPaper(TypedDict):
    id: str
    load_id: str
    cert_number: str
    species: str
    head_count_listed: int
    issued_at: str
    expires_at: str
    status: str
    created_by_user_id: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BrandInspection(TypedDict):
    id: str
    load_id: str
    inspection_no: str
    inspected_at: str
    brand_owner: str
    head_count_inspected: int
    status: str
    created_by_user_id: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    load_id: str
    status: str
    base_amount_cents: int
    provisional_amount_cents: int
    shrink_allowance_lb: int
    delivered_weight_lb: Optional[int]
    effective_delivered_weight_lb: Optional[int]
    shrink_lb: int
    excess_shrink_lb: int
    shrink_penalty_cents: int
    welfare_deduction_cents: int
    dispute_adjustment_cents: int
    final_amount_cents: int
    dispute_deadline_at: Optional[str]
    disputed_weight_lb: Optional[int]
    counter_weight_lb: Optional[int]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WelfareIncident(TypedDict):
    id: str
    load_id: str
    driver_id: str
    incident_type: str
    severity: str
    head_count_affected: int
    occurred_at: str
    description: Optional[str]
    status: str
    fine_cents: int
    fine_waived: bool
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WeatherHold(TypedDict):
    id: str
    load_id: str
    hold_type: str
    temperature_f: int
    reason: Optional[str]
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only records: carry ONLY id + created_at (no updated_at, no version) ---

class DriverDutyEvent(TypedDict):
    id: str
    driver_id: str
    event_type: str
    occurred_at: str
    source: str
    load_id: Optional[str]
    created_at: str


class WashoutEvent(TypedDict):
    id: str
    trailer_id: str
    washed_at: str
    method: str
    operator_note: Optional[str]
    created_at: str


class WeightTicket(TypedDict):
    id: str
    load_id: str
    ticket_type: str
    gross_lb: int
    tare_lb: int
    net_weight_lb: int
    weighed_at: str
    created_at: str
