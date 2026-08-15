"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-4)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD section 2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    SUPERINTENDENT = "Superintendent"
    PROJECT_MANAGER = "ProjectManager"
    SAFETY_OFFICER = "SafetyOfficer"
    CONTRACTOR_REP = "ContractorRep"
    OWNER_REP = "OwnerRep"


# ---------------------------------------------------------------------------
# Status / vocabulary enums
# ---------------------------------------------------------------------------

class ProjectStatus(str, Enum):
    MOBILIZING = "MOBILIZING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class WorkAreaStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DeliveryZoneStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class WorkItemStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class Unit(str, Enum):
    LF = "LF"
    SF = "SF"
    CY = "CY"
    EA = "EA"
    TON = "TON"
    GAL = "GAL"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    LOCKED = "LOCKED"


class ContentPosture(str, Enum):
    EDITABLE = "EDITABLE"
    SEALED = "SEALED"


class RetentionClass(str, Enum):
    STANDARD = "STANDARD"
    CLAIMS_HOLD = "CLAIMS_HOLD"


class EntryStatus(str, Enum):
    """CrewEntry / EquipmentEntry / QuantityEntry lifecycle."""
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class WeatherCondition(str, Enum):
    CLEAR = "CLEAR"
    CLOUDY = "CLOUDY"
    RAIN = "RAIN"
    SNOW = "SNOW"
    WIND = "WIND"
    EXTREME_HEAT = "EXTREME_HEAT"
    EXTREME_COLD = "EXTREME_COLD"


