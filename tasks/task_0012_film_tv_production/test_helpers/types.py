"""Domain types for the Film/TV Production API: TypedDicts, status enums, role enum.

PRD §2.4 declares which entities carry the four common system fields (id, created_at,
updated_at, version) and which are append-only (only id + created_at): Audition,
EquipmentEvent, AuditLog, and the Clock singleton.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# --- Roles (PRD §2.1) ---

class UserRole(str, Enum):
    EXECUTIVE_PRODUCER = "ExecutiveProducer"
    LINE_PRODUCER = "LineProducer"
    FINANCE_CONTROLLER = "FinanceController"
    CASTING_DIRECTOR = "CastingDirector"
    PRODUCTION_COORDINATOR = "ProductionCoordinator"


# --- Production enums (PRD §3.1, §2.6) ---

class ProductionStatus(str, Enum):
    PLANNING = "PLANNING"
    IN_PRODUCTION = "IN_PRODUCTION"
    WRAP_PENDING = "WRAP_PENDING"
    WRAPPED = "WRAPPED"
    CANCELLED = "CANCELLED"


class ProductionPosture(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    FROZEN = "FROZEN"


class ProductionType(str, Enum):
    FILM = "FILM"
    TV_SERIES = "TV_SERIES"
    DOCUMENTARY = "DOCUMENTARY"
    COMMERCIAL = "COMMERCIAL"


# --- Scene enums (PRD §3.4) ---

class SceneStatus(str, Enum):
    BREAKDOWN = "BREAKDOWN"
    SCHEDULED = "SCHEDULED"
    RESCHEDULING = "RESCHEDULING"
    SHOT = "SHOT"
    OMITTED = "OMITTED"


class IntExt(str, Enum):
    INT = "INT"
    EXT = "EXT"
    INT_EXT = "INT_EXT"


# --- Role / Casting enums (PRD §3.2) ---

class CastingStatus(str, Enum):
    OPEN = "OPEN"
    AUDITIONING = "AUDITIONING"
    SHORTLISTED = "SHORTLISTED"
    OFFERED = "OFFERED"
    SIGNED = "SIGNED"
    RECAST = "RECAST"


class UnionTier(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    SUPPORTING = "SUPPORTING"
    FEATURED_BACKGROUND = "FEATURED_BACKGROUND"


class AuditionOutcome(str, Enum):
    PASS = "PASS"
    REJECT = "REJECT"
    CALLBACK = "CALLBACK"


# --- Location / Reservation (PRD §3.3) ---

class PermitStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class WeatherStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    ACCEPTABLE = "ACCEPTABLE"
    BLOCKED = "BLOCKED"


class LocationReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RESCHEDULING = "RESCHEDULING"
    RELEASED = "RELEASED"
    FULFILLED = "FULFILLED"


# --- Budget / ChangeOrder (PRD §2.7, §3.7) ---

class BudgetCategoryCode(str, Enum):
    CAST = "CAST"
    CREW = "CREW"
    EQUIPMENT = "EQUIPMENT"
    LOCATION = "LOCATION"
    POST = "POST"
    MISC = "MISC"


class AlertState(str, Enum):
    OK = "OK"
    WARN = "WARN"
    OVER = "OVER"


class ChangeOrderStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ChangeOrderSource(str, Enum):
    REALLOCATION = "REALLOCATION"
    RESERVE_DRAW = "RESERVE_DRAW"


# --- Equipment (PRD §3.5) ---

class EquipmentCategory(str, Enum):
    CAMERA = "CAMERA"
    LIGHTING = "LIGHTING"
    SOUND = "SOUND"
    GRIP = "GRIP"
    WARDROBE = "WARDROBE"
    PROPS = "PROPS"
    MISC = "MISC"


class AcquisitionMode(str, Enum):
    RENTAL = "RENTAL"
    PURCHASE = "PURCHASE"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHECKED_OUT = "CHECKED_OUT"
    DAMAGED = "DAMAGED"
    LOST = "LOST"
    RETURNED = "RETURNED"
    DECOMMISSIONED = "DECOMMISSIONED"


class EquipmentEventType(str, Enum):
    CHECK_OUT = "CHECK_OUT"
    CHECK_IN = "CHECK_IN"
    REPORT_DAMAGE = "REPORT_DAMAGE"
    REPORT_LOSS = "REPORT_LOSS"
    RETURN_VERIFIED = "RETURN_VERIFIED"


# --- Vendor / Crew (PRD §3.6, §3.8) ---

class VendorInvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class CrewAssignmentStatus(str, Enum):
    BOOKED = "BOOKED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    SETTLED = "SETTLED"


# --- Audit (PRD §2.9) ---

class AuditAction(str, Enum):
    SCHEDULE_CHANGE = "SCHEDULE_CHANGE"
    BUDGET_ADJUSTMENT = "BUDGET_ADJUSTMENT"
    RESERVE_DRAW = "RESERVE_DRAW"
    CONTRACT_SIGNED = "CONTRACT_SIGNED"
    EQUIPMENT_LOSS = "EQUIPMENT_LOSS"
    WRAP_CLOSE = "WRAP_CLOSE"


# --- TypedDicts (common_fields=true entities carry id/created_at/updated_at/version) ---

class Production(TypedDict, total=False):
    id: str
    title: str
    production_type: str
    shoot_window_start: str
    shoot_window_end: str
    total_budget_cents: int
    reserve_fund_cents: int
    status: str
    posture: str
    schedule_baseline_locked_at: Optional[str]
    spent_cents: int
    committed_cents: int
    residual_cents: int
    created_at: str
    updated_at: str
    version: int


class Scene(TypedDict, total=False):
    id: str
    production_id: str
    scene_number: str
    int_ext: str
    planned_duration_minutes: int
    required_actor_role_ids: List[str]
    required_equipment_categories: List[str]
    weather_dependent: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Role(TypedDict, total=False):
    id: str
    production_id: str
    role_name: str
    description: str
    union_tier: str
    day_rate_cents: int
    casting_status: str
    signed_actor_id: Optional[str]
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Actor(TypedDict, total=False):
    id: str
    legal_name: str
    agency_contact_email: str
    travel_origin_zone: str
    active: bool
    created_at: str
    updated_at: str
    version: int


# Audition is append-only — only id + created_at + payload fields
class Audition(TypedDict, total=False):
    id: str
    role_id: str
    actor_id: str
    audition_at: str
    outcome: str
    notes: str
    created_at: str


class Location(TypedDict, total=False):
    id: str
    name: str
    zone: str
    requires_permit: bool
    max_parallel_units: int
    created_at: str
    updated_at: str
    version: int


class LocationReservation(TypedDict, total=False):
    id: str
    location_id: str
    production_id: str
    scene_id: str
    unit_label: str
    start_at: str
    end_at: str
    permit_status: str
    weather_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetCategory(TypedDict, total=False):
    id: str
    production_id: str
    code: str
    planned_cents: int
    committed_cents: int
    actual_cents: int
    alert_state: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    production_id: str
    category_id: str
    delta_cents: int
    justification: str
    requested_by: str
    approved_by: Optional[str]
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict, total=False):
    id: str
    name: str
    category: str
    acquisition_mode: str
    vendor_id: str
    unit_cost_cents: int
    status: str
    last_check_event_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# EquipmentEvent is append-only — only id + created_at + payload fields
class EquipmentEvent(TypedDict, total=False):
    id: str
    equipment_id: str
    production_id: str
    event_type: str
    occurred_at: str
    actor_user_id: str
    damage_charge_cents: int
    created_at: str


class CrewAssignment(TypedDict, total=False):
    id: str
    production_id: str
    crew_user_id: str
    role_label: str
    day_rate_cents: int
    scheduled_days: int
    actual_days: int
    payroll_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorInvoice(TypedDict, total=False):
    id: str
    production_id: str
    vendor_id: str
    category_code: str
    gross_cents: int
    deduction_cents: int
    net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# AuditLog is append-only — only id + created_at + payload fields
class AuditLog(TypedDict, total=False):
    id: str
    production_id: str
    actor_user_id: str
    action: str
    subject_entity: str
    subject_id: str
    before_json: Any
    after_json: Any
    occurred_at: str
    created_at: str


# Clock is append-only singleton-ish — only id + created_at + now
class Clock(TypedDict, total=False):
    id: str
    now: str
    created_at: str
