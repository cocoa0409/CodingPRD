"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries the four
system-managed fields (id, created_at, updated_at, version) described in the
PRD's common-resource-properties section.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    EXECUTIVE_REQUESTER = "ExecutiveRequester"
    DISPATCHER = "Dispatcher"
    FLIGHT_DEPT_MANAGER = "FlightDeptManager"
    MAINTENANCE_PLANNER = "MaintenancePlanner"
    FINANCE_ADMIN = "FinanceAdmin"


class AircraftType(str, Enum):
    LIGHT_JET = "LIGHT_JET"
    MIDSIZE_JET = "MIDSIZE_JET"
    HEAVY_JET = "HEAVY_JET"
    TURBOPROP = "TURBOPROP"


class AircraftStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GROUNDED = "GROUNDED"
    RETIRED = "RETIRED"


class AircraftPosture(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE_HOLD = "MAINTENANCE_HOLD"
    DOCUMENT_LAPSE = "DOCUMENT_LAPSE"


class DocKind(str, Enum):
    AIRWORTHINESS_CERT = "AIRWORTHINESS_CERT"
    REGISTRATION = "REGISTRATION"
    INSURANCE = "INSURANCE"
    OPS_SPECS = "OPS_SPECS"
    NOISE_CERT = "NOISE_CERT"
    INTERNATIONAL_PERMIT = "INTERNATIONAL_PERMIT"


class DocumentStatus(str, Enum):
    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"


class SeatQualification(str, Enum):
    PIC = "PIC"
    SIC = "SIC"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class PriorityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class TripKind(str, Enum):
    BUSINESS = "BUSINESS"
    PERSONAL = "PERSONAL"
    MIXED = "MIXED"


class ApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AssignmentStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"


class FlightLegStatus(str, Enum):
    PLANNED = "PLANNED"
    AIRCRAFT_ASSIGNED = "AIRCRAFT_ASSIGNED"
    CREWED = "CREWED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MaintenanceKind(str, Enum):
    SCHEDULED_INSPECTION = "SCHEDULED_INSPECTION"
    UNSCHEDULED_REPAIR = "UNSCHEDULED_REPAIR"
    AVIONICS_UPGRADE = "AVIONICS_UPGRADE"
    ENGINE_OVERHAUL = "ENGINE_OVERHAUL"


class MaintenanceWindowStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CateringOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class GroundTransportStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CharterSupplementStatus(str, Enum):
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry the four system-managed fields)
# ---------------------------------------------------------------------------

class Aircraft(TypedDict, total=False):
    id: str
    tail_number: str
    aircraft_type: str
    passenger_capacity: int
    home_base_icao: str
    status: str
    posture: str
    posture_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DocumentPermit(TypedDict, total=False):
    id: str
    aircraft_id: str
    doc_kind: str
    identifier: str
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    employee_number: str
    full_name: str
    seat_qualification: str
    type_ratings: List[str]
    training_valid_until: str
    duty_window_start_utc: Optional[str]
    duty_minutes_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BusinessUnit(TypedDict, total=False):
    id: str
    bu_code: str
    name: str
    annual_flight_budget_cents: int
    allocated_cents: int
    created_at: str
    updated_at: str
    version: int


class PassengerProfile(TypedDict, total=False):
    id: str
    employee_number: str
    full_name: str
    priority_tier: str
    home_bu_id: str
    sifl_control_employee: bool
    created_at: str
    updated_at: str
    version: int


class TripRequest(TypedDict, total=False):
    id: str
    requester_id: str
    charge_bu_id: str
    trip_kind: str
    purpose: str
    requested_departure_utc: str
    requested_return_utc: str
    passenger_ids: List[str]
    max_priority_tier: str
    approval_status: str
    assignment_status: str
    personal_use_flag: bool
    personal_use_approved_by: Optional[str]
    assigned_by_user_id: Optional[str]
    dispatched_by_user_id: Optional[str]
    sifl_imputed_income_cents: int
    allocated_cost_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class FlightLeg(TypedDict, total=False):
    id: str
    trip_request_id: str
    leg_sequence: int
    origin_icao: str
    destination_icao: str
    scheduled_departure_utc: str
    scheduled_arrival_utc: str
    distance_statute_miles: int
    aircraft_id: Optional[str]
    pic_crew_id: Optional[str]
    sic_crew_id: Optional[str]
    block_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    aircraft_id: str
    window_start_utc: str
    window_end_utc: str
    maintenance_kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CateringOrder(TypedDict, total=False):
    id: str
    flight_leg_id: str
    vendor_name: str
    menu_code: str
    headcount: int
    quoted_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GroundTransport(TypedDict, total=False):
    id: str
    flight_leg_id: str
    provider_name: str
    pickup_minutes_after_arrival: int
    quoted_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CharterSupplement(TypedDict, total=False):
    id: str
    trip_request_id: str
    vendor_name: str
    quoted_cost_cents: int
    aircraft_type_offered: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SiflRatePeriod(TypedDict, total=False):
    id: str
    period_start_utc: str
    period_end_utc: str
    terminal_charge_cents: int
    rate_band_1_cents_per_mile: int
    rate_band_2_cents_per_mile: int
    rate_band_3_cents_per_mile: int
    control_employee_multiplier_pct: int
    created_at: str
    updated_at: str
    version: int
