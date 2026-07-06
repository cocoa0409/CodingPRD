"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ADMIN = "Admin"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    SUPERVISOR = "Supervisor"
    HEARING_OFFICER = "HearingOfficer"
    MOTORIST = "Motorist"


class PatrolZone(str, Enum):
    DOWNTOWN = "DOWNTOWN"
    RESIDENTIAL = "RESIDENTIAL"
    SCHOOL = "SCHOOL"


class ViolationCodeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ScofflawStatus(str, Enum):
    NONE = "NONE"
    SCOFFLAW = "SCOFFLAW"
    BOOT_ELIGIBLE = "BOOT_ELIGIBLE"
    TOW_ELIGIBLE = "TOW_ELIGIBLE"


class IssuedVia(str, Enum):
    LPR = "LPR"
    HANDHELD = "HANDHELD"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    PAID = "PAID"
    VOID = "VOID"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ECHECK = "ECHECK"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class ContestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    CLOSED_UPHELD = "CLOSED_UPHELD"
    CLOSED_DISMISSED = "CLOSED_DISMISSED"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"


class HearingDecision(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class BootTowType(str, Enum):
    BOOT = "BOOT"
    TOW = "TOW"


class BootTowOrigin(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class BootTowStatus(str, Enum):
    ORDERED = "ORDERED"
    APPLIED = "APPLIED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class RegistrationHoldStatus(str, Enum):
    PLACED = "PLACED"
    CLEARED = "CLEARED"


# ─── Entity TypedDicts ───────────────────────────────────────────
# common_fields: true → id + created_at + updated_at + version


class Officer(TypedDict):
    id: str
    badge_number: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → immutable configuration, id + created_at only
class Beat(TypedDict):
    id: str
    beat_code: str
    name: str
    patrol_zone: str
    created_at: str


class ViolationCode(TypedDict):
    id: str
    code: str
    description: str
    base_fine_cents: int
    is_booting_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → immutable configuration, id + created_at only
class HearingRoom(TypedDict):
    id: str
    room_code: str
    name: str
    created_at: str


class Shift(TypedDict):
    id: str
    officer_id: str
    beat_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    gross_citation_count: int
    net_citation_count: int
    citations_per_hour: float
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    plate: str
    state: str
    outstanding_balance_cents: int
    projected_balance_cents: int
    unpaid_citation_count: int
    scofflaw_status: str
    has_active_registration_hold: bool
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    vehicle_id: str
    shift_id: str
    violation_code_id: str
    officer_id: str
    beat_id: str
    issued_via: str
    evidence_photo_url: str
    fine_amount_cents: int
    amount_paid_cents: int
    amount_due_cents: int
    status: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    citation_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contest(TypedDict):
    id: str
    citation_id: str
    grounds: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Hearing(TypedDict):
    id: str
    contest_id: str
    room_id: str
    scheduled_start: str
    scheduled_end: str
    adjournment_count: int
    decision: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BootTowOrder(TypedDict):
    id: str
    vehicle_id: str
    order_type: str
    origin: str
    fee_cents: int
    release_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegistrationHold(TypedDict):
    id: str
    vehicle_id: str
    boot_tow_order_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int
