"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the full common-field set
(id, created_at, updated_at, version) per the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---------------------------------------------------------------
class UserRole(str, Enum):
    PLAN_ADMIN = "PlanAdmin"
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    HOMEOWNER = "Homeowner"


# --- Status enums ------------------------------------------------------------
class PricingConfigStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class HvacSystemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class RoutePlanStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    INSPECTED = "INSPECTED"
    QUOTED = "QUOTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InspectionPhase(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"


class ReminderStatus(str, Enum):
    WAITING = "WAITING"
    DUE = "DUE"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class PlanLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class UpsellReferralStatus(str, Enum):
    PENDING = "PENDING"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class CallbackTicketStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version) ----------
class PricingConfig(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    duct_base_cents: int
    duct_per_system_cents: int
    dryer_vent_flat_cents: int
    sanitize_per_system_cents: int
    addon_sanitizer_cents: int
    addon_uv_cents: int
    addon_coil_cents: int
    multi_system_discount_pct: float
    plan_member_discount_pct: float
    tax_pct: float
    status: str


class Homeowner(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    email: str
    phone: str


class Home(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    homeowner_id: str
    address_line: str
    zone_code: str
    square_footage: int
    active_system_count: int
    has_active_plan: bool


class HvacSystem(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    home_id: str
    label: str
    register_count: int
    status: str


class CrewMember(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    full_name: str
    home_zone_code: str
    certified_for_uv: bool


class RoutePlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    crew_member_id: str
    zone_code: str
    service_date: str
    shift_start_minute: int
    shift_end_minute: int
    committed_minutes: int
    status: str


class WorkOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    home_id: str
    route_plan_id: Optional[str]
    crew_member_id: Optional[str]
    service_lines: List[dict]
    addons: List[str]
    requested_start_minute: int
    scheduled_start_minute: Optional[int]
    duration_minutes: Optional[int]
    estimate_total_cents: Optional[int]
    invoice_total_cents: Optional[int]
    pricing_config_id: Optional[str]
    status: str


class Inspection(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    work_order_id: str
    before_photo_count: int
    after_photo_count: int
    dust_severity: int
    recommend_hvac_repair: bool
    phase: str


class RecurringPlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    home_id: str
    cadence_months: int
    enrolled_at: str
    next_reminder_at: str
    reminder_status: str
    lifecycle_status: str


class UpsellReferral(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    work_order_id: str
    home_id: str
    severity_at_referral: int
    status: str


class CallbackTicket(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    work_order_id: str
    reopened_from_ticket_id: Optional[str]
    reason: str
    redo_required: bool
    status: str
