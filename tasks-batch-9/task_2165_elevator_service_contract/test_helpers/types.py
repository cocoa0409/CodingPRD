"""Domain types for the Elevator Service Contract API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    BUILDING_MANAGER = "BuildingManager"
    SERVICE_CONTRACTOR = "ServiceContractor"
    STATE_INSPECTOR = "StateInspector"
    FIRE_DISPATCHER = "FireDispatcher"


# ─── Enumerations ────────────────────────────────────────────────────────────

class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SERVICE_ALERT = "SERVICE_ALERT"
    UNDER_RENEGOTIATION = "UNDER_RENEGOTIATION"
    TERMINATED = "TERMINATED"


class ScopeType(str, Enum):
    FULL_MAINTENANCE = "FULL_MAINTENANCE"
    OIL_AND_GREASE = "OIL_AND_GREASE"


class PenaltySchedule(str, Enum):
    SCHEDULE_A = "SCHEDULE_A"
    SCHEDULE_B = "SCHEDULE_B"


class AvailabilityState(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    UNDER_MODERNIZATION = "UNDER_MODERNIZATION"
    DECOMMISSIONED = "DECOMMISSIONED"


class ComplianceState(str, Enum):
    CERTIFIED = "CERTIFIED"
    INSPECTION_DUE = "INSPECTION_DUE"
    RED_TAGGED = "RED_TAGGED"
    CERTIFICATE_EXPIRED = "CERTIFICATE_EXPIRED"


class CarType(str, Enum):
    TRACTION = "TRACTION"
    HYDRAULIC = "HYDRAULIC"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PERFORMED = "PERFORMED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    REJECTED = "REJECTED"
    MISSED = "MISSED"


class CallbackType(str, Enum):
    ENTRAPMENT = "ENTRAPMENT"
    MALFUNCTION = "MALFUNCTION"
    NUISANCE = "NUISANCE"


class CallbackStatus(str, Enum):
    REPORTED = "REPORTED"
    ESCALATED = "ESCALATED"
    ON_SITE = "ON_SITE"
    CLEARED = "CLEARED"
    CANCELLED = "CANCELLED"


class InspectionType(str, Enum):
    PERIODIC = "PERIODIC"
    FIVE_YEAR_FULL_LOAD = "FIVE_YEAR_FULL_LOAD"
    REINSPECTION = "REINSPECTION"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    PASS_WITH_DEFICIENCIES = "PASS_WITH_DEFICIENCIES"
    FAIL = "FAIL"


class CertificateState(str, Enum):
    NONE = "NONE"
    ISSUED = "ISSUED"
    POSTED = "POSTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ProjectStatus(str, Enum):
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    AT_RISK = "AT_RISK"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class WindowType(str, Enum):
    MODERNIZATION = "MODERNIZATION"
    INSPECTION = "INSPECTION"
    REPAIR = "REPAIR"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    RESCHEDULE_REQUIRED = "RESCHEDULE_REQUIRED"


class PartClass(str, Enum):
    LUBRICATION = "LUBRICATION"
    WEAR_ITEM = "WEAR_ITEM"
    COMPONENT = "COMPONENT"
    CONTROLLER_BOARD = "CONTROLLER_BOARD"


class PartLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    OBSOLETE = "OBSOLETE"
    DISCONTINUED = "DISCONTINUED"


class PartOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    SUBSTITUTED = "SUBSTITUTED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class PenaltyStatus(str, Enum):
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"
    CREDITED = "CREDITED"
    SUPERSEDED = "SUPERSEDED"


class PenaltyResolution(str, Enum):
    UPHELD = "UPHELD"
    WAIVED = "WAIVED"
    CREDITED = "CREDITED"


class RoundStatus(str, Enum):
    OPEN = "OPEN"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class RoundOutcome(str, Enum):
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class UptimeVariant(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    INCLUSIVE = "INCLUSIVE"


# ─── Entity shapes (PRD §2.4: every resource carries id/created_at/updated_at/version)

class ServiceContract(TypedDict):
    id: str
    building_name: str
    building_address: str
    jurisdiction_code: str
    fire_district_code: str
    building_manager_user_id: str
    contractor_user_id: str
    scope_type: str
    penalty_schedule: str
    monthly_base_fee_cents: int
    callback_response_minutes: int
    entrapment_response_minutes: int
    term_start_date: str
    term_end_date: str
    status: str
    cars_out_of_service_count: int
    penalty_lifetime_assessed_cents: int
    penalty_lifetime_waived_cents: int
    penalty_lifetime_credited_cents: int
    penalty_balance_cents: int
    performance_score: Optional[float]
    renegotiation_round_count: int
    created_at: str
    updated_at: str
    version: int


class ElevatorCar(TypedDict):
    id: str
    contract_id: str
    car_code: str
    car_type: str
    capacity_lbs: int
    availability_state: str
    compliance_state: str
    scheduled_downtime_minutes: int
    open_part_order_count: int
    unplanned_outage_open_since: Optional[str]
    red_tag_issued_at: Optional[str]
    red_tag_lifted_at: Optional[str]
    current_certificate_number: Optional[str]
    certificate_expiry_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceVisit(TypedDict):
    id: str
    car_id: str
    period_month: str
    scheduled_date: str
    status: str
    task_items: List[Dict[str, Any]]
    completed_task_codes: List[str]
    missing_task_codes: List[str]
    performed_at: Optional[str]
    performed_by_user_id: Optional[str]
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    rework_count: int
    created_at: str
    updated_at: str
    version: int


class Callback(TypedDict):
    id: str
    car_id: str
    callback_type: str
    passengers_trapped: int
    out_of_service: bool
    reported_at: str
    status: str
    fire_dispatch_requested_at: Optional[str]
    fire_dispatch_incident_number: Optional[str]
    arrived_at: Optional[str]
    cleared_at: Optional[str]
    resolution_note: Optional[str]
    response_minutes: Optional[int]
    sla_minutes: Optional[int]
    sla_breached: bool
    created_at: str
    updated_at: str
    version: int


class StateInspection(TypedDict):
    id: str
    car_id: str
    inspection_type: str
    scheduled_date: str
    status: str
    result: Optional[str]
    deficiency_codes: List[str]
    result_recorded_at: Optional[str]
    certificate_state: str
    certificate_number: Optional[str]
    certificate_issued_date: Optional[str]
    certificate_expiry_date: Optional[str]
    certificate_posted_at: Optional[str]
    posted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModernizationProject(TypedDict):
    id: str
    contract_id: str
    title: str
    budget_cents: int
    target_completion_date: str
    status: str
    approved_by_user_id: Optional[str]
    window_count: int
    created_at: str
    updated_at: str
    version: int


class DowntimeWindow(TypedDict):
    id: str
    car_id: str
    project_id: Optional[str]
    window_type: str
    window_start: str
    window_end: str
    duration_minutes: int
    status: str
    reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class SparePart(TypedDict):
    id: str
    part_number: str
    description_text: str
    part_class: str
    unit_price_cents: int
    lead_time_days: int
    lifecycle_state: str
    superseded_by_part_id: Optional[str]
    obsoleted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartOrder(TypedDict):
    id: str
    car_id: str
    part_id: str
    effective_part_id: str
    window_id: Optional[str]
    quantity: int
    expedite: bool
    subtotal_cents: int
    expedite_surcharge_cents: int
    total_cost_cents: int
    lead_time_days_applied: int
    promised_date: str
    substitution_hops: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PenaltyAssessment(TypedDict):
    id: str
    contract_id: str
    period_month: str
    schedule_applied: str
    uptime_variant_applied: str
    uptime_pct_applied: float
    late_callback_count: int
    entrapment_breach_count: int
    missed_visit_count: int
    raw_amount_cents: int
    cap_amount_cents: int
    amount_cents: int
    service_credit_cents: int
    status: str
    assessed_by_user_id: str
    dispute_reason: Optional[str]
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenegotiationRound(TypedDict):
    id: str
    contract_id: str
    round_number: int
    proposed_monthly_fee_cents: int
    proposed_callback_response_minutes: int
    proposed_scope_type: str
    status: str
    opened_by_user_id: str
    countered_by_user_id: Optional[str]
    accepted_by_user_id: Optional[str]
    trigger_performance_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class UptimeReport(TypedDict):
    car_id: str
    period_month: str
    period_minutes: int
    unplanned_outage_minutes: int
    planned_downtime_minutes: int
    available_minutes: int
    uptime_pct_exclusive: float
    uptime_pct_inclusive: float
    outage_interval_count: int


class ClockResponse(TypedDict):
    current_utc: str
    missed_visits_marked: int
    rejected_visits_marked: int
    certificates_expired: int
    windows_completed: int
    cars_under_modernization: int
