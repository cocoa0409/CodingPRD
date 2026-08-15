"""Domain types: entity TypedDicts, status enums, role enum.

Field vocabularies mirror the PRD: tracks, coaches, track days, rental blocks,
bookings, drivers, waivers, safety inspections, sessions, incidents, noise
readings, garage assignments, paddock assignments.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    TRACK_OPS = "TrackOps"
    SAFETY_OFFICER = "SafetyOfficer"
    ORGANIZER = "Organizer"
    COACH = "Coach"


class CertLevel(str, Enum):
    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    RACE = "RACE"


class TrackDayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    WEATHER_HOLD = "WEATHER_HOLD"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class Posture(str, Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    SUSPENDED = "SUSPENDED"


class WeatherFlag(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    STOP = "STOP"


class CancelReason(str, Enum):
    CUSTOMER = "CUSTOMER"
    WEATHER = "WEATHER"
    SAFETY = "SAFETY"


class RentalBlockStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class RunGroupClass(str, Enum):
    NOVICE = "NOVICE"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    RACE = "RACE"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class LicenseClass(str, Enum):
    STREET = "STREET"
    CLUB = "CLUB"
    PRO = "PRO"


class WaiverStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"


class SafetyStatus(str, Enum):
    NOT_INSPECTED = "NOT_INSPECTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class InspectionResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class SessionStatus(str, Enum):
    GREEN = "GREEN"
    RED = "RED"
    BLACK = "BLACK"
    CHECKERED = "CHECKERED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    CLEARED = "CLEARED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


# --- Entity bodies -----------------------------------------------------------
# Mutable entities carry id + created_at + updated_at + version.
# Append-only evidence records (waiver, safety inspection, noise reading)
# carry ONLY id + created_at per PRD section on resource identity.


class Track(TypedDict, total=False):
    id: str
    name: str
    noise_limit_db: int
    run_group_capacity: int
    garage_bay_count: int
    paddock_stall_count: int
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict, total=False):
    id: str
    track_id: str
    full_name: str
    cert_level: str
    active: bool
    assigned_booking_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class TrackDay(TypedDict, total=False):
    id: str
    track_id: str
    date: str
    status: str
    posture: str
    weather_flag: str
    open_incident_count: int
    noise_breach_count: int
    ops_run_index: int
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RentalBlock(TypedDict, total=False):
    id: str
    track_day_id: str
    block_index: int
    start_minute: int
    end_minute: int
    max_group_size: int
    seats_reserved: int
    seats_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    rental_block_id: str
    organizer_user_id: str
    group_name: str
    run_group_class: str
    driver_count: int
    insurance_policy_ref: str
    approval_status: str
    payment_status: str
    cancel_policy_snapshot: Optional[Dict[str, Any]]
    refund_cents: int
    coach_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    booking_id: str
    full_name: str
    license_class: str
    waiver_status: str
    safety_status: str
    cleared_to_run: bool
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict, total=False):
    id: str
    driver_id: str
    signed_at_utc: str
    expires_at_utc: str
    signature_payload_hash: str
    created_at: str


class SafetyInspection(TypedDict, total=False):
    id: str
    driver_id: str
    inspector_user_id: str
    helmet_ok: bool
    harness_ok: bool
    result: str
    inspected_at_utc: str
    created_at: str


class Session(TypedDict, total=False):
    id: str
    track_day_id: str
    rental_block_id: str
    run_group_class: str
    status: str
    started_at_utc: Optional[str]
    ended_at_utc: Optional[str]
    lap_count: int
    max_db_observed: int
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    track_day_id: str
    session_id: str
    severity: str
    status: str
    reported_by_user_id: str
    cleared_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NoiseReading(TypedDict, total=False):
    id: str
    track_day_id: str
    session_id: str
    db_level: int
    recorded_at_utc: str
    breach: bool
    created_at: str


class GarageAssignment(TypedDict, total=False):
    id: str
    track_day_id: str
    booking_id: str
    bay_number: int
    power_hookups: int
    water_hookup: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PaddockAssignment(TypedDict, total=False):
    id: str
    track_day_id: str
    booking_id: str
    stall_number: int
    status: str
    created_at: str
    updated_at: str
    version: int
