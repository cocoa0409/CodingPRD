"""Domain types for the Sports Performance Facility API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles (PRD §2.1) ───────────────────────────────────────────────────────

class UserRole(str, Enum):
    PERFORMANCE_DIRECTOR = "PerformanceDirector"
    COACH = "Coach"
    MEDICAL_PROVIDER = "MedicalProvider"
    FRONT_DESK = "FrontDesk"
    ATHLETE = "Athlete"
    GUARDIAN = "Guardian"


# ─── Status enums ───────────────────────────────────────────────────────────

class MembershipStatus(str, Enum):
    PENDING_INTAKE = "PENDING_INTAKE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TrainingClearance(str, Enum):
    SCREEN_PENDING = "SCREEN_PENDING"
    CLEARED = "CLEARED"
    RESTRICTED = "RESTRICTED"
    MEDICAL_HOLD = "MEDICAL_HOLD"


class Sport(str, Enum):
    BASKETBALL = "BASKETBALL"
    SOCCER = "SOCCER"
    BASEBALL = "BASEBALL"
    VOLLEYBALL = "VOLLEYBALL"
    TRACK = "TRACK"


class InjuryRecordStatus(str, Enum):
    ACTIVE_REHAB = "ACTIVE_REHAB"
    RESOLVED = "RESOLVED"


class BodyRegion(str, Enum):
    KNEE = "KNEE"
    SHOULDER = "SHOULDER"
    ANKLE = "ANKLE"
    HIP = "HIP"
    LUMBAR = "LUMBAR"
    ELBOW = "ELBOW"


class InjurySeverity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class BatteryType(str, Enum):
    MOVEMENT_SCREEN = "MOVEMENT_SCREEN"
    PERFORMANCE_BATTERY = "PERFORMANCE_BATTERY"


class TestSessionStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class VariantApplied(str, Enum):
    INTAKE_SCREEN = "INTAKE_SCREEN"
    REASSESSMENT_SCREEN = "REASSESSMENT_SCREEN"
    RAW_NORM = "RAW_NORM"
    MATURITY_ADJUSTED = "MATURITY_ADJUSTED"


class ScreenMetricCode(str, Enum):
    OH_SQUAT = "OH_SQUAT"
    HURDLE_STEP = "HURDLE_STEP"
    INLINE_LUNGE = "INLINE_LUNGE"
    SL_HOP_L = "SL_HOP_L"
    SL_HOP_R = "SL_HOP_R"


class BatteryMetricCode(str, Enum):
    CMJ_CM = "CMJ_CM"
    SPRINT_10M_S = "SPRINT_10M_S"
    IMTP_N = "IMTP_N"


class TrainingProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ProgramBlockStatus(str, Enum):
    PLANNED = "PLANNED"
    PINNED = "PINNED"


class ProgramPhase(str, Enum):
    GENERAL_PREP = "GENERAL_PREP"
    SPECIFIC_PREP = "SPECIFIC_PREP"
    COMPETITION = "COMPETITION"
    TAPER = "TAPER"
    TRANSITION = "TRANSITION"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"


class StaffingStatus(str, Enum):
    STAFF_PENDING = "STAFF_PENDING"
    UNDERSTAFFED = "UNDERSTAFFED"
    STAFFED = "STAFFED"


class SiteCode(str, Enum):
    ONSITE = "ONSITE"
    OFFSITE = "OFFSITE"


class PhaseFocus(str, Enum):
    GENERAL_PREP = "GENERAL_PREP"
    SPECIFIC_PREP = "SPECIFIC_PREP"
    COMPETITION = "COMPETITION"
    TRANSITION = "TRANSITION"


class CoachRole(str, Enum):
    LEAD = "LEAD"
    ASSISTANT = "ASSISTANT"


class RateTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class EnrollmentStatus(str, Enum):
    RESERVED = "RESERVED"
    WAITLISTED = "WAITLISTED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    LATE_CANCEL = "LATE_CANCEL"
    CANCELED = "CANCELED"


class FundingSource(str, Enum):
    TEAM_CONTRACT = "TEAM_CONTRACT"
    MEMBERSHIP_PACKAGE = "MEMBERSHIP_PACKAGE"
    DROP_IN = "DROP_IN"
    UNFUNDED = "UNFUNDED"


class FundingPreference(str, Enum):
    ANY = "ANY"
    PACKAGE_ONLY = "PACKAGE_ONLY"
    DROP_IN_OK = "DROP_IN_OK"


class CancelReason(str, Enum):
    ATHLETE_REQUEST = "ATHLETE_REQUEST"
    SESSION_CANCELED = "SESSION_CANCELED"
    ATHLETE_SUSPENDED = "ATHLETE_SUSPENDED"
    FUNDING_UNAVAILABLE = "FUNDING_UNAVAILABLE"


class CredentialStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    EXPIRING = "EXPIRING"
    LAPSED = "LAPSED"


class RoleTitle(str, Enum):
    HEAD_COACH = "HEAD_COACH"
    PERFORMANCE_COACH = "PERFORMANCE_COACH"
    INTERN = "INTERN"


class CertificationStatus(str, Enum):
    VALID = "VALID"
    EXPIRING = "EXPIRING"
    LAPSED = "LAPSED"


class CertCode(str, Enum):
    CSCS = "CSCS"
    USAW = "USAW"
    CPR_AED = "CPR_AED"
    SCCC = "SCCC"


class MembershipPackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class TeamContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class OrganizationType(str, Enum):
    SCHOOL = "SCHOOL"
    CLUB = "CLUB"


class RtsPlanStatus(str, Enum):
    STAGE_ACTIVE = "STAGE_ACTIVE"
    STAGE_TESTING = "STAGE_TESTING"
    MEDICAL_REVIEW = "MEDICAL_REVIEW"
    CLEARED = "CLEARED"
    ABORTED = "ABORTED"


class StageDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ClearanceDocumentStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class DocumentType(str, Enum):
    STAGE_CLEARANCE = "STAGE_CLEARANCE"
    FULL_RELEASE = "FULL_RELEASE"
    MEDICAL_HOLD_RELEASE = "MEDICAL_HOLD_RELEASE"


# ─── Entity TypedDicts (every resource carries updated_at and version, PRD §2.5) ──

class Athlete(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    sport: str
    position: str
    guardian_email: Optional[str]
    maturity_offset_months: int
    age_years: int
    membership_status: str
    training_clearance: str
    screen_count: int
    injury_risk_score: Optional[float]
    readiness_index: float
    last_composite_percentile: Optional[float]
    last_performance_test_at: Optional[str]
    next_test_due_on: Optional[str]
    attended_count: int
    no_show_count: int
    no_show_strikes: int
    team_contract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InjuryRecord(TypedDict):
    id: str
    athlete_id: str
    body_region: str
    severity: str
    occurred_on: str
    rts_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TestSession(TypedDict):
    id: str
    athlete_id: str
    battery_type: str
    status: str
    administered_by_staff_id: str
    rts_plan_id: Optional[str]
    results: List[dict]
    result_count: int
    age_years_at_test: Optional[int]
    effective_age_years: Optional[int]
    metric_percentiles: Optional[List[dict]]
    composite_percentile: Optional[float]
    risk_score: Optional[float]
    asymmetry_points: Optional[int]
    variant_applied: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingProgram(TypedDict):
    id: str
    athlete_id: str
    sport: str
    position: str
    competition_start_date: str
    competition_end_date: str
    status: str
    block_count: int
    total_weeks: int
    planned_load_units: float
    pinned_block_versions: Optional[List[dict]]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramBlock(TypedDict):
    id: str
    training_program_id: str
    phase: str
    start_week: int
    end_week: int
    target_intensity_pct: float
    weekly_volume_units: float
    predecessor_block_id: Optional[str]
    sequence_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GroupSession(TypedDict):
    id: str
    start_at: str
    end_at: str
    site_code: str
    offsite_location: Optional[str]
    station_count: int
    phase_focus: str
    max_athletes: int
    team_contract_id: Optional[str]
    session_status: str
    staffing_status: str
    assigned_staff: List[dict]
    compliant_coach_count: int
    required_coach_count: int
    athlete_units: float
    reserved_count: int
    waitlisted_count: int
    attended_count: int
    no_show_count: int
    billed_rate_cents: Optional[int]
    rate_tier_applied: Optional[str]
    delivered_slots_at_completion: Optional[int]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    athlete_id: str
    group_session_id: str
    status: str
    funding_preference: str
    funding_source: str
    membership_package_id: Optional[str]
    charge_cents: int
    station_number: Optional[int]
    promoted_from_waitlist: bool
    cancel_reason: Optional[str]
    strike_index_at_no_show: Optional[int]
    no_show_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    full_name: str
    role_title: str
    liability_insurance_expires_on: str
    credential_status: str
    valid_certification_count: int
    lapsed_certification_count: int
    ceu_credits_earned_total: int
    last_credential_review_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    staff_member_id: str
    cert_code: str
    issued_on: str
    expires_on: str
    ceu_credits_required: int
    ceu_credits_earned: int
    renewal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MembershipPackage(TypedDict):
    id: str
    athlete_id: str
    sessions_purchased: int
    price_cents: int
    expires_on: str
    effective_expires_on: str
    status: str
    sessions_remaining: int
    sessions_reserved: int
    sessions_consumed: int
    sessions_forfeited: int
    frozen_days_total: int
    frozen_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TeamContract(TypedDict):
    id: str
    organization_name: str
    organization_type: str
    contracted_sessions: int
    base_rate_cents: int
    offsite_allowance: int
    term_start: str
    term_end: str
    status: str
    sessions_available: int
    sessions_reserved: int
    sessions_delivered: int
    offsite_sessions_used: int
    billed_amount_cents: int
    rate_tier: str
    created_at: str
    updated_at: str
    version: int


class RtsPlan(TypedDict):
    id: str
    athlete_id: str
    injury_record_id: str
    target_stage_count: int
    status: str
    current_stage: int
    stage_attempts: int
    total_failed_attempts: int
    active_stage_test_id: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClearanceDocument(TypedDict):
    id: str
    athlete_id: str
    document_type: str
    rts_plan_id: Optional[str]
    stage_number: Optional[int]
    expires_on: str
    status: str
    provider_license_id: Optional[str]
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
