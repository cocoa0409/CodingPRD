"""Domain types: status enumerations, role enumeration and entity shapes."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    OUTFITTER_REPRESENTATIVE = "OutfitterRepresentative"
    PERMIT_SPECIALIST = "PermitSpecialist"
    AUTHORIZED_OFFICER = "AuthorizedOfficer"
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"


class AllocationPosture(str, Enum):
    OPEN = "OPEN"
    CONSTRAINED = "CONSTRAINED"
    EXHAUSTED = "EXHAUSTED"


class NeedsAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class PublicNeedFinding(str, Enum):
    NEED_EXISTS = "NEED_EXISTS"
    NO_NEED = "NO_NEED"


class OutfitterStatus(str, Enum):
    APPLICANT = "APPLICANT"
    PERMITTED = "PERMITTED"
    SUSPENDED = "SUSPENDED"


class GuideStatus(str, Enum):
    PENDING_QUALIFICATION = "PENDING_QUALIFICATION"
    QUALIFIED = "QUALIFIED"
    LAPSED = "LAPSED"


class QualificationLevel(str, Enum):
    TRAINEE = "TRAINEE"
    ASSISTANT = "ASSISTANT"
    LEAD = "LEAD"


class FirstAidCertType(str, Enum):
    NONE = "NONE"
    BASIC_FIRST_AID = "BASIC_FIRST_AID"
    WFR = "WFR"
    WEMT = "WEMT"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CAPACITY_SCREENED = "CAPACITY_SCREENED"
    DIRECT_AWARD_PENDING = "DIRECT_AWARD_PENDING"
    PROSPECTUS_QUEUED = "PROSPECTUS_QUEUED"
    PROSPECTUS_RESPONDED = "PROSPECTUS_RESPONDED"
    AWARDED = "AWARDED"
    PERMIT_ISSUED = "PERMIT_ISSUED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationType(str, Enum):
    NEW = "NEW"
    RENEWAL = "RENEWAL"


class RoutingDecision(str, Enum):
    DIRECT = "DIRECT"
    PROSPECTUS = "PROSPECTUS"


class ActivityType(str, Enum):
    HUNTING = "HUNTING"
    FISHING = "FISHING"
    PACK_STOCK = "PACK_STOCK"
    RIVER_FLOAT = "RIVER_FLOAT"
    MOUNTAINEERING = "MOUNTAINEERING"


class ProspectusStatus(str, Enum):
    OPEN = "OPEN"
    EVALUATING = "EVALUATING"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class PermitAdministrativeStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    CLOSED = "CLOSED"


class PermitComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    PROBATION = "PROBATION"
    NONCOMPLIANT = "NONCOMPLIANT"


class FeeScheduleCode(str, Enum):
    GRADUATED = "GRADUATED"
    FLAT_THREE_PERCENT = "FLAT_THREE_PERCENT"


class OperatingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class InsuranceCertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class CoverageType(str, Enum):
    GENERAL_LIABILITY = "GENERAL_LIABILITY"
    AUTO_LIABILITY = "AUTO_LIABILITY"
    WATERCRAFT_LIABILITY = "WATERCRAFT_LIABILITY"


class BondStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class GuideAuthorizationStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    REVOKED = "REVOKED"


class TripUseReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class FeeAssessmentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    PAID = "PAID"
    CLOSED = "CLOSED"


class FeeVariant(str, Enum):
    PROVISIONAL_PER_REPORT = "PROVISIONAL_PER_REPORT"
    FINAL_AGGREGATE = "FINAL_AGGREGATE"


class PerformanceRating(str, Enum):
    SUPERIOR = "SUPERIOR"
    SATISFACTORY = "SATISFACTORY"
    MARGINAL = "MARGINAL"
    UNSATISFACTORY = "UNSATISFACTORY"


class NoncomplianceSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"


class NoncomplianceActionType(str, Enum):
    WARNING = "WARNING"
    SUSPENSION = "SUSPENSION"
    REVOCATION = "REVOCATION"


class NoncomplianceActionStatus(str, Enum):
    ISSUED = "ISSUED"
    CURED = "CURED"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    RESCINDED = "RESCINDED"


# --- Entity shapes -----------------------------------------------------------
# Every record below carries id, created_at, updated_at and version, except
# PerformanceEvaluation, which is an append-only record carrying only id and
# created_at.


class UseArea(TypedDict):
    id: str
    area_code: str
    name: str
    total_allocated_service_days: int
    reserved_admin_service_days: int
    season_year: int
    season_open_date: str
    season_close_date: str
    party_size_max: int
    max_clients_per_guide: int
    min_liability_coverage_cents: int
    allocatable_service_days: int
    committed_service_days: int
    pending_service_days: int
    available_service_days: int
    demand_ratio: float
    allocation_posture: str
    created_at: str
    updated_at: str
    version: int


class NeedsAssessment(TypedDict):
    id: str
    use_area_id: str
    assessment_year: int
    public_need_finding: str
    determined_capacity_service_days: int
    allocated_service_days: int
    unallocated_service_days: int
    prospectus_required: bool
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Outfitter(TypedDict):
    id: str
    legal_name: str
    ein: str
    contact_email: str
    prequalification_insurance_verified: bool
    status: str
    active_permit_count: int
    prior_permit_count: int
    created_at: str
    updated_at: str
    version: int


class Guide(TypedDict):
    id: str
    outfitter_id: str
    full_name: str
    qualification_level: str
    first_aid_cert_type: str
    first_aid_expires_on: str
    seasons_experience: int
    base_client_capacity: int
    status: str
    qualified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    outfitter_id: str
    use_area_id: str
    prospectus_id: Optional[str]
    predecessor_permit_id: Optional[str]
    application_type: str
    season_year: int
    requested_service_days: int
    proposed_activity_type: str
    narrative: Optional[str]
    status: str
    routing_decision: Optional[str]
    screened_at: Optional[str]
    hold_expires_at: Optional[str]
    preliminary_evaluation_score: Optional[float]
    final_evaluation_score: Optional[float]
    denial_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Prospectus(TypedDict):
    id: str
    use_area_id: str
    needs_assessment_id: str
    offered_service_days: int
    submission_deadline_date: str
    min_qualifying_score: float
    status: str
    responsive_application_count: int
    awarded_application_id: Optional[str]
    cancellation_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    application_id: str
    outfitter_id: str
    use_area_id: str
    predecessor_permit_id: Optional[str]
    term_start_date: str
    term_end_date: str
    authorized_service_days: int
    fee_schedule_code: str
    indemnification_acknowledged: bool
    administrative_status: str
    compliance_status: str
    insurance_current: bool
    bond_current: bool
    fee_delinquent: bool
    open_noncompliance_points: int
    authorized_client_capacity_total: int
    service_days_used_ytd: int
    latest_performance_rating: Optional[str]
    suspension_count: int
    suspension_reason_code: Optional[str]
    suspended_until_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OperatingPlan(TypedDict):
    id: str
    permit_id: str
    plan_year: int
    sanitation_section: dict
    campsite_section: dict
    stock_section: dict
    resource_protection_section: dict
    completeness_score: float
    status: str
    revision_round: int
    deficiency_sections: List[str]
    reviewed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejection_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict):
    id: str
    permit_id: str
    coverage_type: str
    carrier_name: str
    coverage_amount_cents: int
    effective_date: str
    expiration_date: str
    additional_insured_endorsed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Bond(TypedDict):
    id: str
    permit_id: str
    bond_amount_cents: int
    required_amount_cents: int
    surety_name: str
    effective_date: str
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GuideAuthorization(TypedDict):
    id: str
    permit_id: str
    guide_id: str
    authorized_client_capacity: int
    status: str
    authorized_at: str
    revoked_at: Optional[str]
    revocation_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TripUseReport(TypedDict):
    id: str
    permit_id: str
    supersedes_report_id: Optional[str]
    season_year: int
    period_start_date: str
    period_end_date: str
    service_days_used: int
    client_count: int
    gross_revenue_cents: int
    allowable_deductions_cents: int
    adjusted_gross_revenue_cents: int
    applied_rate_bp: Optional[int]
    fee_component_cents: Optional[int]
    status: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict):
    id: str
    permit_id: str
    season_year: int
    variant_applied: str
    reported_agr_cents: int
    assessed_fee_cents: int
    minimum_fee_applied: bool
    paid_to_date_cents: int
    balance_due_cents: int
    credit_balance_cents: int
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceEvaluation(TypedDict):
    """Append-only evaluation record: carries only id and created_at as its
    common fields — no updated_at and no version."""
    id: str
    permit_id: str
    evaluation_year: int
    resource_protection_score: int
    client_safety_score: int
    reporting_timeliness_score: int
    fee_compliance_score: int
    raw_score: float
    provisional_band: str
    penalty_points_applied: float
    weighted_score: float
    rating: str
    evaluator_user_id: str
    created_at: str


class NoncomplianceAction(TypedDict):
    id: str
    permit_id: str
    severity: str
    action_type: str
    cited_provision: str
    cure_deadline_date: str
    points: int
    status: str
    issued_by_user_id: str
    corrective_summary: Optional[str]
    appeal_basis: Optional[str]
    appeal_decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
