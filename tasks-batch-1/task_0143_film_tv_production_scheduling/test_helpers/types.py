"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Film/TV Production Scheduling PRD entity model. Monetary fields are
whole integer cents throughout. ResidualEvent is the one immutable record that
carries only ``id`` + ``created_at`` (no ``updated_at``/``version``).
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class ProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    PRE_PRODUCTION = "PRE_PRODUCTION"
    ACTIVE = "ACTIVE"
    WRAPPED = "WRAPPED"
    CLOSED = "CLOSED"


class ShootingDayStatus(str, Enum):
    PLANNED = "PLANNED"
    CALLED = "CALLED"
    IN_PROGRESS = "IN_PROGRESS"
    WRAPPED = "WRAPPED"
    CANCELLED = "CANCELLED"


class AttendanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    WRAPPED = "WRAPPED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOID = "VOID"


class CallSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    REVISED = "REVISED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class LocationPermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class DailiesStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    FLAGGED = "FLAGGED"
    ARCHIVED = "ARCHIVED"


# --------------------------------------------------------------------------- #
# Domain value enums
# --------------------------------------------------------------------------- #
class ProductionType(str, Enum):
    FEATURE = "FEATURE"
    EPISODIC = "EPISODIC"


class BudgetCategory(str, Enum):
    ABOVE_THE_LINE = "ABOVE_THE_LINE"
    BELOW_THE_LINE_LABOR = "BELOW_THE_LINE_LABOR"
    LOCATIONS = "LOCATIONS"
    POST = "POST"
    FRINGES = "FRINGES"


class ShootingUnit(str, Enum):
    MAIN = "MAIN"
    SECOND = "SECOND"
    SPLINTER = "SPLINTER"


class IntExt(str, Enum):
    INT = "INT"
    EXT = "EXT"


class DayNight(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"


class UnionCode(str, Enum):
    SAG_AFTRA = "SAG_AFTRA"
    IATSE = "IATSE"
    DGA = "DGA"
    NONE = "NONE"


class ResidualMarket(str, Enum):
    THEATRICAL = "THEATRICAL"
    SVOD = "SVOD"
    BASIC_CABLE = "BASIC_CABLE"
    NETWORK = "NETWORK"
    HOME_VIDEO = "HOME_VIDEO"


class UserRole(str, Enum):
    LINE_PRODUCER = "LineProducer"
    FIRST_AD = "FirstAD"
    PAYROLL_COORDINATOR = "PayrollCoordinator"
    POST_SUPERVISOR = "PostSupervisor"
    UNION_REP = "UnionRep"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (common_fields: true → id/created_at/updated_at/version)
# --------------------------------------------------------------------------- #
class Production(TypedDict):
    id: str
    title: str
    production_type: str
    status: str
    total_budget_cents: int
    committed_cost_cents: int
    actual_cost_cents: int
    residual_reserve_cents: int
    created_at: str
    updated_at: str
    version: int


class BudgetLine(TypedDict):
    id: str
    production_id: str
    category: str
    estimated_cents: int
    actual_cents: int
    variance_cents: int
    created_at: str
    updated_at: str
    version: int


class ShootingDay(TypedDict):
    id: str
    production_id: str
    shoot_date: str
    day_number: int
    unit: str
    status: str
    estimated_page_eighths: int
    created_at: str
    updated_at: str
    version: int


class Scene(TypedDict):
    id: str
    production_id: str
    shooting_day_id: Optional[str]
    scene_number: str
    page_eighths: int
    int_ext: str
    day_night: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    production_id: str
    full_name: str
    role_title: str
    is_sag_aftra: bool
    daily_rate_cents: int
    union_code: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    shooting_day_id: str
    crew_member_id: str
    call_time: str
    wrap_time: Optional[str]
    meal_breaks_taken: int
    hours_worked: float
    attendance_status: str
    payment_status: str
    estimated_cost_cents: int
    meal_penalty_cents: int
    turnaround_penalty_cents: int
    fringe_cents: int
    paid_cost_cents: int
    prior_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CallSheet(TypedDict):
    id: str
    shooting_day_id: str
    status: str
    revision_number: int
    general_call_time: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    production_id: str
    name: str
    address: str
    created_at: str
    updated_at: str
    version: int


class LocationPermit(TypedDict):
    id: str
    location_id: str
    permit_number: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UnionFringe(TypedDict):
    id: str
    production_id: str
    union_code: str
    fringe_rate_bps: int
    pension_health_flat_cents: int
    created_at: str
    updated_at: str
    version: int


class Dailies(TypedDict):
    id: str
    shooting_day_id: str
    reel_label: str
    status: str
    flagged_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable accounting fact: id + created_at only.
class ResidualEvent(TypedDict):
    id: str
    production_id: str
    market: str
    gross_receipts_cents: int
    event_date: str
    residual_amount_cents: int
    created_at: str
