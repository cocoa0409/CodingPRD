"""Domain types: entity TypedDicts, status enums, role enum.

Every primary resource carries the full common-fields quartet
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------
class UserRole(str, Enum):
    SCHEDULING_PLANNER = "SchedulingPlanner"
    OPERATIONS_CONTROLLER = "OperationsController"
    CREW_MEMBER = "CrewMember"


# ---------------------------------------------------------------------
# Enums for entity-level status / state fields
# ---------------------------------------------------------------------
class CrewRank(str, Enum):
    CAPTAIN = "CAPTAIN"
    FIRST_OFFICER = "FIRST_OFFICER"
    PURSER = "PURSER"
    FLIGHT_ATTENDANT = "FLIGHT_ATTENDANT"


class LineType(str, Enum):
    LINEHOLDER = "LINEHOLDER"
    RESERVE = "RESERVE"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_DUTY = "ON_DUTY"
    ON_REST = "ON_REST"
    SICK = "SICK"
    INACTIVE = "INACTIVE"


class PairingState(str, Enum):
    DRAFT = "DRAFT"
    BID_OPEN = "BID_OPEN"
    BID_CLOSED = "BID_CLOSED"
    AWARDED = "AWARDED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LegType(str, Enum):
    REVENUE = "REVENUE"
    DEADHEAD = "DEADHEAD"


class BidState(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    UNSUCCESSFUL = "UNSUCCESSFUL"
    WITHDRAWN = "WITHDRAWN"


class AssignmentState(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"
    RECOVERED = "RECOVERED"
    CANCELLED = "CANCELLED"


class AssignmentSource(str, Enum):
    BID_AWARD = "BID_AWARD"
    RESERVE_CALLUP = "RESERVE_CALLUP"
    TRIP_TRADE = "TRIP_TRADE"


class SickCallState(str, Enum):
    REPORTED = "REPORTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLOSED = "CLOSED"


class SickReasonCode(str, Enum):
    ILLNESS = "ILLNESS"
    INJURY = "INJURY"
    FAMILY_EMERGENCY = "FAMILY_EMERGENCY"


class ReserveCallupState(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class TripTradeState(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERSIGNED = "COUNTERSIGNED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 — all primary entities carry the full quartet)
# ---------------------------------------------------------------------
class CrewMember(TypedDict):
    id: str
    employee_code: str
    full_name: str
    rank: str
    base_airport: str
    seniority_number: int
    line_type: str
    status: str
    total_flight_minutes_7d: int
    total_duty_minutes_7d: int
    last_off_duty_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Pairing(TypedDict):
    id: str
    pairing_code: str
    origin_base: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    required_captains: int
    required_first_officers: int
    required_cabin_crew: int
    state: str
    bidding_close_utc: str
    total_flight_minutes: int
    total_duty_minutes: int
    scheduled_block_minutes: int
    actual_block_minutes: int
    created_at: str
    updated_at: str
    version: int


class FlightLeg(TypedDict):
    id: str
    pairing_id: str
    leg_sequence: int
    departure_airport: str
    arrival_airport: str
    scheduled_departure_utc: str
    scheduled_arrival_utc: str
    leg_type: str
    flight_minutes: int
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    pairing_id: str
    crew_member_id: str
    requested_seat: str
    state: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    pairing_id: str
    crew_member_id: str
    seat: str
    source: str
    state: str
    actual_duty_start_utc: Optional[str]
    actual_duty_end_utc: Optional[str]
    flight_minutes_credited: int
    duty_minutes_credited: int
    created_at: str
    updated_at: str
    version: int


class SickCall(TypedDict):
    id: str
    assignment_id: str
    reported_utc: str
    reason_code: str
    state: str
    hours_before_departure: int
    created_at: str
    updated_at: str
    version: int


class ReserveCallup(TypedDict):
    id: str
    sick_call_id: str
    callup_sequence: int
    selected_reserve_id: str
    state: str
    offered_utc: str
    replacement_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TripTrade(TypedDict):
    id: str
    initiator_assignment_id: str
    counterparty_assignment_id: str
    initiator_id: str
    counterparty_id: str
    state: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
