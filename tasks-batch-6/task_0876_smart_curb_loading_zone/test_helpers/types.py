"""Domain types: entity TypedDicts, status enums, role enum.

Field lists mirror the resource shapes described in the PRD (§2.4, §3). Resources
that the PRD calls "deliberately lightweight" — pricing policies, schedule windows,
and ledger entries — carry only id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    PERMITTEE = "Permittee"
    CURB_PLANNER = "CurbPlanner"
    PERMIT_APPROVER = "PermitApprover"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status enums (PRD §3) ---
class PermitteeStatus(str, Enum):
    ACTIVE = "ACTIVE"


class PermitteeType(str, Enum):
    CARRIER = "CARRIER"
    VALET_OPERATOR = "VALET_OPERATOR"
    TNC = "TNC"
    MERCHANT = "MERCHANT"


class ZoneDesignation(str, Enum):
    LOADING = "LOADING"
    VALET = "VALET"
    TNC = "TNC"
    PASSENGER = "PASSENGER"
    METERED = "METERED"
    NO_STANDING = "NO_STANDING"


class ZoneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class SensorOccupancyState(str, Enum):
    VACANT = "VACANT"
    OCCUPIED = "OCCUPIED"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACTIVE = "ACTIVE"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    CANCELLED_BY_EVENT = "CANCELLED_BY_EVENT"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class SessionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ViolationType(str, Enum):
    OVERSTAY = "OVERSTAY"
    NO_PERMIT = "NO_PERMIT"
    UNAUTHORIZED_ZONE = "UNAUTHORIZED_ZONE"
    WRONG_DESIGNATION = "WRONG_DESIGNATION"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    PAID = "PAID"
    DISMISSED = "DISMISSED"


class EventStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EntryType(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"
    ADJUSTMENT = "ADJUSTMENT"
    FINE = "FINE"


# --- Entity TypedDicts ---

# common_fields: true
class Permittee(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    permittee_type: str
    status: str
    outstanding_fines_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — lightweight, only id + created_at
class PricingPolicy(TypedDict):
    id: str
    name: str
    base_rate_cents_per_15min: int
    peak_multiplier_bps: int
    peak_start_hour: int
    peak_end_hour: int
    surge_tier1_ratio_bps: int
    surge_tier1_mult_bps: int
    surge_tier2_ratio_bps: int
    surge_tier2_mult_bps: int
    created_at: str


# common_fields: true
class CurbZone(TypedDict):
    id: str
    name: str
    block_face: str
    length_meters: float
    designation: str
    capacity_slots: int
    pricing_policy_id: str
    base_rate_override_cents: Optional[int]
    status: str
    sensor_occupancy_state: str
    revenue_accrued_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class CurbPermit(TypedDict):
    id: str
    permittee_id: str
    requested_designation: str
    purpose: str
    zone_ids: List[str]
    reviewer_user_id: Optional[str]
    approver_user_id: Optional[str]
    last_change_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — lightweight, only id + created_at
class ScheduleWindow(TypedDict):
    id: str
    permit_id: str
    zone_id: str
    day_of_week: int
    start_minute: int
    end_minute: int
    exclusive: bool
    created_at: str


# common_fields: true
class Reservation(TypedDict):
    id: str
    permit_id: str
    zone_id: str
    start_utc: str
    end_utc: str
    booking_status: str
    payment_status: str
    estimated_price_cents: Optional[int]
    settled_price_cents: Optional[int]
    surge_ratio_bps: Optional[int]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class OccupancySession(TypedDict):
    id: str
    zone_id: str
    reservation_id: Optional[str]
    entered_at: str
    exited_at: Optional[str]
    actual_minutes: Optional[int]
    session_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Citation(TypedDict):
    id: str
    zone_id: str
    permittee_id: str
    occupancy_session_id: Optional[str]
    reservation_id: Optional[str]
    violation_type: str
    issued_at: str
    due_at: str
    fine_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class CurbEvent(TypedDict):
    id: str
    name: str
    start_utc: str
    end_utc: str
    zone_ids: List[str]
    total_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — lightweight, only id + created_at
class LedgerEntry(TypedDict):
    id: str
    entry_type: str
    amount_cents: int
    zone_id: Optional[str]
    reservation_id: Optional[str]
    citation_id: Optional[str]
    memo: Optional[str]
    created_at: str
