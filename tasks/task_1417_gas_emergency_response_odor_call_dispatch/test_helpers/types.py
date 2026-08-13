"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    DISPATCHER = "Dispatcher"
    FIELD_TECHNICIAN = "FieldTechnician"
    SUPERVISOR = "Supervisor"
    REGULATOR = "Regulator"


class LocationContext(str, Enum):
    INSIDE_STRUCTURE = "INSIDE_STRUCTURE"
    OUTSIDE_STRUCTURE = "OUTSIDE_STRUCTURE"
    METER_AREA = "METER_AREA"
    PUBLIC_SPACE = "PUBLIC_SPACE"
    UNKNOWN = "UNKNOWN"


class OccupancyType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    MULTI_FAMILY = "MULTI_FAMILY"
    PUBLIC_ASSEMBLY = "PUBLIC_ASSEMBLY"
    SCHOOL = "SCHOOL"
    HOSPITAL = "HOSPITAL"


class CallClassification(str, Enum):
    PRIMARY = "PRIMARY"
    DUPLICATE = "DUPLICATE"
    RECURRENCE = "RECURRENCE"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class IncidentLifecycle(str, Enum):
    NEW = "NEW"
    TRIAGED = "TRIAGED"
    DISPATCHED = "DISPATCHED"
    ON_SCENE = "ON_SCENE"
    MAKE_SAFE_IN_PROGRESS = "MAKE_SAFE_IN_PROGRESS"
    MONITORING = "MONITORING"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    MERGED = "MERGED"


class EntryStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    AWAITING_AUTHORIZATION = "AWAITING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    FORCED = "FORCED"
    REFUSED = "REFUSED"


class BreachClass(str, Enum):
    NONE = "NONE"
    RESPONDED_LATE = "RESPONDED_LATE"
    NO_RESPONSE = "NO_RESPONSE"


class DispatchStatus(str, Enum):
    EN_ROUTE = "EN_ROUTE"
    ON_SCENE = "ON_SCENE"
    CLEARED = "CLEARED"
    PREEMPTED = "PREEMPTED"
    CANCELLED = "CANCELLED"


class PauseReason(str, Enum):
    CUSTOMER_NOT_HOME = "CUSTOMER_NOT_HOME"
    ACCESS_BLOCKED = "ACCESS_BLOCKED"


class PauseStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReadingContext(str, Enum):
    INSIDE = "INSIDE"
    OUTSIDE = "OUTSIDE"
    CONFINED_SPACE = "CONFINED_SPACE"


class MakeSafeActionType(str, Enum):
    VENTILATE = "VENTILATE"
    SHUT_APPLIANCE_VALVE = "SHUT_APPLIANCE_VALVE"
    EVACUATE = "EVACUATE"
    SECURE_AREA = "SECURE_AREA"
    OTHER = "OTHER"


class EntryMethod(str, Enum):
    CUSTOMER_CONSENT = "CUSTOMER_CONSENT"
    EMERGENCY_FORCED = "EMERGENCY_FORCED"
    WARRANT = "WARRANT"


class ShutoffScope(str, Enum):
    METER = "METER"
    APPLIANCE = "APPLIANCE"
    SERVICE_LINE = "SERVICE_LINE"


class ShutoffStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    DECLINED = "DECLINED"
    EXECUTED = "EXECUTED"
    RESTORED = "RESTORED"


class Responsibility(str, Enum):
    INSIDE_CUSTOMER = "INSIDE_CUSTOMER"
    OUTSIDE_COMPANY = "OUTSIDE_COMPANY"
    SHARED = "SHARED"


class DeterminationBasis(str, Enum):
    METER_LOCATION = "METER_LOCATION"
    BARHOLE_SURVEY = "BARHOLE_SURVEY"
    CUSTOMER_APPLIANCE_TRACE = "CUSTOMER_APPLIANCE_TRACE"
    EXCAVATION = "EXCAVATION"


class DeterminationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class WorkOrderOrigin(str, Enum):
    AUTO_DETERMINATION = "AUTO_DETERMINATION"
    MANUAL = "MANUAL"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class NotificationChannel(str, Enum):
    MEDIA = "MEDIA"
    PUBLIC_ALERT = "PUBLIC_ALERT"
    AGENCY_NOTICE = "AGENCY_NOTICE"


class NotificationOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_PRIORITY = "AUTO_PRIORITY"
    AUTO_SEVERITY = "AUTO_SEVERITY"


class NotificationStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    RETRACTED = "RETRACTED"
    DISCARDED = "DISCARDED"


# --- Entity TypedDicts ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).
# Immutable records (shift, call, reading, action, entry authorization) carry
# id + created_at only (PRD §2.5).


class ServiceTerritory(TypedDict, total=False):
    id: str
    name: str
    p1_threshold_minutes: int
    p2_threshold_minutes: int
    p3_threshold_minutes: int
    p4_threshold_minutes: int
    recurrence_window_hours: int
    repair_budget_cap_cents: int
    repair_reserved_cents: int
    created_at: str
    updated_at: str
    version: int


