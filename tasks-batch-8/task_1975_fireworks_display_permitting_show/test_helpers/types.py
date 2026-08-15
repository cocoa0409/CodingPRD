"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class OperatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LicenseClass(str, Enum):
    DISPLAY_1_3G = "DISPLAY_1_3G"
    PROXIMATE_1_4G = "PROXIMATE_1_4G"


class CertLevel(str, Enum):
    TRAINEE = "TRAINEE"
    SHOOTER = "SHOOTER"
    LEAD_OPERATOR = "LEAD_OPERATOR"


class DisplayStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    STANDBY_CONFIRMED = "STANDBY_CONFIRMED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    SHOW_COMPLETE = "SHOW_COMPLETE"
    SWEEP_VERIFIED = "SWEEP_VERIFIED"
    CLOSED = "CLOSED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class WeatherDecision(str, Enum):
    PENDING = "PENDING"
    GO = "GO"
    NO_GO = "NO_GO"


class CancellationReason(str, Enum):
    OPERATOR = "OPERATOR"
    WEATHER_NO_GO = "WEATHER_NO_GO"
    OPERATOR_SUSPENDED = "OPERATOR_SUSPENDED"


class TerminationReason(str, Enum):
    COMPLETED = "COMPLETED"
    DUD_HALT = "DUD_HALT"


class SitePlanStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class MagazineType(str, Enum):
    INDOOR = "INDOOR"
    OUTDOOR = "OUTDOOR"


class MagazinePosture(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class BatchStatus(str, Enum):
    IN_MAGAZINE = "IN_MAGAZINE"
    CHECKED_OUT = "CHECKED_OUT"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class MovementType(str, Enum):
    CHECK_OUT = "CHECK_OUT"
    RETURN = "RETURN"
    EXPEND = "EXPEND"


class WeatherSource(str, Enum):
    ON_SITE_ANEMOMETER = "ON_SITE_ANEMOMETER"
    NWS = "NWS"


class PostStatus(str, Enum):
    UNSTAFFED = "UNSTAFFED"
    STAFFED = "STAFFED"
    SECURED = "SECURED"
    RELEASED = "RELEASED"


class DisposalMethod(str, Enum):
    SOAK_CRUSH = "SOAK_CRUSH"
    BURN_PIT = "BURN_PIT"
    RETURN_TO_SUPPLIER = "RETURN_TO_SUPPLIER"


class MisfireStatus(str, Enum):
    LOGGED = "LOGGED"
    DISPOSED = "DISPOSED"


class SweepType(str, Enum):
    NIGHT_SWEEP = "NIGHT_SWEEP"
    DAWN_RECHECK = "DAWN_RECHECK"


class SweepVerdict(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class IncidentType(str, Enum):
    INJURY = "INJURY"
    FIRE = "FIRE"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    DUD_OFFSITE = "DUD_OFFSITE"
    CROWD_BREACH = "CROWD_BREACH"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    FILED = "FILED"
    CLOSED = "CLOSED"


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    OPERATOR = "Operator"
    FIRE_MARSHAL = "FireMarshal"
    CREW_MEMBER = "CrewMember"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Common-field entities carry id + created_at + updated_at + version (PRD §2.4).
# Append-only entities (InventoryMovement, WeatherReading) carry ONLY
# id + created_at — updated_at and version are absent on those two (PRD §2.4).
# ---------------------------------------------------------------------------


class Operator(TypedDict, total=False):
    id: str
    legal_name: str
    atf_license_number: str
    license_class: str
    license_valid_from: str
    license_expires_at: str
    status: str
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    operator_id: str
    full_name: str
    cert_level: str
    cert_expires_at: str
    hazmat_endorsed: bool
    created_at: str
    updated_at: str
    version: int


class DisplayEvent(TypedDict, total=False):
    id: str
    operator_id: str
    venue_id: str
    venue_name: str
    scheduled_start_at: str
    scheduled_end_at: str
    declared_max_shell_diameter_in: float
    status: str
    weather_decision: str
    cancellation_reason: Optional[str]
    termination_reason: Optional[str]
    standby_confirmed_at: Optional[str]
    standby_confirmed_by: Optional[str]
    show_completed_at: Optional[str]
    closed_at: Optional[str]
    dud_count: int
    fired_count: int
    final_fallout_radius_ft: Optional[int]
    final_standby_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SitePlan(TypedDict, total=False):
    id: str
    display_event_id: str
    diagram_ref: str
    launch_area_width_ft: float
    launch_area_length_ft: float
    spectator_boundary_ft: int
    spectator_arc_center_deg: int
    nearest_structure_ft: int
    required_spectator_distance_ft: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict, total=False):
    id: str
    display_event_id: str
    site_plan_id: str
    site_plan_version: int
    standby_engines: int
    planned_hours: int
    provisional_standby_fee_cents: int
    reviewed_by_user_id: Optional[str]
    decision_note: Optional[str]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Magazine(TypedDict, total=False):
    id: str
    operator_id: str
    name: str
    atf_magazine_permit: str
    magazine_type: str
    capacity_new_lbs: float
    current_new_lbs: float
    inspection_due_at: str
    posture: str
    created_at: str
    updated_at: str
    version: int


class ProductBatch(TypedDict, total=False):
    id: str
    magazine_id: str
    product_name: str
    un_number: str
    shell_diameter_in: float
    quantity_units: int
    new_per_unit_lbs: float
    lot_number: str
    quantity_remaining: int
    qty_at_magazine: int
    qty_at_show: int
    qty_expended: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryMovement(TypedDict, total=False):
    # Append-only (PRD §2.4): NO updated_at, NO version.
    id: str
    product_batch_id: str
    display_event_id: str
    movement_type: str
    quantity: int
    driver_name: Optional[str]
    vehicle_placard: Optional[str]
    cdl_hazmat_endorsed: Optional[bool]
    auto_generated: bool
    recorded_by_user_id: str
    created_at: str


class WeatherReading(TypedDict, total=False):
    # Append-only (PRD §2.4): NO updated_at, NO version.
    id: str
    display_event_id: str
    wind_speed_mph: float
    gust_mph: float
    wind_direction_deg: int
    precipitation: bool
    source: str
    recorded_by_user_id: str
    created_at: str


class SecurityPost(TypedDict, total=False):
    id: str
    display_event_id: str
    post_label: str
    arc_degrees: int
    radius_ft: int
    required_guards: int
    assigned_guards: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MisfireRecord(TypedDict, total=False):
    id: str
    display_event_id: str
    product_batch_id: str
    shell_description: str
    location_note: Optional[str]
    logged_by_crew_id: str
    soak_until: str
    disposal_method: Optional[str]
    disposed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SweepRecord(TypedDict, total=False):
    id: str
    display_event_id: str
    sweep_type: str
    area_clear: bool
    notes: Optional[str]
    swept_by_crew_id: str
    verified_by_user_id: Optional[str]
    verdict: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    display_event_id: str
    incident_type: str
    severity: str
    description: str
    reported_by_user_id: str
    reported_by_role: str
    resolution_note: Optional[str]
    closed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
