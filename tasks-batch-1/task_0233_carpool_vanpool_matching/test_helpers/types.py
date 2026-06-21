"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_OPS = "PlatformOps"
    PROGRAM_ADMIN = "ProgramAdmin"
    DRIVER = "Driver"
    RIDER = "Rider"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class EmployerProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class PoolStatus(str, Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MatchRequestStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class TripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BOARDING = "BOARDING"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    CHARGED = "CHARGED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class GrhStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REIMBURSED = "REIMBURSED"
    DENIED = "DENIED"


class GrhDenialReason(str, Enum):
    ANNUAL_CAP = "ANNUAL_CAP"
    EVENT_CAP = "EVENT_CAP"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"


class GrhReasonCode(str, Enum):
    ILLNESS = "ILLNESS"
    OVERTIME = "OVERTIME"
    EMERGENCY = "EMERGENCY"
    DRIVER_CANCEL = "DRIVER_CANCEL"


class PoolKind(str, Enum):
    CARPOOL = "CARPOOL"
    VANPOOL = "VANPOOL"


class LedgerEntryType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class LedgerReason(str, Enum):
    RESERVATION_FINALIZED = "RESERVATION_FINALIZED"
    RESERVATION_CANCELLED = "RESERVATION_CANCELLED"
    TRIP_CANCELLED = "TRIP_CANCELLED"
    GRH_REIMBURSED = "GRH_REIMBURSED"


class ReliabilityEventType(str, Enum):
    COMPLETION = "COMPLETION"
    NO_SHOW = "NO_SHOW"
    LATE_CANCEL = "LATE_CANCEL"
    GRH_OVERUSE = "GRH_OVERUSE"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4)
# Versioned entities carry id + created_at + updated_at + version.
# ---------------------------------------------------------------------------
class EmployerProgram(TypedDict):
    id: str
    employer_name: str
    hov_discount_pct: float
    employer_match_pct: float
    monthly_benefit_cap_cents: int
    grh_annual_cap_cents: int
    grh_per_event_cap_cents: int
    grh_max_events_per_year: int
    subsidy_budget_cents: int
    subsidy_consumed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    employer_program_id: str
    full_name: str
    home_zone: str
    work_zone: str
    can_drive: bool
    wallet_balance_cents: int
    completed_trip_count: int
    no_show_count: int
    reliability_score: float
    month_benefit_used_cents: int
    grh_year_used_cents: int
    grh_year_event_count: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    owner_member_id: str
    plate: str
    seat_capacity: int
    hov_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Pool(TypedDict):
    id: str
    employer_program_id: str
    driver_member_id: str
    vehicle_id: str
    kind: str
    origin_zone: str
    dest_zone: str
    departure_days: List[str]
    base_cost_cents: int
    per_mile_cents: int
    seat_capacity: int
    committed_seat_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MatchRequest(TypedDict):
    id: str
    rider_member_id: str
    origin_zone: str
    dest_zone: str
    needed_days: List[str]
    earliest_departure_min: int
    latest_departure_min: int
    matched_pool_id: Optional[str]
    match_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    pool_id: str
    rider_member_id: str
    recurring_seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    pool_id: str
    departure_at: str
    duration_min: int
    distance_miles: float
    hov_lane_used: bool
    seats_reserved: int
    total_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    trip_id: str
    rider_member_id: str
    seat_count: int
    reservation_status: str
    payment_status: str
    estimate_cost_share_cents: int
    estimate_subsidy_cents: int
    final_cost_share_cents: int
    final_subsidy_cents: int
    net_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class GuaranteedRideHome(TypedDict):
    id: str
    rider_member_id: str
    employer_program_id: str
    trip_id: Optional[str]
    claimed_fare_cents: int
    reason_code: str
    reimbursed_cents: int
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only audit records (PRD §2.4): id + created_at ONLY.
# No updated_at, no version.
# ---------------------------------------------------------------------------
class SubsidyLedgerEntry(TypedDict):
    id: str
    employer_program_id: str
    member_id: str
    reservation_id: Optional[str]
    amount_cents: int
    entry_type: str
    reason: str
    created_at: str


class ReliabilityEvent(TypedDict):
    id: str
    member_id: str
    reservation_id: Optional[str]
    event_type: str
    weight_delta: float
    created_at: str
