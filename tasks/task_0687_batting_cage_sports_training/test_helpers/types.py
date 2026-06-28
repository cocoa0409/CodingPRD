"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Batting Cage & Sports-Training PRD. Times are UTC ISO 8601.
Monetary amounts are integer cents; tokens and minutes are integers.
"""
from enum import Enum
from typing import TypedDict, List


class UserRole(str, Enum):
    FACILITY_MANAGER = "FacilityManager"
    FRONT_DESK = "FrontDesk"
    MEMBER = "Member"
    INSTRUCTOR = "Instructor"


class FacilityPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class LaneKind(str, Enum):
    CAGE = "CAGE"
    TUNNEL = "TUNNEL"
    LANE = "LANE"


class LaneMaintStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    CLOSED = "CLOSED"


class MachineModel(str, Enum):
    WHEEL = "WHEEL"
    ARM = "ARM"
    SOFT_TOSS = "SOFT_TOSS"


class MachineStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class MaintenanceSeverity(str, Enum):
    ROUTINE = "ROUTINE"
    CRITICAL = "CRITICAL"


class MaintenanceStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class MemberTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    GOLD = "GOLD"


class WaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    VOID = "VOID"


class BookingKind(str, Enum):
    OPEN_SLOT = "OPEN_SLOT"
    LESSON = "LESSON"
    TEAM_BLOCK = "TEAM_BLOCK"
    PARTY = "PARTY"


class PayMode(str, Enum):
    TOKEN = "TOKEN"
    HOURLY = "HOURLY"
    MEMBERSHIP = "MEMBERSHIP"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    NO_SHOW = "NO_SHOW"


class ProgramKind(str, Enum):
    LEAGUE = "LEAGUE"
    CLINIC = "CLINIC"


class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


# --- Entity TypedDicts ---
# common_fields: true -> id + created_at + updated_at + version


class Facility(TypedDict):
    id: str
    name: str
    timezone: str
    open_minute: int
    close_minute: int
    token_price_cents: int
    hourly_rate_cents: int
    posture: str
    open_incident_count: int
    epoch_index: int
    created_at: str
    updated_at: str
    version: int


class Lane(TypedDict):
    id: str
    facility_id: str
    label: str
    kind: str
    buffer_minutes: int
    hourly_rate_cents: int
    maint_status: str
    created_at: str
    updated_at: str
    version: int


class PitchingMachine(TypedDict):
    id: str
    facility_id: str
    lane_id: str
    model: str
    pitch_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict):
    id: str
    facility_id: str
    lane_id: str
    start_utc: str
    end_utc: str
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    facility_id: str
    full_name: str
    tier: str
    token_balance: int
    monthly_member_minutes_used: int
    no_show_strikes: int
    waiver_ok: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> Waiver carries ONLY id + created_at (no updated_at, no version)
class Waiver(TypedDict):
    id: str
    facility_id: str
    member_id: str
    signed_at: str
    expires_at: str
    status: str
    created_at: str


class Instructor(TypedDict):
    id: str
    facility_id: str
    full_name: str
    rate_cents_per_hour: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    facility_id: str
    lane_id: str
    member_id: str
    instructor_id: str
    machine_id: str
    kind: str
    pay_mode: str
    lane_count: int
    team_lane_ids: List[str]
    party_guests: int
    start_utc: str
    end_utc: str
    duration_minutes: int
    quoted_cost_cents: int
    final_cost_cents: int
    token_cost: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    facility_id: str
    lane_id: str
    kind: str
    capacity: int
    price_cents: int
    session_start_utc: str
    session_end_utc: str
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    facility_id: str
    program_id: str
    member_id: str
    status: str
    charged_cents: int
    created_at: str
    updated_at: str
    version: int
