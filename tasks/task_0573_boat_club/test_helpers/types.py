"""Domain types: entity TypedDicts, status enums, role enum for the Boat Club API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    MEMBER = "Member"
    DOCK_STAFF = "DockStaff"
    CLUB_ADMIN = "ClubAdmin"


# --- Enumerated value sets ---
class TierCode(str, Enum):
    CRUISE = "CRUISE"
    SAIL = "SAIL"
    UNLIMITED = "UNLIMITED"


class BoatType(str, Enum):
    PONTOON = "PONTOON"
    BOWRIDER = "BOWRIDER"
    DECK_BOAT = "DECK_BOAT"
    CENTER_CONSOLE = "CENTER_CONSOLE"


class SessionType(str, Enum):
    ORIENTATION = "ORIENTATION"
    BASIC_CERT = "BASIC_CERT"
    ADVANCED_CERT = "ADVANCED_CERT"


class FeeType(str, Enum):
    NO_SHOW = "NO_SHOW"
    LATE_RETURN = "LATE_RETURN"
    FUEL = "FUEL"
    CLEANING = "CLEANING"
    DAMAGE = "DAMAGE"


class Severity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class CertLevel(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"


# --- Status enums (state machines) ---
class MemberStatus(str, Enum):
    PENDING_ORIENTATION = "PENDING_ORIENTATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class BoatStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT = "OUT"
    CLEANING = "CLEANING"
    MAINTENANCE = "MAINTENANCE"


class ReservationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class TrainingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FULL = "FULL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class DamageReportStatus(str, Enum):
    FILED = "FILED"
    ASSESSED = "ASSESSED"
    DISMISSED = "DISMISSED"


class FeeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    WAIVED = "WAIVED"
    PAID = "PAID"


class DuesInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    VOID = "VOID"


# --- Entity TypedDicts ---

# common_fields: false — configuration record keyed by tier_code; carries ONLY id + created_at
class MembershipTier(TypedDict, total=False):
    id: str
    tier_code: str
    monthly_dues_cents: int
    max_active_reservations: int
    reservations_per_week: int
    reciprocal_access_allowed: bool
    advance_booking_days_max: int
    created_at: str


class Dock(TypedDict, total=False):
    id: str
    name: str
    location_code: str
    capacity: int
    is_reciprocal: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    membership_tier: str
    home_dock_id: str
    status: str
    orientation_completed: bool
    certification_level: str
    no_show_strikes: int
    last_reinstated_at: Optional[str]
    outstanding_fees_cents: int
    waived_fees_cents: int
    paid_fees_cents: int
    reservations_used_this_week: int
    reservations_remaining_this_week: int
    dues_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Boat(TypedDict, total=False):
    id: str
    dock_id: str
    boat_type: str
    status: str
    fuel_level_pct: float
    usage_count: int
    needs_cleaning: bool
    last_used_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    member_id: str
    dock_id: str
    boat_type: str
    boat_id: Optional[str]
    start_time: str
    end_time: str
    status: str
    fuel_at_checkout: Optional[float]
    fuel_at_return: Optional[float]
    checkout_time: Optional[str]
    return_time: Optional[str]
    provisional_fuel_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict, total=False):
    id: str
    dock_id: str
    session_type: str
    start_time: str
    end_time: str
    capacity: int
    instructor_name: str
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    member_id: str
    session_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageReport(TypedDict, total=False):
    id: str
    reservation_id: str
    boat_id: str
    severity: str
    repair_cost_cents: int
    assessed_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Fee(TypedDict, total=False):
    id: str
    member_id: str
    reservation_id: Optional[str]
    fee_type: str
    amount_cents: int
    status: str
    assessed_at: str
    source_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DuesInvoice(TypedDict, total=False):
    id: str
    member_id: str
    period_start: str
    period_end: str
    base_dues_cents: int
    fees_rolled_cents: int
    estimated_total_cents: int
    final_total_cents: Optional[int]
    rolled_fee_ids: List[str]
    status: str
    issued_at: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
