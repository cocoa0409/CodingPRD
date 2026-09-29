"""Domain types for the Disaster Public Assistance Grant Administration API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    APPLICANT_AGENT = "ApplicantAgent"
    PROGRAM_SPECIALIST = "ProgramSpecialist"
    GRANTS_OFFICER = "GrantsOfficer"
    APPEALS_ADJUDICATOR = "AppealsAdjudicator"
    STATE_AUDITOR = "StateAuditor"


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------
class DisasterStatus(str, Enum):
    DECLARED = "DECLARED"
    OBLIGATION_CLOSED = "OBLIGATION_CLOSED"


class IncidentType(str, Enum):
    SEVERE_STORM = "SEVERE_STORM"
    FLOOD = "FLOOD"
    WILDFIRE = "WILDFIRE"
    HURRICANE = "HURRICANE"
    EARTHQUAKE = "EARTHQUAKE"


class ApplicantType(str, Enum):
    LOCAL_GOVERNMENT = "LOCAL_GOVERNMENT"
    TRIBE = "TRIBE"
    STATE_AGENCY = "STATE_AGENCY"
    PRIVATE_NONPROFIT = "PRIVATE_NONPROFIT"


class PnpServiceType(str, Enum):
    CRITICAL = "CRITICAL"
    ESSENTIAL_NON_CRITICAL = "ESSENTIAL_NON_CRITICAL"
    NON_ELIGIBLE = "NON_ELIGIBLE"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class MonitoringStatus(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"


class DrawdownAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AuditRequirement(str, Enum):
    NONE = "NONE"
    SINGLE_AUDIT = "SINGLE_AUDIT"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class FacilityType(str, Enum):
    ROAD_BRIDGE = "ROAD_BRIDGE"
    WATER_CONTROL = "WATER_CONTROL"
    BUILDING_EQUIPMENT = "BUILDING_EQUIPMENT"
    UTILITY = "UTILITY"
    PARK_RECREATION = "PARK_RECREATION"
    EMERGENCY_PROTECTIVE = "EMERGENCY_PROTECTIVE"


class FacilityOwnership(str, Enum):
    PUBLIC = "PUBLIC"
    PNP_OWNED = "PNP_OWNED"
    LEASED = "LEASED"


class ScreeningFailureReason(str, Enum):
    LEGAL_RESPONSIBILITY_NOT_DOCUMENTED = "LEGAL_RESPONSIBILITY_NOT_DOCUMENTED"
    NOT_IN_ACTIVE_USE = "NOT_IN_ACTIVE_USE"
    PNP_MUST_OWN_FACILITY = "PNP_MUST_OWN_FACILITY"
    TAX_EXEMPT_DOCUMENTATION_MISSING = "TAX_EXEMPT_DOCUMENTATION_MISSING"
    PNP_SERVICE_NOT_ELIGIBLE = "PNP_SERVICE_NOT_ELIGIBLE"


class DamageCategory(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"


class ValidationStatus(str, Enum):
    REPORTED = "REPORTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class WorkType(str, Enum):
    EMERGENCY = "EMERGENCY"
    PERMANENT = "PERMANENT"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    RFI_ISSUED = "RFI_ISSUED"
    VALIDATED = "VALIDATED"
    OBLIGATED = "OBLIGATED"
    CLOSEOUT_REQUESTED = "CLOSEOUT_REQUESTED"
    CLOSED = "CLOSED"
    DENIED = "DENIED"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    LARGE = "LARGE"


class CostType(str, Enum):
    FORCE_ACCOUNT_LABOR = "FORCE_ACCOUNT_LABOR"
    FORCE_ACCOUNT_EQUIPMENT = "FORCE_ACCOUNT_EQUIPMENT"
    MATERIALS = "MATERIALS"
    CONTRACT = "CONTRACT"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ALLOWED = "ALLOWED"
    PARTIALLY_ALLOWED = "PARTIALLY_ALLOWED"
    DISALLOWED = "DISALLOWED"


class DisallowanceReason(str, Enum):
    STRAIGHT_TIME_NOT_ELIGIBLE_FOR_EMERGENCY_WORK = (
        "STRAIGHT_TIME_NOT_ELIGIBLE_FOR_EMERGENCY_WORK"
    )
    FRINGE_RATE_CAPPED = "FRINGE_RATE_CAPPED"
    LESSER_OF_RATE_APPLIED = "LESSER_OF_RATE_APPLIED"
    CLAIM_EXCEEDS_COMPUTED_COST = "CLAIM_EXCEEDS_COMPUTED_COST"
    PROCUREMENT_NONCOMPLIANT = "PROCUREMENT_NONCOMPLIANT"
    CONTRACT_AWARD_CEILING_REACHED = "CONTRACT_AWARD_CEILING_REACHED"


class ResourceKind(str, Enum):
    LABOR = "LABOR"
    EQUIPMENT = "EQUIPMENT"


class EmployeeType(str, Enum):
    PERMANENT = "PERMANENT"
    TEMPORARY = "TEMPORARY"


class ContractType(str, Enum):
    SEALED_BID = "SEALED_BID"
    COMPETITIVE_PROPOSAL = "COMPETITIVE_PROPOSAL"
    NONCOMPETITIVE = "NONCOMPETITIVE"
    SMALL_PURCHASE = "SMALL_PURCHASE"
    TIME_AND_MATERIALS = "TIME_AND_MATERIALS"
    COST_PLUS_PERCENTAGE_OF_COST = "COST_PLUS_PERCENTAGE_OF_COST"


class ProcurementStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    COMPLIANT = "COMPLIANT"
    NONCOMPLIANT = "NONCOMPLIANT"


class NoncomplianceReason(str, Enum):
    PROHIBITED_CONTRACT_TYPE = "PROHIBITED_CONTRACT_TYPE"
    TIME_AND_MATERIALS_CEILING_EXCEEDED = "TIME_AND_MATERIALS_CEILING_EXCEEDED"
    SOLE_SOURCE_UNJUSTIFIED = "SOLE_SOURCE_UNJUSTIFIED"
    INADEQUATE_COMPETITION = "INADEQUATE_COMPETITION"
    DEBARMENT_CHECK_MISSING = "DEBARMENT_CHECK_MISSING"


class PolicyType(str, Enum):
    FLOOD = "FLOOD"
    PROPERTY = "PROPERTY"


class DrawdownStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    REFUNDED = "REFUNDED"


class ProgressReportStatus(str, Enum):
    DUE = "DUE"
    SUBMITTED = "SUBMITTED"
    LATE = "LATE"
    DELINQUENT = "DELINQUENT"


class DeobligationReason(str, Enum):
    CLOSEOUT_UNDERRUN = "CLOSEOUT_UNDERRUN"
    INSURANCE_DOB = "INSURANCE_DOB"
    DISALLOWED_COST = "DISALLOWED_COST"
    PROCUREMENT_NONCOMPLIANCE = "PROCUREMENT_NONCOMPLIANCE"
    SCOPE_REDUCTION = "SCOPE_REDUCTION"


class DeobligationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    FINAL = "FINAL"
    REVERSED = "REVERSED"


class AppealLevel(str, Enum):
    FIRST = "FIRST"
    SECOND = "SECOND"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
    DENIED = "DENIED"
    REMANDED = "REMANDED"


# --------------------------------------------------------------------------
# Entity TypedDicts.  Every resource in this PRD carries id, created_at,
# updated_at and version.
# --------------------------------------------------------------------------
class Disaster(TypedDict):
    id: str
    declaration_number: str
    state_code: str
    incident_type: str
    incident_start_at: str
    incident_end_at: str
    population: int
    federal_cost_share_pct: float
    small_project_threshold_cents: int
    status: str
    total_validated_loss_cents: int
    per_capita_impact_cents: int
    indicator_met: bool
    total_obligated_cents: int
    total_drawn_cents: int
    enhanced_monitoring_applicant_count: int
    suspended_applicant_count: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    disaster_id: str
    name: str
    applicant_type: str
    pnp_service_type: Optional[str]
    pnp_sba_referral_completed: bool
    tax_exempt_letter_on_file: bool
    population_served: int
    eligibility_status: str
    eligibility_rationale: Optional[str]
    monitoring_status: str
    drawdown_status: str
    audit_requirement: str
    risk_score_screening: float
    risk_score_monitoring: Optional[float]
    monitoring_scored_at: Optional[str]
    risk_tier: str
    total_obligated_cents: int
    total_drawn_cents: int
    total_refunded_cents: int
    cash_on_hand_cents: int
    available_drawdown_cents: int
    pending_deobligation_cents: int
    delinquent_report_count: int
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    applicant_id: str
    name: str
    facility_type: str
    ownership: str
    in_active_use: bool
    legal_responsibility_documented: bool
    flood_zone: bool
    prior_disaster_flood_damage: bool
    eligibility_status: str
    screening_failure_reason: Optional[str]
    screened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageAssessmentSite(TypedDict):
    id: str
    facility_id: str
    category: str
    reported_loss_cents: int
    damage_observed_at: str
    work_completed_pct: float
    validated_loss_cents: int
    validation_status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    applicant_id: str
    facility_id: str
    category: str
    work_type: Optional[str]
    title: str
    scope_of_work: str
    estimated_repair_cost_cents: int
    mitigation_requested_cents: int
    status: str
    size_class: Optional[str]
    rfi_round_count: int
    last_rfi_question: Optional[str]
    repair_eligible_cents: int
    anticipated_insurance_cents: int
    settlement_allocated_cents: int
    insurance_reduction_cents: int
    mitigation_approved_cents: int
    eligible_cost_provisional_cents: int
    eligible_cost_final_cents: Optional[int]
    federal_share_obligated_cents: int
    federal_share_final_cents: Optional[int]
    deobligated_cents: int
    pending_deobligation_cents: int
    closeout_variance_cents: Optional[int]
    cost_reviewed_by_user_id: Optional[str]
    obligated_by_user_id: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostLineItem(TypedDict):
    id: str
    project_id: str
    cost_type: str
    force_account_resource_id: Optional[str]
    contract_id: Optional[str]
    claimed_cents: int
    work_start_at: str
    work_end_at: str
    straight_time_hours: float
    overtime_hours: float
    equipment_hours: float
    eligible_cents: int
    review_status: str
    disallowance_reason: Optional[str]
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ForceAccountResource(TypedDict):
    id: str
    applicant_id: str
    resource_kind: str
    label: str
    employee_type: Optional[str]
    base_hourly_rate_cents: int
    fringe_benefit_pct: float
    equipment_code: Optional[str]
    published_hourly_rate_cents: int
    schedule_hourly_rate_cents: int
    charged_hours_total: float
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    applicant_id: str
    vendor_name: str
    contract_type: str
    award_amount_cents: int
    bids_received: int
    advertised: bool
    sole_source_justification_on_file: bool
    debarment_check_completed: bool
    awarded_at: str
    procurement_status: str
    noncompliance_reason: Optional[str]
    allowed_cost_total_cents: int
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    facility_id: str
    insurer_name: str
    policy_type: str
    is_nfip: bool
    coverage_limit_cents: int
    deductible_cents: int
    effective_start_at: str
    effective_end_at: str
    settlement_amount_cents: int
    settled_at: Optional[str]
    allocated_cents: int
    unallocated_cents: int
    created_at: str
    updated_at: str
    version: int


class Drawdown(TypedDict):
    id: str
    applicant_id: str
    project_id: str
    requested_cents: int
    approved_cents: int
    refunded_cents: int
    status: str
    disbursed_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgressReport(TypedDict):
    id: str
    applicant_id: str
    quarter_label: str
    period_start_at: str
    period_end_at: str
    due_at: str
    expenditures_to_date_cents: int
    pct_complete: float
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Deobligation(TypedDict):
    id: str
    project_id: str
    reason: str
    amount_cents: int
    status: str
    determined_by_user_id: str
    finalized_at: Optional[str]
    appeal_deadline_at: Optional[str]
    reversed_cents: int
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    deobligation_id: str
    prior_appeal_id: Optional[str]
    level: str
    grounds: str
    relief_requested_cents: int
    relief_granted_cents: int
    status: str
    filed_at: str
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    decision_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int
