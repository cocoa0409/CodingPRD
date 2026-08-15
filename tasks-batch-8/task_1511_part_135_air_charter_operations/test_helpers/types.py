"""Domain types: entity TypedDicts, status enums, role enum.

Primary resources carry the standard system-managed fields (id, created_at,
updated_at, version) described in PRD section "Common Resource Properties".
The three ledger-style resources (Payment, FlightLog, WeatherAdvisory) carry
only id and created_at — updated_at and version are absent from them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    SALES_AGENT = "SalesAgent"
    DISPATCH_MANAGER = "DispatchManager"
    MAINTENANCE_CONTROLLER = "MaintenanceController"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AIRCRAFT_OWNER = "AircraftOwner"
    CREW_MEMBER = "CrewMember"


class AircraftCategory(str, Enum):
    TURBOPROP = "TURBOPROP"
    LIGHT_JET = "LIGHT_JET"
    MIDSIZE_JET = "MIDSIZE_JET"
    HEAVY_JET = "HEAVY_JET"


class AircraftStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_TRIP = "IN_TRIP"
    MAINTENANCE_HOLD = "MAINTENANCE_HOLD"
    GROUNDED = "GROUNDED"


class CrewMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TripStatus(str, Enum):
    QUOTE_DRAFT = "QUOTE_DRAFT"
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PaymentPosture(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED_PARTIAL = "REFUNDED_PARTIAL"
    REFUNDED_FULL = "REFUNDED_FULL"


class LegType(str, Enum):
    REVENUE = "REVENUE"
    POSITIONING = "POSITIONING"


class AssignmentStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class DutyRole(str, Enum):
    PIC = "PIC"
    SIC = "SIC"


class CrewAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VETTED = "VETTED"
    FLAGGED_ILLEGAL = "FLAGGED_ILLEGAL"
    RELEASED = "RELEASED"


class WindowType(str, Enum):
    INSPECTION_100H = "INSPECTION_100H"
    ANNUAL = "ANNUAL"
    AOG_REPAIR = "AOG_REPAIR"


class WindowStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TsaStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class PermitType(str, Enum):
    OVERFLIGHT = "OVERFLIGHT"
    LANDING = "LANDING"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class PaymentType(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"


class SubjectType(str, Enum):
    AIRCRAFT = "AIRCRAFT"
    CREW_MEMBER = "CREW_MEMBER"
    TRIP_REQUEST = "TRIP_REQUEST"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class Severity(str, Enum):
    SIGMET = "SIGMET"
    CONVECTIVE = "CONVECTIVE"
    WINTER = "WINTER"
    OTHER = "OTHER"


class CancelReason(str, Enum):
    CUSTOMER = "CUSTOMER"
    WEATHER = "WEATHER"
    OPS = "OPS"


# --- Entity TypedDicts (common fields: id, created_at, updated_at, version) ---

class AircraftOwner(TypedDict, total=False):
    id: str
    name: str
    contact_email: str
    revenue_share_pct: float
    guarantee_cents_per_block_min: int
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict, total=False):
    id: str
    owner_id: str
    tail_number: str
    category: str
    home_base_icao: str
    seats: int
    hourly_rate_cents: int
    on_ops_spec: bool
    initial_airframe_minutes: int
    total_airframe_minutes: int
    next_check_due_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    name: str
    base_icao: str
    qualified_categories: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TripRequest(TypedDict, total=False):
    id: str
    customer_name: str
    customer_email: str
    requested_category: str
    origin_icao: str
    destination_icao: str
    departure_at: str
    passenger_count: int
    international: bool
    status: str
    payment_posture: str
    quoted_total_cents: Optional[int]
    deposit_required_cents: Optional[int]
    quote_valid_until: Optional[str]
    collected_cents: int
    final_total_cents: Optional[int]
    cancellation_reason: Optional[str]
    cancellation_fee_cents: Optional[int]
    refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class QuoteLeg(TypedDict, total=False):
    id: str
    trip_request_id: str
    seq_no: int
    leg_type: str
    origin_icao: str
    destination_icao: str
    block_minutes: int
    fuel_stop: bool
    created_at: str
    updated_at: str
    version: int


class AircraftAssignment(TypedDict, total=False):
    id: str
    trip_request_id: str
    aircraft_id: str
    status: str
    occupied_start_at: str
    occupied_end_at: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    trip_request_id: str
    crew_member_id: str
    duty_role: str
    status: str
    planned_duty_minutes: Optional[int]
    duty_legal: Optional[bool]
    rest_legal: Optional[bool]
    vetted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    aircraft_id: str
    window_type: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Passenger(TypedDict, total=False):
    id: str
    trip_request_id: str
    full_name: str
    date_of_birth: str
    tsa_status: str
    screened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OverflightPermit(TypedDict, total=False):
    id: str
    trip_request_id: str
    country_code: str
    permit_type: str
    required: bool
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Ledger-style resources: ONLY id + created_at (no updated_at, no version) ---

class Payment(TypedDict, total=False):
    id: str
    trip_request_id: str
    payment_type: str
    amount_cents: int
    status: str
    created_at: str


class FlightLog(TypedDict, total=False):
    id: str
    trip_request_id: str
    quote_leg_id: str
    actual_block_minutes: int
    departed_at: str
    arrived_at: str
    recorded_by_crew_id: str
    created_at: str


class WeatherAdvisory(TypedDict, total=False):
    id: str
    station_icao: str
    severity: str
    starts_at: str
    ends_at: str
    created_at: str


class OwnerStatement(TypedDict, total=False):
    id: str
    owner_id: str
    trip_request_id: str
    gross_cents: int
    standard_share_cents: int
    guarantee_floor_cents: int
    owner_share_cents: int
    operator_retained_cents: int
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceFinding(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    finding_code: str
    grounding: bool
    notes: Optional[str]
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