class FieldTechnician(TypedDict, total=False):
    id: str
    full_name: str
    badge_number: str
    home_territory_id: str
    hourly_rate_cents: int
    is_active: bool
    on_shift: bool
    active_assignment_count: int
    weighted_load: int
    last_cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TechnicianShift(TypedDict, total=False):
    id: str
    technician_id: str
    shift_start: str
    shift_end: str
    created_at: str


class RepairCrew(TypedDict, total=False):
    id: str
    crew_code: str
    territory_id: str
    hourly_rate_cents: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class EmergencyCall(TypedDict, total=False):
    id: str
    caller_name: str
    caller_phone: str
    address_line: str
    city: str
    territory_id: str
    location_context: str
    occupancy_type: str
    odor_reported: bool
    symptoms_reported: bool
    hissing_reported: bool
    implied_priority: str
    classification: str
    is_duplicate: bool
    incident_id: str
    received_at: str
    created_at: str


class GasIncident(TypedDict, total=False):
    id: str
    territory_id: str
    normalized_address: str
    occupancy_type: str
    lifecycle_status: str
    entry_status: str
    priority: str
    severity_score: int
    linked_call_count: int
    reopen_count: int
    response_clock_started_at: str
    first_arrival_at: Optional[str]
    prior_segment_adjusted_seconds: int
    pause_total_seconds: int
    raw_elapsed_seconds: int
    adjusted_elapsed_seconds: int
    threshold_minutes: int
    breach_class: str
    awaiting_dispatch: bool
    evacuation_required: bool
    make_safe_completed: bool
    leak_confirmed: bool
    gas_flow_stopped: bool
    responsibility: Optional[str]
    customer_referral_required: bool
    auto_notification_created: bool
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispatchAssignment(TypedDict, total=False):
    id: str
    incident_id: str
    technician_id: str
    status: str
    sla_threshold_minutes: int
    dispatched_at: str
    arrived_at: Optional[str]
    cleared_at: Optional[str]
    preempt_reason: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResponseClockPause(TypedDict, total=False):
    id: str
    incident_id: str
    reason: str
    started_at: str
    ended_at: Optional[str]
    status: str
    duration_seconds: int
    created_at: str
    updated_at: str
    version: int


class AtmosphericReading(TypedDict, total=False):
    id: str
    incident_id: str
    technician_id: str
    pct_lel: float
    co_ppm: float
    reading_context: str
    taken_at: str
    created_at: str


class MakeSafeAction(TypedDict, total=False):
    id: str
    incident_id: str
    technician_id: str
    action_type: str
    notes: Optional[str]
    performed_at: str
    created_at: str


class PremiseEntryAuthorization(TypedDict, total=False):
    id: str
    incident_id: str
    method: str
    authorized_by_name: str
    recorded_by_user_id: str
    created_at: str


class ShutoffOrder(TypedDict, total=False):
    id: str
    incident_id: str
    scope: str
    entry_required: bool
    reason: str
    status: str
    requested_by_user_id: str
    authorized_by_user_id: Optional[str]
    executed_by_technician_id: Optional[str]
    executed_at: Optional[str]
    restored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResponsibilityDetermination(TypedDict, total=False):
    id: str
    incident_id: str
    responsibility: str
    basis: str
    notes: Optional[str]
    status: str
    drafted_by_user_id: str
    finalized_by_user_id: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrderLine(TypedDict, total=False):
    description: str
    quantity: float
    unit_price_cents: int
    discount_pct: float


class RepairWorkOrder(TypedDict, total=False):
    id: str
    incident_id: str
    origin: str
    status: str
    crew_id: Optional[str]
    provisional_estimate_cents: int
    current_estimate_cents: int
    scheduled_window_start: Optional[str]
    scheduled_window_end: Optional[str]
    lines: Optional[List[WorkOrderLine]]
    labor_minutes: Optional[int]
    labor_billed_minutes: Optional[int]
    final_cost_cents: Optional[int]
    completed_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegulatoryReport(TypedDict, total=False):
    id: str
    territory_id: str
    period_start: str
    period_end: str
    status: str
    generated_at: str
    submitted_at: Optional[str]
    incident_count: int
    determined_count: int
    pending_count: int
    compliant_count_raw: int
    compliant_count_adjusted: int
    compliance_rate_raw: Optional[float]
    compliance_rate_adjusted: Optional[float]
    needs_regeneration: bool
    regeneration_count: int
    reject_reason: Optional[str]
    stats: dict
    created_at: str
    updated_at: str
    version: int


class PublicNotification(TypedDict, total=False):
    id: str
    incident_id: str
    channel: str
    headline: str
    body: str
    origin: str
    status: str
    issued_at: Optional[str]
    retracted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
