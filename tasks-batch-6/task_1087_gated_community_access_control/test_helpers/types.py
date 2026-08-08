"""Domain types: entity TypedDicts, status enums, role enum (PRD Sections 3, 5).

Entities carrying the common system fields (PRD Section 2.5) expose
``id``/``created_at``/``updated_at``/``version``. ``GateEvent`` is the sole
append-only log and exposes only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    COMMUNITY_ADMIN = "CommunityAdmin"
    SECURITY_OFFICER = "SecurityOfficer"
    RESIDENT = "Resident"


# --- Status enums ---------------------------------------------------------

class ResidentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    MOVED_OUT = "MOVED_OUT"


class ResidentStanding(str, Enum):
    GOOD = "GOOD"
    DELINQUENT = "DELINQUENT"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class DecalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class DecalTier(str, Enum):
    RESIDENT = "RESIDENT"
    TENANT = "TENANT"
    TEMPORARY = "TEMPORARY"


class PassType(str, Enum):
    GUEST = "GUEST"
    VENDOR = "VENDOR"


class PassAuthStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PassPresenceStatus(str, Enum):
    OFFSITE = "OFFSITE"
    ONSITE = "ONSITE"
    DEPARTED = "DEPARTED"


class GateDirection(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"


class GateMatchedType(str, Enum):
    DECAL = "DECAL"
    PASS = "PASS"
    UNMATCHED = "UNMATCHED"


class GateDecision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class AmenityType(str, Enum):
    POOL = "POOL"
    GYM = "GYM"
    CLUBHOUSE = "CLUBHOUSE"
    TENNIS = "TENNIS"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PatrolStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class IncidentType(str, Enum):
    TRESPASS = "TRESPASS"
    NOISE = "NOISE"
    SPEEDING = "SPEEDING"
    VANDALISM = "VANDALISM"
    UNAUTHORIZED_ACCESS = "UNAUTHORIZED_ACCESS"
    OTHER = "OTHER"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ViolationType(str, Enum):
    SPEEDING = "SPEEDING"
    NOISE = "NOISE"
    PARKING = "PARKING"
    UNAUTHORIZED_GUEST = "UNAUTHORIZED_GUEST"
    GATE_TAILGATING = "GATE_TAILGATING"


class ViolationStatus(str, Enum):
    ISSUED = "ISSUED"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    REDUCED = "REDUCED"
    PAID = "PAID"
    VOID = "VOID"


# --- Entity TypedDicts ----------------------------------------------------

class Community(TypedDict):
    id: str
    name: str
    timezone: str
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    community_id: str
    full_name: str
    email: str
    phone: Optional[str]
    resident_type: str
    unit_label: Optional[str]
    lot_number: Optional[str]
    directory_listed: bool
    callbox_code: str
    status: str
    standing: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    resident_id: str
    plate: str
    plate_state: str
    make: Optional[str]
    model: Optional[str]
    color: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Decal(TypedDict):
    id: str
    vehicle_id: str
    tier: str
    decal_number: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Pass(TypedDict):
    id: str
    sponsor_resident_id: str
    pass_type: str
    visitor_name: str
    visitor_plate: str
    plate_state: Optional[str]
    vendor_company: Optional[str]
    valid_from: str
    valid_until: str
    auth_status: str
    presence_status: str
    estimated_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    entry_at: Optional[str]
    exit_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only log (PRD Section 2.5): only id + created_at beyond read fields.
class GateEvent(TypedDict):
    id: str
    community_id: str
    gate_id: str
    direction: str
    plate_read: str
    plate_state: Optional[str]
    matched_type: str
    matched_id: Optional[str]
    decision: str
    reason: str
    event_at: str
    created_at: str


class Amenity(TypedDict):
    id: str
    community_id: str
    name: str
    amenity_type: str
    capacity: int
    hourly_fee_cents: int
    deposit_cents: int
    open_hour: int
    close_hour: int
    reservable: bool
    created_at: str
    updated_at: str
    version: int


class AmenityReservation(TypedDict):
    id: str
    amenity_id: str
    resident_id: str
    start_at: str
    end_at: str
    party_size: int
    status: str
    quoted_fee_cents: int
    settled_fee_cents: Optional[int]
    checkin_at: Optional[str]
    checkout_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Patrol(TypedDict):
    id: str
    community_id: str
    officer_id: str
    route: Optional[str]
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    community_id: str
    patrol_id: Optional[str]
    incident_type: str
    severity: str
    location: Optional[str]
    description: str
    related_resident_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    community_id: str
    resident_id: str
    incident_id: Optional[str]
    violation_type: str
    base_fine_cents: int
    assessed_fine_cents: int
    repeat_index: int
    paid_amount_cents: Optional[int]
    issued_by_user_id: str
    status: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int
