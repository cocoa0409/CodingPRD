"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries the four
system-managed properties id, created_at, updated_at, version (PRD common
resource properties).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    FACILITY_MANAGER = "FacilityManager"
    PARKING_ATTENDANT = "ParkingAttendant"
    REVENUE_AUDITOR = "RevenueAuditor"
    MAINTENANCE_SUPERVISOR = "MaintenanceSupervisor"
    SECURITY_OFFICER = "SecurityOfficer"
    GATE_DEVICE = "GateDevice"
    MONTHLY_PARKER = "MonthlyParker"


class FacilityPosture(str, Enum):
    NORMAL = "NORMAL"
    EVENT_SURGE = "EVENT_SURGE"
    RESTRICTED = "RESTRICTED"
    CLOSED_TEMPORARY = "CLOSED_TEMPORARY"
    DECOMMISSIONED = "DECOMMISSIONED"


class ScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class CapMode(str, Enum):
    CALENDAR_DAY = "CALENDAR_DAY"
    ROLLING_24H = "ROLLING_24H"


class DeviceKind(str, Enum):
    ENTRY_GATE = "ENTRY_GATE"
    EXIT_GATE = "EXIT_GATE"
    PAY_STATION = "PAY_STATION"


class DeviceStatus(str, Enum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    DECOMMISSIONED = "DECOMMISSIONED"


class DeviceMode(str, Enum):
    STANDARD = "STANDARD"
    EVENT = "EVENT"


class AgreementTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    EV = "EV"


class AgreementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    WAITLISTED = "WAITLISTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    WITHDRAWN = "WITHDRAWN"


class CredentialType(str, Enum):
    BADGE = "BADGE"
    TRANSPONDER = "TRANSPONDER"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LOST_REPORTED = "LOST_REPORTED"
    REPLACED = "REPLACED"
    RETURNED = "RETURNED"
    REVOKED = "REVOKED"


class OccupancyState(str, Enum):
    PARKED = "PARKED"
    EXITED = "EXITED"


class BillingState(str, Enum):
    OPEN = "OPEN"
    QUOTED = "QUOTED"
    SETTLED = "SETTLED"
    COMPED = "COMPED"
    REFUNDED = "REFUNDED"


class FeeMode(str, Enum):
    STANDARD = "STANDARD"
    EVENT_FLAT = "EVENT_FLAT"
    LOST_TICKET = "LOST_TICKET"
    MONTHLY = "MONTHLY"


class TenderType(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    NONE = "NONE"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FORCE_CLOSED = "FORCE_CLOSED"
    RECONCILED = "RECONCILED"


class ReconciliationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VARIANCE_REVIEW = "VARIANCE_REVIEW"
    APPROVED = "APPROVED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_FIELD = "IN_FIELD"
    REPORTED = "REPORTED"
    CANCELLED = "CANCELLED"


class ConditionClass(str, Enum):
    SOUND = "SOUND"
    FAIR = "FAIR"
    CRITICAL = "CRITICAL"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    FUNDED = "FUNDED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    DEFERRED = "DEFERRED"
    CLOSED_OUT = "CLOSED_OUT"
    CANCELLED = "CANCELLED"


class WindowType(str, Enum):
    SWEEPING = "SWEEPING"
    DRAIN_FLUSH = "DRAIN_FLUSH"
    LIGHTING_REPAIR = "LIGHTING_REPAIR"
    SEALANT_WORK = "SEALANT_WORK"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class PatrolStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"


class IncidentType(str, Enum):
    SECURITY = "SECURITY"
    VEHICLE_DAMAGE = "VEHICLE_DAMAGE"
    CASH_VARIANCE = "CASH_VARIANCE"
    VANDALISM = "VANDALISM"
    SAFETY = "SAFETY"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ChargerStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PERMITTED = "PERMITTED"
    INSTALLED = "INSTALLED"
    COMMISSIONED = "COMMISSIONED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class ChargingSessionStatus(str, Enum):
    CHARGING = "CHARGING"
    COMPLETED = "COMPLETED"
    FAULTED = "FAULTED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CancellationPolicy(str, Enum):
    FORFEIT_DEPOSIT = "FORFEIT_DEPOSIT"
    SLIDING_NOTICE = "SLIDING_NOTICE"


class Facility(TypedDict, total=False):
    id: str
    name: str
    total_spaces: int
    monthly_capacity: int
    event_pool_spaces: int
    levy_pct: float
    posture: str
    closed_spaces: int
    occupied_spaces: int
    monthly_allocated: int
    capital_reserve_cents: int
    deposit_liability_cents: int
    cumulative_collected_cents: int
    last_close_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict, total=False):
    id: str
    facility_id: str
    label: str
    schedule_status: str
    grace_minutes: int
    first_hour_cents: int
    additional_hour_cents: int
    daily_max_cents: int
    event_flat_cents: int
    lost_ticket_daily_cents: int
    cap_mode: str
    effective_from: str
    supersedes_schedule_id: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessDevice(TypedDict, total=False):
    id: str
    facility_id: str
    device_label: str
    device_kind: str
    device_status: str
    device_mode: str
    last_heartbeat_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParkerAccount(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class MonthlyAgreement(TypedDict, total=False):
    id: str
    facility_id: str
    parker_account_id: str
    tier: str
    monthly_rate_cents: int
    ev_surcharge_cents: int
    agreement_status: str
    application_seq: int
    activated_at: Optional[str]
    first_invoice_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict, total=False):
    id: str
    agreement_id: str
    credential_type: str
    credential_status: str
    deposit_cents: int
    replaced_by_credential_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ParkingSession(TypedDict, total=False):
    id: str
    facility_id: str
    rate_schedule_id: str
    entry_device_id: str
    credential_id: Optional[str]
    paid_in_shift_id: Optional[str]
    ticket_barcode: str
    occupancy_state: str
    billing_state: str
    fee_mode: str
    entry_at: str
    exit_at: Optional[str]
    quoted_fee_cents: Optional[int]
    settled_fee_cents: Optional[int]
    refunded_cents: Optional[int]
    refunded_at: Optional[str]
    tender_type: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendantShift(TypedDict, total=False):
    id: str
    facility_id: str
    attendant_user_id: str
    shift_status: str
    opening_float_cents: int
    counted_cash_cents: Optional[int]
    over_ring_cents: int
    paid_out_cents: int
    expected_cash_cents: Optional[int]
    comp_total_cents: int
    opened_at: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReconciliationRecord(TypedDict, total=False):
    id: str
    shift_id: str
    auditor_user_id: Optional[str]
    reconciliation_status: str
    variance_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StructuralInspection(TypedDict, total=False):
    id: str
    facility_id: str
    level_scope: str
    scheduled_for: str
    inspection_status: str
    load_bearing_rating: Optional[int]
    waterproofing_rating: Optional[int]
    surface_rating: Optional[int]
    closed_space_count: int
    condition_index: Optional[int]
    condition_class: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairProject(TypedDict, total=False):
    id: str
    facility_id: str
    inspection_id: Optional[str]
    title: str
    level_scope: str
    estimated_cost_cents: int
    closed_space_count: int
    project_status: str
    funded_amount_cents: int
    scheduled_start_at: Optional[str]
    scheduled_end_at: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    facility_id: str
    level: str
    window_type: str
    start_at: str
    end_at: str
    safety_authorized: bool
    window_status: str
    created_at: str
    updated_at: str
    version: int


class PatrolRound(TypedDict, total=False):
    id: str
    facility_id: str
    officer_user_id: str
    scheduled_start: str
    patrol_status: str
    checkpoints_completed: Optional[int]
    lighting_outages_found: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    facility_id: str
    patrol_round_id: Optional[str]
    reconciliation_id: Optional[str]
    incident_type: str
    severity: str
    description: str
    incident_status: str
    duplicate_of_incident_id: Optional[str]
    auto_created: bool
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EVCharger(TypedDict, total=False):
    id: str
    facility_id: str
    charger_label: str
    max_kw: int
    charger_status: str
    commissioned_at: Optional[str]
    utilization_session_pct: Optional[float]
    utilization_energy_pct: Optional[float]
    low_util_run_count: int
    utilization_review_flag: bool
    created_at: str
    updated_at: str
    version: int


class ChargingSession(TypedDict, total=False):
    id: str
    charger_id: str
    agreement_id: Optional[str]
    session_status: str
    started_at: str
    ended_at: Optional[str]
    kwh_delivered: Optional[float]
    idle_minutes: int
    created_at: str
    updated_at: str
    version: int


class EventBooking(TypedDict, total=False):
    id: str
    facility_id: str
    event_name: str
    booking_status: str
    start_at: str
    end_at: str
    presale_allocation: int
    min_staff: int
    staffing_assignments: List[str]
    deposit_cents: int
    cancellation_policy: str
    cancellation_fee_cents: Optional[int]
    deposit_refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