class WorkImpact(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    STOPPAGE = "STOPPAGE"


class DelayCause(str, Enum):
    WEATHER = "WEATHER"
    OWNER = "OWNER"
    MATERIAL = "MATERIAL"
    LABOR = "LABOR"
    EQUIPMENT = "EQUIPMENT"
    OTHER = "OTHER"


class DelayClassification(str, Enum):
    EXCUSABLE_COMPENSABLE = "EXCUSABLE_COMPENSABLE"
    EXCUSABLE_NON_COMPENSABLE = "EXCUSABLE_NON_COMPENSABLE"
    NON_EXCUSABLE = "NON_EXCUSABLE"
    CONCURRENT = "CONCURRENT"


class DelayStatus(str, Enum):
    RECORDED = "RECORDED"
    CLASSIFIED = "CLASSIFIED"
    DISPUTED = "DISPUTED"
    FINAL = "FINAL"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ObservationStatus(str, Enum):
    OPEN = "OPEN"
    MITIGATED = "MITIGATED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    ESCALATED = "ESCALATED"


class IncidentSeverity(str, Enum):
    FIRST_AID = "FIRST_AID"
    NEAR_MISS = "NEAR_MISS"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    MEDICAL_TREATMENT = "MEDICAL_TREATMENT"
    LOST_TIME = "LOST_TIME"
    FATALITY = "FATALITY"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    OSHA_NOTIFIED = "OSHA_NOTIFIED"
    CLOSED_RECORDABLE = "CLOSED_RECORDABLE"
    CLOSED_NOT_RECORDABLE = "CLOSED_NOT_RECORDABLE"


class MediaType(str, Enum):
    PHOTO = "PHOTO"
    VIDEO = "VIDEO"


class MediaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PURGED = "PURGED"


class DeliveryStatus(str, Enum):
    DELIVERED = "DELIVERED"
    PARTIAL = "PARTIAL"
    INSPECTED = "INSPECTED"


class TicketStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURES = "PENDING_SIGNATURES"
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED"
    FULLY_SIGNED = "FULLY_SIGNED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOID = "VOID"


class SignerRole(str, Enum):
    CONTRACTOR = "CONTRACTOR"
    OWNER = "OWNER"


class RecipientRole(str, Enum):
    OWNER = "OWNER"
    ARCHITECT = "ARCHITECT"
    INSPECTOR = "INSPECTOR"
    SUBCONTRACTOR = "SUBCONTRACTOR"
    INTERNAL = "INTERNAL"


class DistributionStatus(str, Enum):
    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD section 2.4: id/created_at/updated_at/version;
# WeatherObservation is append-only and carries id + created_at only)
# ---------------------------------------------------------------------------

class Project(TypedDict, total=False):
    id: str
    name: str
    contract_number: str
    scheduled_shift_start: str
    scheduled_shift_hours: float
    retention_days: int
    status: str
    percent_complete_units: float
    percent_complete_cost: float
    created_at: str
    updated_at: str
    version: int


class WorkArea(TypedDict, total=False):
    id: str
    project_id: str
    code: str
    description: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryZone(TypedDict, total=False):
    id: str
    project_id: str
    zone_code: str
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkItem(TypedDict, total=False):
    id: str
    project_id: str
    cost_code: str
    description: str
    budgeted_quantity: float
    unit: str
    unit_cost_cents: int
    installed_to_date: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyReport(TypedDict, total=False):
    id: str
    project_id: str
    report_date: str
    general_notes: Optional[str]
    shift_start_actual: Optional[str]
    shift_end_actual: Optional[str]
    no_work_performed: bool
    status: str
    content_posture: str
    submitted_by_user_id: Optional[str]
    submitted_at: Optional[str]
    revision_count: int
    has_open_incident: bool
    distribution_hold: bool
    retention_class: str
    retention_release_date: Optional[str]
    total_workers: int
    manhours_regular: float
    manhours_ot: float
    manhours_dt: float
    weather_lost_hours: float
    weather_lost_day_calendar: bool
    weather_lost_day_fraction: float
    created_at: str
    updated_at: str
    version: int


class CrewEntry(TypedDict, total=False):
    id: str
    report_id: str
    work_area_id: str
    subcontractor: str
    trade: str
    worker_count: int
    hours_per_worker: float
    work_performed: str
    regular_hours: float
    ot_hours: float
    dt_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentEntry(TypedDict, total=False):
    id: str
    report_id: str
    work_area_id: str
    equipment_type: str
    unit_count: int
    hours_used: float
    hours_idle: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherObservation(TypedDict, total=False):
    """Append-only log row: id + created_at only (no updated_at, no version)."""
    id: str
    report_id: str
    observed_at: str
    condition: str
    temperature_f: Optional[float]
    precipitation_in: Optional[float]
    wind_mph: Optional[float]
    work_impact: str
    created_at: str


class DelayEvent(TypedDict, total=False):
    id: str
    report_id: str
    work_area_id: str
    start_at: str
    end_at: str
    cause: str
    classification: Optional[str]
    lost_hours: Optional[float]
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyObservation(TypedDict, total=False):
    id: str
    report_id: str
    work_area_id: str
    description: str
    risk_level: str
    corrective_action: Optional[str]
    due_date: Optional[str]
    media_attachment_id: Optional[str]
    status: str
    created_by_user_id: str
    incident_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    report_id: str
    work_area_id: str
    safety_observation_id: Optional[str]
    occurred_at: str
    severity: str
    injured_count: int
    days_away: int
    narrative: str
    recordable: bool
    osha_notification_deadline: Optional[str]
    osha_notified_at: Optional[str]
    notification_overdue: bool
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class MediaAttachment(TypedDict, total=False):
    id: str
    report_id: str
    work_area_id: str
    media_type: str
    file_url: str
    captured_at: str
    gps_lat: Optional[float]
    gps_lng: Optional[float]
    linked_incident_id: Optional[str]
    linked_delivery_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaterialDelivery(TypedDict, total=False):
    id: str
    report_id: str
    delivery_zone_id: str
    po_number: str
    material_description: str
    delivered_qty: float
    unit: str
    scheduled_window_start: str
    scheduled_window_end: str
    accepted_qty: float
    rejected_qty: float
    pending_recount_qty: float
    inspection_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TmTicket(TypedDict, total=False):
    id: str
    report_id: str
    work_item_id: str
    description: str
    authorized_ceiling_cents: Optional[int]
    labor_lines: list
    equipment_lines: list
    material_lines: list
    labor_cost_cents: int
    equipment_cost_cents: int
    materials_subtotal_cents: int
    materials_markup_cents: int
    materials_cost_cents: int
    total_cents: int
    status: str
    created_by_user_id: str
    contractor_signed_by: Optional[str]
    owner_signed_by: Optional[str]
    revision_count: int
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuantityEntry(TypedDict, total=False):
    id: str
    report_id: str
    work_item_id: str
    work_area_id: str
    quantity_installed: float
    rounded_quantity: float
    supersedes_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionRecord(TypedDict, total=False):
    id: str
    report_id: str
    recipient_email: str
    recipient_role: str
    status: str
    sent_at: Optional[str]
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgressSummary(TypedDict, total=False):
    project_id: str
    units_based_pct: float
    cost_weighted_pct: float
    work_item_count: int
