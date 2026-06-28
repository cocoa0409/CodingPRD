"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system are mutable, so every entity carries
id + created_at + updated_at + version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    CLINIC_ADMIN = "ClinicAdmin"
    INTAKE_NURSE = "IntakeNurse"
    MEDICAL_DIRECTOR = "MedicalDirector"
    NURSE = "Nurse"


# --- Status enums (PRD §2.10) ---
class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCREEN_PENDING = "SCREEN_PENDING"
    REQUIRES_MD_REVIEW = "REQUIRES_MD_REVIEW"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class StandingOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DispatchRouteStatus(str, Enum):
    PLANNING = "PLANNING"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class AdverseEventStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED = "RESOLVED"


class IntakeScreeningStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


class ScreeningOutcome(str, Enum):
    CLEARED = "CLEARED"
    REQUIRES_MD_REVIEW = "REQUIRES_MD_REVIEW"
    BLOCKED = "BLOCKED"


class ConsentStatus(str, Enum):
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class SupplyLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    QUARANTINED = "QUARANTINED"


class MenuTier(str, Enum):
    MYERS = "MYERS"
    NAD = "NAD"
    IMMUNITY = "IMMUNITY"


class MembershipTier(str, Enum):
    NONE = "NONE"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class AddOnCode(str, Enum):
    GLUTATHIONE = "GLUTATHIONE"
    B12 = "B12"
    ZOFRAN = "ZOFRAN"
    TORADOL = "TORADOL"
    VITC_HIGH = "VITC_HIGH"


class LocationType(str, Enum):
    LOUNGE = "LOUNGE"
    MOBILE = "MOBILE"


class ItemKind(str, Enum):
    DRIP_BASE = "DRIP_BASE"
    ADDON = "ADDON"


class Severity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


# --- Entity TypedDicts (all carry common fields per PRD §2.4) ---
class InfusionMenuItem(TypedDict):
    id: str
    name: str
    tier: str
    base_price_cents: int
    requires_standing_order: bool
    g6pd_sensitive: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    name: str
    code: str
    price_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    membership_id: Optional[str]
    open_adverse_event_count: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    tier: str
    covered_drip_tier: str
    drip_credits_total: int
    drip_credits_remaining: int
    addon_credits_total: int
    addon_credits_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StandingOrder(TypedDict):
    id: str
    medical_director_user_id: str
    covered_tier: str
    effective_from: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Nurse(TypedDict):
    id: str
    full_name: str
    license_number: str
    home_lounge_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lounge(TypedDict):
    id: str
    name: str
    bay_count: int
    open_minute_of_day: int
    close_minute_of_day: int
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    patient_id: str
    menu_item_id: str
    addon_ids: List[str]
    location_type: str
    lounge_id: Optional[str]
    route_id: Optional[str]
    nurse_id: Optional[str]
    standing_order_id: Optional[str]
    start_at: str
    duration_minutes: int
    membership_id: Optional[str]
    status: str
    amount_charged_cents: Optional[int]
    drip_credit_used: int
    addon_credits_used: int
    created_at: str
    updated_at: str
    version: int


class IntakeScreening(TypedDict):
    id: str
    appointment_id: str
    author_user_id: str
    pregnancy: bool
    renal_impairment: bool
    cardiac_history: bool
    g6pd_deficiency: bool
    recent_adverse_event: bool
    contraindication_score: int
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Consent(TypedDict):
    id: str
    appointment_id: str
    signed_by_patient: bool
    witness_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyLot(TypedDict):
    id: str
    item_kind: str
    tier_or_code: str
    lot_number: str
    units_total: int
    units_reserved: int
    units_consumed: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DispatchRoute(TypedDict):
    id: str
    nurse_id: str
    service_date: str
    turnaround_minutes: int
    stop_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict):
    id: str
    appointment_id: str
    reported_by_user_id: str
    severity: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int
