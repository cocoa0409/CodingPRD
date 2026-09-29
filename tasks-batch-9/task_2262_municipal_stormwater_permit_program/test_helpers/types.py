"""Domain types for the Municipal Stormwater Permit Program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    STORMWATER_PROGRAM_MANAGER = "StormwaterProgramManager"
    IDDE_INVESTIGATOR = "IDDEInvestigator"
    CONSTRUCTION_INSPECTOR = "ConstructionInspector"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    MUNICIPAL_OPERATIONS_SUPERVISOR = "MunicipalOperationsSupervisor"
    UTILITY_BILLING_CLERK = "UtilityBillingClerk"
    PROPERTY_OWNER = "PropertyOwner"


# --------------------------------------------------------------------------
# Enumerated states and classifications
# --------------------------------------------------------------------------


class PermitTermStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    AT_RISK = "AT_RISK"
    NON_COMPLIANT = "NON_COMPLIANT"


class FundingAdequacyStatus(str, Enum):
    ADEQUATE = "ADEQUATE"
    UNDERFUNDED = "UNDERFUNDED"


class TmdlPollutant(str, Enum):
    TOTAL_PHOSPHORUS = "TOTAL_PHOSPHORUS"
    TOTAL_NITROGEN = "TOTAL_NITROGEN"
    SEDIMENT = "SEDIMENT"
    BACTERIA = "BACTERIA"


class MeasureCode(str, Enum):
    PUBLIC_EDUCATION = "PUBLIC_EDUCATION"
    ILLICIT_DISCHARGE = "ILLICIT_DISCHARGE"
    CONSTRUCTION_RUNOFF = "CONSTRUCTION_RUNOFF"
    POST_CONSTRUCTION = "POST_CONSTRUCTION"
    MUNICIPAL_OPERATIONS = "MUNICIPAL_OPERATIONS"
    MONITORING = "MONITORING"


class ControlMeasureStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class GoalStatus(str, Enum):
    PENDING = "PENDING"
    MET = "MET"
    ON_TRACK = "ON_TRACK"
    BEHIND = "BEHIND"


class OutfallStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ScreeningStatus(str, Enum):
    NOT_SCREENED = "NOT_SCREENED"
    CLEAR = "CLEAR"
    SUSPECT = "SUSPECT"


class TmdlStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    ATTAINING = "ATTAINING"
    EXCEEDING = "EXCEEDING"


class PriorityTier(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ObservationType(str, Enum):
    DRY_WEATHER_SCREENING = "DRY_WEATHER_SCREENING"
    WET_WEATHER_SAMPLE = "WET_WEATHER_SAMPLE"


class ScreeningResult(str, Enum):
    CLEAR = "CLEAR"
    SUSPECT = "SUSPECT"


class ValidationStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    TRACING = "TRACING"
    SOURCE_IDENTIFIED = "SOURCE_IDENTIFIED"
    ENFORCEMENT = "ENFORCEMENT"
    RESOLVED = "RESOLVED"


class TraceMethod(str, Enum):
    DYE_TEST = "DYE_TEST"
    SMOKE_TEST = "SMOKE_TEST"
    CCTV = "CCTV"
    UPSTREAM_SAMPLING = "UPSTREAM_SAMPLING"


class PlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ESC_REVIEW = "ESC_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"


class FieldStatus(str, Enum):
    PRE_CONSTRUCTION = "PRE_CONSTRUCTION"
    ACTIVE_DISTURBANCE = "ACTIVE_DISTURBANCE"
    STOP_WORK = "STOP_WORK"
    CLOSED = "CLOSED"


class EscReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"


class FacilityType(str, Enum):
    BIORETENTION = "BIORETENTION"
    WET_POND = "WET_POND"
    INFILTRATION_TRENCH = "INFILTRATION_TRENCH"
    UNDERGROUND_DETENTION = "UNDERGROUND_DETENTION"


class FacilityOwnership(str, Enum):
    MUNICIPAL = "MUNICIPAL"
    PRIVATE = "PRIVATE"


class AgreementStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    RECORDED = "RECORDED"


class InspectionType(str, Enum):
    CONSTRUCTION_ESC = "CONSTRUCTION_ESC"
    POST_CONSTRUCTION_MAINTENANCE = "POST_CONSTRUCTION_MAINTENANCE"


class InspectionStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class FindingSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ActionType(str, Enum):
    NOTICE_OF_VIOLATION = "NOTICE_OF_VIOLATION"
    ADMINISTRATIVE_ORDER = "ADMINISTRATIVE_ORDER"
    CIVIL_PENALTY = "CIVIL_PENALTY"


class EnforcementStatus(str, Enum):
    ISSUED = "ISSUED"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"
    RESCINDED = "RESCINDED"


class SubjectKind(str, Enum):
    ILLICIT_DISCHARGE_CASE = "ILLICIT_DISCHARGE_CASE"
    CONSTRUCTION_SITE = "CONSTRUCTION_SITE"
    POST_CONSTRUCTION_FACILITY = "POST_CONSTRUCTION_FACILITY"


class ParcelClass(str, Enum):
    RESIDENTIAL_SINGLE = "RESIDENTIAL_SINGLE"
    RESIDENTIAL_MULTI = "RESIDENTIAL_MULTI"
    COMMERCIAL = "COMMERCIAL"
    INSTITUTIONAL = "INSTITUTIONAL"


class BillingRunType(str, Enum):
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class LoadAssessmentVariant(str, Enum):
    FINAL = "FINAL"
    PROVISIONAL = "PROVISIONAL"


class CreditApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class CreditReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"
    DENY = "DENY"


class AnnualReportStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPILED = "COMPILED"
    CERTIFIED = "CERTIFIED"
    SUBMITTED = "SUBMITTED"


class InvalidatedReason(str, Enum):
    POSTURE_CHANGED = "POSTURE_CHANGED"
    PENALTY_LEDGER_CHANGED = "PENALTY_LEDGER_CHANGED"


class StopWorkReason(str, Enum):
    AUTOMATIC_ESC_DEFICIENCY = "AUTOMATIC_ESC_DEFICIENCY"


class ObservationValidateDecision(str, Enum):
    VALIDATE = "VALIDATE"
    REJECT = "REJECT"


# --------------------------------------------------------------------------
# Entity shapes (PRD §2.4: every stored resource kind carries
# id / created_at / updated_at / version)
# --------------------------------------------------------------------------


class PermitTerm(TypedDict):
    id: str
    permit_number: str
    term_start_date: str
    term_end_date: str
    tmdl_applicable: bool
    tmdl_pollutant: Optional[str]
    tmdl_wla_lb_per_year: Optional[float]
    eru_sqft: int
    funding_target_cents: int
    status: str
    compliance_posture: str
    behind_measure_count: int
    exceeding_outfall_count: int
    total_assessed_penalty_cents: int
    projected_annual_revenue_cents: int
    funding_adequacy_status: str
    activated_at: Optional[str]
    expired_at: Optional[str]
    last_compiled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ControlMeasure(TypedDict):
    id: str
    permit_term_id: str
    measure_code: str
    measurable_goal_target: float
    weight: int
    salt_storage_covered: bool
    fleet_wash_recycle: bool
    status: str
    goal_status: str
    measurable_goal_actual: float
    attainment_pct: float
    open_case_count: int
    enforcement_count: int
    swept_lane_miles_ytd: float
    last_progress_reported_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Outfall(TypedDict):
    id: str
    permit_term_id: str
    outfall_code: str
    receiving_water: str
    drainage_area_acres: float
    priority_tier: str
    baseline_concentration_mg_per_l: float
    design_runoff_kl: float
    sweeping_capacity_lane_miles_per_month: float
    status: str
    screening_status: str
    tmdl_status: str
    sweeping_runs: List[Dict[str, Any]]
    swept_lane_miles_ytd: float
    screening_count: int
    open_case_count: int
    last_screened_at: Optional[str]
    last_assessed_year: Optional[int]
    last_assessed_gross_load_lb: float
    last_assessed_credit_lb: float
    last_assessed_net_load_lb: float
    created_at: str
    updated_at: str
    version: int


class OutfallObservation(TypedDict):
    id: str
    outfall_id: str
    observation_type: str
    observed_at: str
    field_notes: Optional[str]
    dry_weather_flow_present: Optional[bool]
    indicator_bacteria_mpn: Optional[float]
    indicator_surfactant_mg_per_l: Optional[float]
    indicator_ammonia_mg_per_l: Optional[float]
    pollutant_concentration_mg_per_l: Optional[float]
    runoff_volume_kl: Optional[float]
    recorded_by_user_id: str
    screening_result: Optional[str]
    validation_status: str
    validated_at: Optional[str]
    sample_load_lb: Optional[float]
    created_at: str
    updated_at: str
    version: int


class IllicitDischargeCase(TypedDict):
    id: str
    outfall_id: str
    origin_observation_id: str
    status: str
    opened_at: str
    trace_method: Optional[str]
    tracing_attempt_count: int
    source_description: Optional[str]
    responsible_party: Optional[str]
    reopen_count: int
    enforcement_action_count: int
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConstructionSite(TypedDict):
    id: str
    permit_term_id: str
    site_name: str
    operator_name: str
    disturbed_acres: float
    post_construction_control_required: bool
    plan_status: str
    field_status: str
    plan_review_round: int
    esc_plan_reference: Optional[str]
    stop_work_count: int
    stop_work_reason: Optional[str]
    open_deficiency_score: int
    open_enforcement_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PostConstructionFacility(TypedDict):
    id: str
    construction_site_id: str
    facility_type: str
    ownership: str
    design_capacity_cf: float
    service_area_acres: float
    agreement_status: str
    agreement_reference: Optional[str]
    agreement_recorded_at: Optional[str]
    inspection_interval_months: Optional[int]
    last_inspection_finalized_at: Optional[str]
    months_since_last_inspection: int
    inspection_overdue: bool
    credit_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    inspection_type: str
    construction_site_id: Optional[str]
    post_construction_facility_id: Optional[str]
    period_start: str
    period_end: str
    rainfall_trigger: bool
    status: str
    findings: List[Dict[str, Any]]
    minor_finding_count: int
    major_finding_count: int
    critical_finding_count: int
    deficiency_score: int
    escalation_triggered: bool
    finalized_at: Optional[str]
    finalized_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnforcementAction(TypedDict):
    id: str
    action_type: str
    illicit_discharge_case_id: Optional[str]
    construction_site_id: Optional[str]
    post_construction_facility_id: Optional[str]
    source_inspection_id: Optional[str]
    subject_kind: str
    violation_days: int
    billable_violation_days: int
    prior_assessed_total_cents: int
    escalation_multiplier: float
    penalty_cents: int
    status: str
    issued_at: str
    issued_by_user_id: str
    escalation_count: int
    last_escalated_at: Optional[str]
    auto_generated: bool
    compliance_note: Optional[str]
    closed_at: Optional[str]
    rescinded_reason: Optional[str]
    rescinded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StormwaterAccount(TypedDict):
    id: str
    permit_term_id: str
    parcel_id: str
    owner_name: str
    parcel_class: str
    impervious_area_sqft: float
    eru_units: float
    gross_fee_cents: int
    class_surcharge_cents: int
    gross_billable_cents: int
    total_credit_pct: float
    current_net_fee_cents: int
    last_billed_run_type: Optional[str]
    last_billed_net_cents: Optional[int]
    last_billed_credit_pct: Optional[float]
    last_billed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeCreditApplication(TypedDict):
    id: str
    stormwater_account_id: str
    post_construction_facility_id: Optional[str]
    requested_credit_pct: float
    bmp_description: str
    status: str
    submitted_at: str
    applicant_user_id: str
    approved_credit_pct: Optional[float]
    reviewed_by_user_id: Optional[str]
    approved_at: Optional[str]
    return_reason: Optional[str]
    revoked_reason: Optional[str]
    revoked_at: Optional[str]
    resubmission_count: int
    created_at: str
    updated_at: str
    version: int


class AnnualReport(TypedDict):
    id: str
    permit_term_id: str
    reporting_period_start: str
    reporting_period_end: str
    status: str
    screenings_completed: int
    outfall_screening_coverage_pct: float
    cases_opened: int
    cases_resolved: int
    construction_inspections_finalized: int
    facility_inspections_finalized: int
    enforcement_actions_issued: int
    total_penalty_assessed_cents: int
    swept_lane_miles: float
    net_annual_load_lb: float
    measurable_goals_met_count: int
    compliance_index: float
    invalidation_count: int
    invalidated_reason: Optional[str]
    compiled_at: Optional[str]
    compiled_by_user_id: Optional[str]
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]
    certification_statement: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
