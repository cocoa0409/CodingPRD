"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    EOC_MANAGER = "EOCManager"
    SITE_LEAD = "SiteLead"
    INTAKE_STAFF = "IntakeStaff"
    OUTREACH_WORKER = "OutreachWorker"
    MEDICAL_RESPONDER = "MedicalResponder"
    TRANSPORT_COORDINATOR = "TransportCoordinator"


class EpisodeMode(str, Enum):
    WARMING = "WARMING"
    COOLING = "COOLING"


class EpisodeStatus(str, Enum):
    STANDBY = "STANDBY"
    ACTIVATING = "ACTIVATING"
    ACTIVE = "ACTIVE"
    DEACTIVATING = "DEACTIVATING"
    DEACTIVATED = "DEACTIVATED"
    CLOSED = "CLOSED"


class SiteActivationStatus(str, Enum):
    OPENING = "OPENING"
    OPEN = "OPEN"
    DRAINING = "DRAINING"
    CLOSED = "CLOSED"


class GuestStayStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class TransportDispatchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class ShiftStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ShiftRole(str, Enum):
    INTAKE = "INTAKE"
    MEDICAL = "MEDICAL"
    OUTREACH = "OUTREACH"
    SITE_LEAD = "SITE_LEAD"
    GENERAL = "GENERAL"


class StaffSkill(str, Enum):
    INTAKE = "INTAKE"
    MEDICAL = "MEDICAL"
    OUTREACH = "OUTREACH"
    SITE_LEAD = "SITE_LEAD"
    DRIVER = "DRIVER"


class DonationCategory(str, Enum):
    MEAL = "MEAL"
    WATER = "WATER"
    BEDDING = "BEDDING"
    HYGIENE = "HYGIENE"
    PET_SUPPLIES = "PET_SUPPLIES"


class DonationStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"


class MealPeriod(str, Enum):
    BREAKFAST = "BREAKFAST"
    LUNCH = "LUNCH"
    DINNER = "DINNER"


class MealServiceStatus(str, Enum):
    PLANNED = "PLANNED"
    SERVED = "SERVED"


class IncidentKind(str, Enum):
    MEDICAL = "MEDICAL"
    BEHAVIORAL = "BEHAVIORAL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class AfterActionReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class WeatherReadingSource(str, Enum):
    NWS = "NWS"
    MANUAL = "MANUAL"


# ---------------------------------------------------------------------------
# Entity bodies (TypedDicts are documentation; total=False keeps them lenient)
# ---------------------------------------------------------------------------

class Episode(TypedDict, total=False):
    id: str
    mode: str
    threshold_f: float
    sustained_hours_required: int
    scheduled_end_at: str
    status: str
    trigger_met: bool
    breach_run_minutes: int
    activated_at: Optional[str]
    activated_by_user_id: Optional[str]
    deactivated_at: Optional[str]
    extension_count: int
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


# Append-only event log (PRD §2.5): carries ONLY id + created_at as common
# fields — no updated_at, no version.
class WeatherReading(TypedDict, total=False):
    id: str
    episode_id: str
    observed_at: str
    temp_f: float
    heat_index_f: float
    source: str
    created_at: str


class Site(TypedDict, total=False):
    id: str
    name: str
    address: str
    bed_capacity: int
    pet_capacity: int
    locker_capacity: int
    created_at: str
    updated_at: str
    version: int


class SiteActivation(TypedDict, total=False):
    id: str
    episode_id: str
    site_id: str
    capacity_override: Optional[int]
    status: str
    beds_effective: Optional[int]
    occupied_beds: int
    reserved_beds: int
    beds_free: Optional[int]
    pet_slots_free: int
    lockers_free: int
    overnight_coverage_gap_minutes: int
    lead_coverage_ok: bool
    meal_stock_on_hand: int
    meal_stock_projected: int
    opened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    skills: List[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    site_activation_id: str
    staff_member_id: str
    role_on_shift: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict, total=False):
    id: str
    alias: str
    has_pets: bool
    pet_count: int
    bag_count: int
    medical_flag: bool
    medical_hold_active: bool
    created_at: str
    updated_at: str
    version: int


class GuestStay(TypedDict, total=False):
    id: str
    site_activation_id: str
    guest_id: str
    transport_dispatch_id: Optional[str]
    status: str
    pet_slots_used: int
    lockers_used: int
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    bed_nights_provisional: Optional[int]
    bed_nights_final: Optional[int]
    transfer_sequence: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    label: str
    seats: int
    turnaround_minutes: int
    created_at: str
    updated_at: str
    version: int


class TransportDispatch(TypedDict, total=False):
    id: str
    site_activation_id: str
    vehicle_id: Optional[str]
    requested_by_user_id: str
    guest_ids: List[str]
    pickup_window_start: str
    pickup_window_end: str
    has_pets: bool
    status: str
    reserved_bed_count: int
    arrived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict, total=False):
    id: str
    site_activation_id: str
    partner_name: str
    category: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MealService(TypedDict, total=False):
    id: str
    site_activation_id: str
    service_date: str
    meal_period: str
    planned_meals: int
    served_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    site_activation_id: str
    guest_id: Optional[str]
    kind: str
    severity: int
    reporter_user_id: str
    status: str
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AfterActionReport(TypedDict, total=False):
    id: str
    episode_id: str
    status: str
    total_unique_guests: int
    total_bed_nights: int
    meals_served: int
    incidents_by_severity: dict
    transports_arrived: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
