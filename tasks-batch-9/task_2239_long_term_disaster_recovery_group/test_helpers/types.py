"""Domain types for the Long-Term Disaster Recovery Group API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

# --------------------------------------------------------------------------- roles


class UserRole(str, Enum):
    INTAKE_SPECIALIST = "IntakeSpecialist"
    CASE_MANAGER = "CaseManager"
    UNMET_NEEDS_CHAIR = "UnmetNeedsChair"
    MEMBER_ORG_DELEGATE = "MemberOrgDelegate"
    DISBURSEMENT_OFFICER = "DisbursementOfficer"
    CONSTRUCTION_MANAGER = "ConstructionManager"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    LTRG_ADMIN = "LTRGAdmin"


# ------------------------------------------------------------------- status enums


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    ASSESSED = "ASSESSED"
    PRESENTED = "PRESENTED"
    ACTIVE_RECOVERY = "ACTIVE_RECOVERY"
    CLOSURE_PENDING = "CLOSURE_PENDING"
    CLOSED = "CLOSED"
    INACTIVE = "INACTIVE"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    FULLY_COMMITTED = "FULLY_COMMITTED"
    DISBURSING = "DISBURSING"
    SATISFIED = "SATISFIED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class DamageCategory(str, Enum):
    STRUCTURE = "STRUCTURE"
    ROOF = "ROOF"
    HVAC = "HVAC"
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    CONTENTS = "CONTENTS"
    ACCESSIBILITY = "ACCESSIBILITY"


class PurposeCode(str, Enum):
    STRUCTURE_REPAIR = "STRUCTURE_REPAIR"
    CONTENTS_REPLACEMENT = "CONTENTS_REPLACEMENT"
    ACCESSIBILITY_MOD = "ACCESSIBILITY_MOD"
    TEMPORARY_HOUSING = "TEMPORARY_HOUSING"


class IncomeBand(str, Enum):
    ELI = "ELI"
    VLI = "VLI"
    LOW = "LOW"
    MODERATE = "MODERATE"
    ABOVE = "ABOVE"


class PrimaryResidenceStatus(str, Enum):
    OWNER_OCCUPIED = "OWNER_OCCUPIED"
    RENTER = "RENTER"
    MOBILE_HOME = "MOBILE_HOME"
    OTHER = "OTHER"


class AssistanceSourceType(str, Enum):
    INSURANCE_SETTLEMENT = "INSURANCE_SETTLEMENT"
    FEMA_IA = "FEMA_IA"
    SBA_LOAN = "SBA_LOAN"
    NONPROFIT_GRANT = "NONPROFIT_GRANT"
    STATE_PROGRAM = "STATE_PROGRAM"
    CROWDFUNDING = "CROWDFUNDING"
    OTHER = "OTHER"


class DocumentationStatus(str, Enum):
    UNDOCUMENTED = "UNDOCUMENTED"
    DOCUMENTED = "DOCUMENTED"
    DISPUTED = "DISPUTED"


class AssessmentVariant(str, Enum):
    PURPOSE_MATCHED = "PURPOSE_MATCHED"
    POOLED = "POOLED"


class MemberOrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CAPPED = "CAPPED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class MemberOrgType(str, Enum):
    FAITH_BASED = "FAITH_BASED"
    NONPROFIT = "NONPROFIT"
    GOVERNMENT = "GOVERNMENT"
    CIVIC_CLUB = "CIVIC_CLUB"
    FOUNDATION = "FOUNDATION"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    ADJOURNED = "ADJOURNED"
    CANCELLED = "CANCELLED"


class PresentationStatus(str, Enum):
    QUEUED = "QUEUED"
    PRESENTING = "PRESENTING"
    DELIBERATING = "DELIBERATING"
    AWARDED = "AWARDED"
    DEFERRED = "DEFERRED"
    DENIED = "DENIED"


class BridgeTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class DecisionBranch(str, Enum):
    AWARD = "AWARD"
    DEFER = "DEFER"
    DENY = "DENY"


class CommitmentStatus(str, Enum):
    PLEDGED = "PLEDGED"
    CONFIRMED = "CONFIRMED"
    DISBURSED = "DISBURSED"
    RESCINDED = "RESCINDED"


class RestrictionCode(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    STRUCTURE_REPAIR_ONLY = "STRUCTURE_REPAIR_ONLY"
    CONTENTS_ONLY = "CONTENTS_ONLY"
    ACCESSIBILITY_ONLY = "ACCESSIBILITY_ONLY"
    TEMPORARY_HOUSING_ONLY = "TEMPORARY_HOUSING_ONLY"
    MATERIALS_ONLY = "MATERIALS_ONLY"


class FundingSourceType(str, Enum):
    INDIVIDUAL_DONATION = "INDIVIDUAL_DONATION"
    FOUNDATION_GRANT = "FOUNDATION_GRANT"
    GOVERNMENT_GRANT = "GOVERNMENT_GRANT"
    IN_KIND_MATERIAL = "IN_KIND_MATERIAL"
    MEMBER_ORG_TRANSFER = "MEMBER_ORG_TRANSFER"


class FundingSourceStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class DisbursementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DOB_CLEARED = "DOB_CLEARED"
    DOB_FLAGGED = "DOB_FLAGGED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REVERSED = "REVERSED"
    VOIDED = "VOIDED"


class ProjectStatus(str, Enum):
    SCOPED = "SCOPED"
    PERMITTED = "PERMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    PUNCHLIST = "PUNCHLIST"
    CLOSED_OUT = "CLOSED_OUT"
    CANCELLED = "CANCELLED"


class ProjectAction(str, Enum):
    PERMIT = "PERMIT"
    START = "START"
    SUSPEND = "SUSPEND"
    RESUME = "RESUME"
    PUNCHLIST = "PUNCHLIST"
    CLOSE_OUT = "CLOSE_OUT"
    CANCEL = "CANCEL"


class ScopeCode(str, Enum):
    ROOF_REPLACEMENT = "ROOF_REPLACEMENT"
    STRUCTURE_REBUILD = "STRUCTURE_REBUILD"
    INTERIOR_REPAIR = "INTERIOR_REPAIR"
    ACCESSIBILITY_RAMP = "ACCESSIBILITY_RAMP"
    MECHANICAL_REPAIR = "MECHANICAL_REPAIR"


class TradeCode(str, Enum):
    FRAMING = "FRAMING"
    ROOFING = "ROOFING"
    DRYWALL = "DRYWALL"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    PAINTING = "PAINTING"
    GENERAL_LABOR = "GENERAL_LABOR"


class DeploymentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class DeploymentAction(str, Enum):
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"
    COMPLETE = "COMPLETE"


class HousingAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class LodgingSiteStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class ContactType(str, Enum):
    CHECK_IN_30_DAY = "CHECK_IN_30_DAY"
    CHECK_IN_90_DAY = "CHECK_IN_90_DAY"
    CLOSURE_REVIEW = "CLOSURE_REVIEW"
    ANNIVERSARY = "ANNIVERSARY"
    REFERRAL = "REFERRAL"


class ContactOutcome(str, Enum):
    REACHED = "REACHED"
    NO_ANSWER = "NO_ANSWER"
    DECLINED = "DECLINED"
    NEEDS_REOPENED = "NEEDS_REOPENED"


class SkillFitVariant(str, Enum):
    COVERAGE_WEIGHTED = "COVERAGE_WEIGHTED"
    HEADCOUNT_WEIGHTED = "HEADCOUNT_WEIGHTED"


# --------------------------------------------------------------- entity TypedDicts
# Resources carrying id + created_at + updated_at + version.


class Survivor(TypedDict):
    id: str
    household_name: str
    primary_contact_phone: str
    household_size: int
    income_band: str
    head_of_household_age: int
    has_member_with_disability: bool
    is_uninsured: bool
    consent_on_file: bool
    follow_up_opt_in: bool
    priority_score: int
    open_case_count: int
    created_at: str
    updated_at: str
    version: int


class RecoveryCase(TypedDict):
    id: str
    survivor_id: str
    disaster_code: str
    assigned_case_manager_user_id: str
    primary_residence_status: str
    temporary_housing_need_cents: int
    case_status: str
    funding_status: str
    verified_damage_total_cents: int
    reference_unmet_cents: int
    total_committed_cents: int
    total_net_disbursed_cents: int
    residual_unmet_cents: int
    closure_waiver_reason: Optional[str]
    reopen_count: int
    withdrawn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageItem(TypedDict):
    id: str
    case_id: str
    category: str
    item_description: str
    documented_cost_cents: int
    photo_count: int
    is_habitability_critical: bool
    verification_status: str
    verified_cost_cents: Optional[int]
    capped_cost_cents: int
    purpose_bucket: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssistanceRecord(TypedDict):
    id: str
    case_id: str
    source_type: str
    purpose_code: str
    awarded_cents: int
    received_on: str
    documentation_status: str
    is_excluded_from_dob: bool
    exclusion_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MemberOrganization(TypedDict):
    id: str
    org_name: str
    org_type: str
    contact_email: str
    annual_pledge_cap_cents: int
    status: str
    committed_cents: int
    disbursed_cents: int
    remaining_pledge_capacity_cents: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TableSession(TypedDict):
    id: str
    session_label: str
    scheduled_for: str
    quorum_min_member_orgs: int
    attending_member_org_ids: List[str]
    status: str
    chaired_by_user_id: Optional[str]
    awarded_total_cents: int
    queued_count: int
    created_at: str
    updated_at: str
    version: int


class CasePresentation(TypedDict):
    id: str
    case_id: str
    session_id: str
    assessment_id: str
    prepared_by_user_id: str
    narrative: str
    status: str
    queue_position: int
    priority_score_snapshot: int
    pledged_total_cents: int
    bridge_tier: Optional[str]
    bridge_authorized_cents: int
    awarded_cents: int
    shortfall_cents: int
    deferral_count: int
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingCommitment(TypedDict):
    id: str
    presentation_id: str
    member_org_id: str
    pledged_cents: int
    purpose_code: str
    status: str
    pledged_by_user_id: str
    rescission_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingSource(TypedDict):
    id: str
    label: str
    source_type: str
    restriction_code: str
    eligible_purpose_codes: List[str]
    restriction_specificity: int
    total_cents: int
    expires_on: Optional[str]
    admin_retention_allowed: bool
    committed_cents: int
    disbursed_cents: int
    admin_retained_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict):
    funding_source_id: str
    net_cents: int
    retention_cents: int
    gross_cents: int


class Disbursement(TypedDict):
    id: str
    case_id: str
    project_id: Optional[str]
    commitment_id: Optional[str]
    purpose_code: str
    requested_cents: int
    payee_name: str
    status: str
    dob_pool_cents: int
    dob_exposure_cents: int
    allocation_lines: List[AllocationLine]
    net_cents: int
    admin_retained_cents: int
    gross_cents: int
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    dob_resolution_note: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConstructionProject(TypedDict):
    id: str
    case_id: str
    predecessor_project_id: Optional[str]
    scope_code: str
    required_trade_hours: Dict[str, int]
    critical_trades: List[str]
    estimated_material_cents: int
    permit_number: Optional[str]
    status: str
    suspension_reason: Optional[str]
    volunteer_hours_logged: int
    confirmed_deployment_count: int
    created_at: str
    updated_at: str
    version: int


class VolunteerGroup(TypedDict):
    id: str
    group_name: str
    home_organization: str
    member_count: int
    skill_profile: Dict[str, int]
    requires_housing: bool
    brings_own_tools: bool
    active_deployment_count: int
    created_at: str
    updated_at: str
    version: int


class VolunteerDeployment(TypedDict):
    id: str
    group_id: str
    project_id: str
    arrival_date: str
    departure_date: str
    day_count: int
    crew_hours_committed: int
    skill_fit_score_bps: int
    status: str
    hours_logged: int
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LodgingSite(TypedDict):
    id: str
    site_name: str
    bed_capacity: int
    has_showers: bool
    nightly_cost_cents: int
    peak_committed_beds: int
    available_beds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HousingAssignment(TypedDict):
    id: str
    group_id: str
    lodging_site_id: str
    check_in_date: str
    check_out_date: str
    beds_requested: int
    night_count: int
    status: str
    released_at: Optional[str]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# The two immutable resource kinds carry ONLY id and created_at: no updated_at and
# no version, per the PRD's record-identity rules.


class UnmetNeedAssessment(TypedDict):
    id: str
    case_id: str
    variant: str
    verified_damage_total_cents: int
    total_documented_assistance_cents: int
    bucket_need_cents: Dict[str, int]
    bucket_offset_cents: Dict[str, int]
    unmet_need_total_cents: int
    prepared_by_user_id: str
    created_at: str


class FollowUpContact(TypedDict):
    id: str
    case_id: str
    contact_type: str
    contacted_on: str
    outcome: str
    notes: str
    recorded_by_user_id: str
    created_at: str


# ------------------------------------------------------------------ computed reads


class DobReport(TypedDict):
    case_id: str
    survivor_id: str
    purpose_code: str
    dob_pool_cents: int
    prior_disbursed_cents: int
    bucket_need_cents: int
    dob_exposure_cents: int
    sibling_case_ids: List[str]


class SkillFitReport(TypedDict):
    project_id: str
    group_id: str
    variant: str
    day_count: int
    weighted_covered: int
    weighted_required: int
    score_bps: int
    meets_minimum: bool


class ClockReading(TypedDict):
    current_utc: str
    expired_funding_source_ids: List[str]


JsonDict = Dict[str, Any]
