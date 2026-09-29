"""Domain types for the Crane Rigging Lift API: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum (PRD 2.1) - the seven recognised roles, spelled exactly.
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    LIFT_DIRECTOR = "LiftDirector"
    ENGINEER = "Engineer"
    OPERATOR = "Operator"
    SAFETY_MANAGER = "SafetyManager"
    BILLING_CLERK = "BillingClerk"
    CUSTOMER = "Customer"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class BillingTerms(str, Enum):
    NET_15 = "NET_15"
    NET_30 = "NET_30"
    NET_45 = "NET_45"


class SurveyStatus(str, Enum):
    NOT_SURVEYED = "NOT_SURVEYED"
    SURVEYED = "SURVEYED"


class CraneStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class BoomConfiguration(str, Enum):
    MAIN_BOOM = "MAIN_BOOM"
    LUFFING_JIB = "LUFFING_JIB"
    FIXED_JIB = "FIXED_JIB"


class PersonnelRoleType(str, Enum):
    OPERATOR = "OPERATOR"
    RIGGER = "RIGGER"
    ENGINEER = "ENGINEER"


class RiggerLevel(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    MASTER = "MASTER"


class PersonnelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class GearType(str, Enum):
    SLING = "SLING"
    SHACKLE = "SHACKLE"
    SPREADER_BAR = "SPREADER_BAR"


class GearStatus(str, Enum):
    DUE_INSPECTION = "DUE_INSPECTION"
    SERVICEABLE = "SERVICEABLE"
    QUARANTINED = "QUARANTINED"
    RETIRED = "RETIRED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    REPAIR_PASS = "REPAIR_PASS"
    RETIRE = "RETIRE"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SURVEYED = "SURVEYED"
    CONFIGURED = "CONFIGURED"
    PENDING_ENGINEERING = "PENDING_ENGINEERING"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class FieldStatus(str, Enum):
    NOT_MOBILIZED = "NOT_MOBILIZED"
    MOBILIZED = "MOBILIZED"
    LIFTING = "LIFTING"
    WIND_HOLD = "WIND_HOLD"
    SECURED = "SECURED"
    DEMOBILIZED = "DEMOBILIZED"


class FieldAction(str, Enum):
    MOBILIZE = "MOBILIZE"
    START_LIFT = "START_LIFT"
    RESUME = "RESUME"
    SECURE = "SECURE"
    DEMOBILIZE = "DEMOBILIZE"


class LiftClass(str, Enum):
    NOT_CLASSIFIED = "NOT_CLASSIFIED"
    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"
    ENGINEERED_CRITICAL = "ENGINEERED_CRITICAL"


class BearingVariant(str, Enum):
    NONE = "NONE"
    PROVISIONAL_SURVEY = "PROVISIONAL_SURVEY"
    FINAL_ENGINEERED = "FINAL_ENGINEERED"


class GearAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class ReviewStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    STAMPED = "STAMPED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ReviewAction(str, Enum):
    REQUEST_CHANGES = "REQUEST_CHANGES"
    STAMP = "STAMP"
    REJECT = "REJECT"


class PermitType(str, Enum):
    ROAD_CLOSURE = "ROAD_CLOSURE"
    CRANE_PLACEMENT = "CRANE_PLACEMENT"
    OVERSIZE_ESCORT = "OVERSIZE_ESCORT"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"
    VOIDED = "VOIDED"


class PermitDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class StandbyCause(str, Enum):
    WIND = "WIND"
    WEATHER = "WEATHER"
    CUSTOMER_DELAY = "CUSTOMER_DELAY"
    SITE_ACCESS = "SITE_ACCESS"


class StandbyStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BillingMode(str, Enum):
    HOURLY = "HOURLY"
    LUMP_SUM = "LUMP_SUM"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


# --------------------------------------------------------------------------
# Entity TypedDicts.
#
# Most resources carry id + created_at + updated_at + version (PRD 2.4).
# A load-chart row and a gear-inspection record are append-only records of a
# moment and carry ONLY id and created_at - no updated_at, no version.
# --------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    account_name: str
    billing_terms: str
    credit_hold: bool
    credit_hold_reason: Optional[str]
    open_receivable_cents: int
    invoice_count: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    customer_id: str
    address_label: str
    jurisdiction_code: str
    soil_bearing_capacity_psf: int
    proximity_to_energized_lines_ft: int
    over_water: bool
    survey_status: str
    last_surveyed_at: Optional[str]
    access_notes: Optional[str]
    mat_inventory_available: bool
    created_at: str
    updated_at: str
    version: int


class Crane(TypedDict):
    id: str
    model_code: str
    class_tons: int
    gross_weight_lb: int
    counterweight_lb: int
    outrigger_pad_area_sqft: float
    max_line_pull_lb: int
    rated_max_wind_mph: int
    annual_inspection_expires_on: str
    mob_demob_cents: int
    hourly_rate_cents: int
    out_of_service_flag: bool
    status: str
    reserved_hours_total: float
    active_plan_count: int
    created_at: str
    updated_at: str
    version: int


class LoadChartEntry(TypedDict):
    # Append-only: id + created_at only.
    id: str
    crane_id: str
    configuration: str
    boom_length_ft: int
    radius_ft: int
    gross_capacity_lb: int
    created_at: str


class Personnel(TypedDict):
    id: str
    full_name: str
    role_type: str
    certification_number: str
    certification_expires_on: str
    endorsement_class_tons: int
    rigger_level: str
    pe_license_state: Optional[str]
    status: str
    peak_daily_assigned_hours: float
    created_at: str
    updated_at: str
    version: int


class RiggingGear(TypedDict):
    id: str
    gear_tag: str
    gear_type: str
    rated_wll_lb: int
    weight_lb: int
    inspection_interval_days: int
    last_inspection_at: Optional[str]
    next_inspection_due_at: Optional[str]
    repair_count: int
    effective_wll_lb: int
    status: str
    committed_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class GearInspection(TypedDict):
    # Append-only: id + created_at only.
    id: str
    gear_id: str
    result: str
    inspector_note: str
    inspected_at: str
    resulting_status: str
    repair_count_after: int
    created_at: str


class LiftPlan(TypedDict):
    id: str
    site_id: str
    customer_id: str
    crane_id: Optional[str]
    operator_id: Optional[str]
    rigger_id: Optional[str]
    job_reference: str
    window_start: str
    window_end: str
    load_weight_lb: int
    sail_area_sqft: float
    personnel_lift: bool
    multi_crane: bool
    road_closure_requested: bool
    configuration: Optional[str]
    boom_length_ft: Optional[int]
    radius_ft: Optional[int]
    parts_of_line: Optional[int]
    block_weight_lb: int
    jib_weight_lb: int
    aux_head_weight_lb: int
    chart_gross_capacity_lb: int
    hoist_line_capacity_lb: int
    net_capacity_lb: int
    rigging_weight_lb: int
    total_load_lb: int
    utilization_pct: float
    lift_class: str
    bearing_variant: str
    per_outrigger_load_lb: float
    bearing_pressure_psf: float
    matting_required: bool
    mat_area_required_sqft: int
    mat_count: int
    allowable_wind_mph: int
    escort_required: bool
    permit_required: bool
    rigging_verified: bool
    standby_hours_billable: float
    invoice_count: int
    plan_status: str
    field_status: str
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GearAssignment(TypedDict):
    id: str
    lift_plan_id: str
    gear_id: str
    leg_count: int
    sling_angle_deg: int
    load_angle_factor: float
    leg_tension_lb: int
    effective_wll_lb: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EngineeringReview(TypedDict):
    id: str
    lift_plan_id: str
    author_personnel_id: str
    stamped_by_personnel_id: Optional[str]
    analysis_notes: str
    revision_round: int
    change_request_note: Optional[str]
    decision_note: Optional[str]
    final_bearing_pressure_psf: float
    final_mat_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    lift_plan_id: str
    permit_type: str
    jurisdiction_code: str
    escort_required: bool
    required_lead_days: int
    permit_fee_cents: int
    cancellation_fee_cents: int
    submitted_at: Optional[str]
    decision_at: Optional[str]
    agency_reference: Optional[str]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StandbyEvent(TypedDict):
    id: str
    lift_plan_id: str
    cause: str
    wind_speed_mph: float
    started_at: str
    ended_at: Optional[str]
    raw_duration_hours: float
    forced_wind_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    lift_plan_id: str
    customer_id: str
    billing_mode: str
    on_site_hours: float
    travel_hours: float
    travel_miles: float
    lump_sum_cents: int
    standby_hours_source: float
    billable_hours: float
    regular_hours: float
    overtime_hours: float
    line_regular_cents: int
    line_overtime_cents: int
    line_standby_cents: int
    line_travel_cents: int
    line_mobdemob_cents: int
    line_lump_sum_cents: int
    line_permit_cancellation_cents: int
    subtotal_cents: int
    discount_pct: float
    discount_cents: int
    fuel_surcharge_cents: int
    total_cents: int
    system_generated: bool
    status: str
    created_at: str
    updated_at: str
    version: int
