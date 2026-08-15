"""Domain types: entity TypedDicts, status enums, role enum.

Ledger-style append-only resources (FlightLog, InvoiceLineItem, AgencyRecord)
carry only ``id`` and ``created_at`` per the PRD common-properties rule; every
other primary resource also carries ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CARRIER_OPS = "CarrierOps"
    AGENCY_DISPATCHER = "AgencyDispatcher"
    PILOT = "Pilot"
    CARRIER_FINANCE = "CarrierFinance"
    AGENCY_FINANCE = "AgencyFinance"
    CARDING_INSPECTOR = "CardingInspector"
    SYSTEM_ADMIN = "SystemAdmin"


class Agency(str, Enum):
    USFS = "USFS"
    CAL_FIRE = "CAL_FIRE"


class ContractType(str, Enum):
    EXCLUSIVE_USE = "EXCLUSIVE_USE"
    CALL_WHEN_NEEDED = "CALL_WHEN_NEEDED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AircraftCardingStatus(str, Enum):
    UNCARDED = "UNCARDED"
    CARDED = "CARDED"
    SUSPENDED = "SUSPENDED"
    DECARDED = "DECARDED"


class CrewCardingStatus(str, Enum):
    UNCARDED = "UNCARDED"
    CARDED = "CARDED"
    SUSPENDED = "SUSPENDED"


class DutyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FATIGUE_HOLD = "FATIGUE_HOLD"


class CrewRole(str, Enum):
    PIC = "PIC"
    SIC = "SIC"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class InspectionResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class AvailabilityStatus(str, Enum):
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    UNAVAILABLE = "UNAVAILABLE"
    EXCUSED = "EXCUSED"


class ExcuseReason(str, Enum):
    MAINTENANCE = "MAINTENANCE"
    CARDING = "CARDING"
    WEATHER = "WEATHER"
    AGENCY_RELEASE = "AGENCY_RELEASE"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    ACTIVE = "ACTIVE"
    CONTAINED = "CONTAINED"
    CLOSED = "CLOSED"


class IncidentPriority(str, Enum):
    INITIAL_ATTACK = "INITIAL_ATTACK"
    EXTENDED_ATTACK = "EXTENDED_ATTACK"


class DispatchOrderStatus(str, Enum):
    PLACED = "PLACED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    ON_INCIDENT = "ON_INCIDENT"
    RELEASED = "RELEASED"
    DEMOBILIZED = "DEMOBILIZED"


class ReleaseReason(str, Enum):
    AGENCY = "AGENCY"
    MECHANICAL = "MECHANICAL"
    FATIGUE = "FATIGUE"


class RetardantLoadStatus(str, Enum):
    REQUESTED = "REQUESTED"
    LOADED = "LOADED"
    DROPPED = "DROPPED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    RECONCILED = "RECONCILED"
    PAID = "PAID"
    VOID = "VOID"


class BillingBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    RECONCILED = "RECONCILED"


class LineType(str, Enum):
    AVAILABILITY_DAY = "AVAILABILITY_DAY"
    FLIGHT_DAY = "FLIGHT_DAY"
    PENALTY = "PENALTY"


class Contract(TypedDict):
    id: str
    contract_number: str
    agency: str
    contract_type: str
    daily_availability_rate_cents: int
    flight_hour_rate_cents: int
    season_start_date: str
    season_end_date: str
    min_daily_available_minutes: int
    season_flight_hour_cap_tenths: int
    acceptance_window_minutes: int
    status: str
    season_billed_cents: int
    season_flight_hours_tenths: int
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    tail_number: str
    model: str
    tank_capacity_gallons: int
    contract_id: str
    carding_status: str
    carded_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    full_name: str
    crew_role: str
    contract_id: str
    qualified_aircraft_models: List[str]
    carding_status: str
    carded_until: Optional[str]
    duty_status: str
    created_at: str
    updated_at: str
    version: int


class CardingInspection(TypedDict):
    id: str
    subject_aircraft_id: Optional[str]
    subject_crew_member_id: Optional[str]
    scheduled_for: str
    valid_days: int
    status: str
    result: str
    completed_at: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AvailabilityPeriod(TypedDict):
    id: str
    contract_id: str
    aircraft_id: str
    service_date: str
    available_start: str
    available_end: str
    status: str
    excuse_reason: Optional[str]
    available_minutes: int
    availability_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    incident_number: str
    name: str
    location: str
    agency: str
    priority: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DispatchOrder(TypedDict):
    id: str
    order_number: str
    contract_id: str
    incident_id: str
    aircraft_quantity: int
    required_model: Optional[str]
    placed_at: str
    accept_deadline: str
    status: str
    filled_count: int
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    dispatch_order_id: str
    aircraft_id: str
    pilot_id: str
    planned_start: str
    planned_end: str
    status: str
    assigned_at: str
    launched_at: Optional[str]
    arrived_at: Optional[str]
    released_at: Optional[str]
    demobilized_at: Optional[str]
    release_reason: Optional[str]
    reload_turn_avg_minutes: Optional[float]
    reload_sla_breach: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class FlightLog(TypedDict):
    id: str
    created_at: str
    assignment_id: str
    pilot_id: str
    logged_date: str
    hobbs_start: float
    hobbs_stop: float
    flight_hours_tenths: int
    billable_cents: int


class RetardantLoad(TypedDict):
    id: str
    assignment_id: str
    gallons: int
    requested_at: str
    loaded_at: Optional[str]
    dropped_at: Optional[str]
    status: str
    reload_turn_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CrewDutyDay(TypedDict):
    id: str
    crew_member_id: str
    duty_date: str
    duty_start: Optional[str]
    flown_tenths: int
    projected_tenths: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    contract_id: str
    period_start: str
    period_end: str
    status: str
    billing_basis: str
    availability_subtotal_cents: int
    flight_subtotal_cents: int
    penalty_cents: int
    net_cents: int
    submitted_by: Optional[str]
    submitted_at: Optional[str]
    reconciled_by: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class InvoiceLineItem(TypedDict):
    id: str
    created_at: str
    invoice_id: str
    line_type: str
    reference_date: str
    source_ref_id: str
    carrier_qty: int
    carrier_amount_cents: int
    agency_qty: Optional[int]
    agency_amount_cents: Optional[int]
    billed_amount_cents: int
    mismatch_flag: bool


# common_fields: false — append-only, carries ONLY id + created_at
class AgencyRecord(TypedDict):
    id: str
    created_at: str
    contract_id: str
    assignment_id: str
    record_date: str
    agency_flight_hours_tenths: int
    agency_available_minutes: Optional[int]
