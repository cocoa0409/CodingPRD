"""Status vocabularies and row shapes for the twelve persisted resource types.

All twelve resources carry ``id``, ``created_at``, ``updated_at`` and
``version``; no resource opts out of any of the four.
"""

from typing import Any, Dict, List, Optional, TypedDict


class Role:
    """The seven roles, spelled exactly as the PRD spells them."""

    PROGRAM_DIRECTOR = "ProgramDirector"
    INTAKE_SPECIALIST = "IntakeSpecialist"
    JOB_COACH = "JobCoach"
    CASE_MANAGER = "CaseManager"
    FUNDER_ANALYST = "FunderAnalyst"
    REFERRAL_PARTNER = "ReferralPartner"
    EMPLOYER_PARTNER = "EmployerPartner"


ALL_ROLES = (
    Role.PROGRAM_DIRECTOR,
    Role.INTAKE_SPECIALIST,
    Role.JOB_COACH,
    Role.CASE_MANAGER,
    Role.FUNDER_ANALYST,
    Role.REFERRAL_PARTNER,
    Role.EMPLOYER_PARTNER,
)

OPERATOR_ROLES = (
    Role.PROGRAM_DIRECTOR,
    Role.INTAKE_SPECIALIST,
    Role.JOB_COACH,
    Role.CASE_MANAGER,
    Role.FUNDER_ANALYST,
)

ENTITY_BACKED_ROLES = (Role.REFERRAL_PARTNER, Role.EMPLOYER_PARTNER)


class BusinessLineStatus:
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    LAUNCHED = "LAUNCHED"
    SUSPENDED = "SUSPENDED"


BUSINESS_LINE_STATUSES = (
    BusinessLineStatus.DRAFT,
    BusinessLineStatus.APPROVED,
    BusinessLineStatus.REJECTED,
    BusinessLineStatus.LAUNCHED,
    BusinessLineStatus.SUSPENDED,
)


class IntakePosture:
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MouStatus:
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


class MouTier:
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ReferralStatus:
    SUBMITTED = "SUBMITTED"
    WAITLISTED = "WAITLISTED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    ENROLLED = "ENROLLED"


REFERRAL_STATUSES = (
    ReferralStatus.SUBMITTED,
    ReferralStatus.WAITLISTED,
    ReferralStatus.ELIGIBLE,
    ReferralStatus.INELIGIBLE,
    ReferralStatus.ENROLLED,
)


class PriorityBand:
    BAND_A = "BAND_A"
    BAND_B = "BAND_B"
    BAND_C = "BAND_C"


class ScreeningDecision:
    ELIGIBLE = "ELIGIBLE"
    WAITLISTED = "WAITLISTED"
    INELIGIBLE = "INELIGIBLE"


class ReviewDecision:
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ParticipantStatus:
    TRANSITIONAL_EMPLOYED = "TRANSITIONAL_EMPLOYED"
    READY_FOR_GRADUATION = "READY_FOR_GRADUATION"
    GRADUATED = "GRADUATED"
    PLACED = "PLACED"
    RE_ENTRY_ELIGIBLE = "RE_ENTRY_ELIGIBLE"
    ALUMNI_RETAINED = "ALUMNI_RETAINED"
    EXITED_UNSUCCESSFUL = "EXITED_UNSUCCESSFUL"


PARTICIPANT_STATUSES = (
    ParticipantStatus.TRANSITIONAL_EMPLOYED,
    ParticipantStatus.READY_FOR_GRADUATION,
    ParticipantStatus.GRADUATED,
    ParticipantStatus.PLACED,
    ParticipantStatus.RE_ENTRY_ELIGIBLE,
    ParticipantStatus.ALUMNI_RETAINED,
    ParticipantStatus.EXITED_UNSUCCESSFUL,
)


class WorkShiftStatus:
    SCHEDULED = "SCHEDULED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CustomerServiceStandard:
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class ShiftAssignmentStatus:
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class ReleasedReason:
    MANUAL_RELEASE = "MANUAL_RELEASE"
    SHIFT_CANCELLED = "SHIFT_CANCELLED"
    PARTICIPANT_EXITED = "PARTICIPANT_EXITED"


class SupportActivityStatus:
    PLANNED = "PLANNED"
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"


class SupportCategory:
    JOB_COACHING = "JOB_COACHING"
    CASE_MANAGEMENT = "CASE_MANAGEMENT"
    TRANSPORT_VOUCHER = "TRANSPORT_VOUCHER"
    CHILDCARE_VOUCHER = "CHILDCARE_VOUCHER"


class PartnershipStatus:
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    TERMINATED = "TERMINATED"


class EmploymentStatus:
    ACTIVE = "ACTIVE"
    SEPARATED_VOLUNTARY = "SEPARATED_VOLUNTARY"
    SEPARATED_INVOLUNTARY = "SEPARATED_INVOLUNTARY"


class WageVerificationStatus:
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"


class WageVerificationAction:
    VERIFY = "VERIFY"
    DISPUTE = "DISPUTE"


class SeparationType:
    VOLUNTARY = "VOLUNTARY"
    INVOLUNTARY = "INVOLUNTARY"


class RetentionOutcome:
    PENDING = "PENDING"
    FAILED_EARLY = "FAILED_EARLY"
    FAILED_LATE = "FAILED_LATE"
    RETAINED_180 = "RETAINED_180"


class CheckpointStatus:
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    MISSED = "MISSED"
    VOIDED = "VOIDED"


class SubsidyPeriodStatus:
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AllocationBasis:
    HOURS = "HOURS"
    REVENUE = "REVENUE"


class CostCategory:
    TRAINEE_WAGES = "TRAINEE_WAGES"
    SUPERVISION = "SUPERVISION"
    MATERIALS = "MATERIALS"
    COACHING = "COACHING"
    SUPPORT_SERVICE = "SUPPORT_SERVICE"
    OVERHEAD = "OVERHEAD"


class CostClassification:
    MISSION = "MISSION"
    BUSINESS = "BUSINESS"
    SHARED = "SHARED"


class CostEntryStatus:
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class RetentionMeasure:
    COHORT_BASED = "COHORT_BASED"
    POINT_IN_TIME = "POINT_IN_TIME"


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class BusinessLine(CommonFields, total=False):
    name: str
    market_viability_score: int
    training_relevance_score: int
    mission_alignment_score: int
    composite_viability_score: float
    training_slots_total: int
    training_slots_filled: int
    supervisor_capacity: int
    target_gross_margin_pct: float
    subsidy_cap_cents: int
    cumulative_subsidy_cents: int
    quality_incident_count: int
    status: str
    intake_posture: str
    rejection_reason: Optional[str]
    launched_at: Optional[str]


class ReferralPartner(CommonFields, total=False):
    organization_name: str
    mou_tier: str
    mou_status: str
    referral_quota_per_period: int
    referrals_submitted_count: int
    enrolled_referral_count: int
    conversion_rate: Optional[float]


class Referral(CommonFields, total=False):
    referral_partner_id: str
    candidate_reference: str
    declared_barrier_codes: List[str]
    verified_barrier_codes: List[str]
    household_income_cents: int
    household_size: int
    hours_available_per_week: int
    fpl_ratio: Optional[float]
    eligibility_score: Optional[float]
    priority_band: Optional[str]
    status: str
    screened_at: Optional[str]
    decided_by_user_id: Optional[str]


class Participant(CommonFields, total=False):
    referral_id: str
    business_line_id: str
    wage_cents_per_hour: int
    max_transitional_weeks: int
    status: str
    enrolled_at: str
    transitional_hours_worked: float
    scheduled_hours_current_week: float
    support_activity_minutes: int
    delivered_coaching_count: int
    re_entry_count: int
    readiness_certified_by_user_id: Optional[str]
    readiness_certified_at: Optional[str]
    graduated_at: Optional[str]
    graduation_wage_cents_per_hour: Optional[int]
    eligible_re_entry_at: Optional[str]


class WorkShift(CommonFields, total=False):
    business_line_id: str
    starts_at: str
    ends_at: str
    duration_hours: float
    trainee_capacity: int
    assigned_count: int
    supervisor_user_id: str
    customer_service_standard: str
    status: str
    quality_defect_count: int
    customer_complaint_count: int
    billable_labor_cost_cents: Optional[int]


class ShiftAssignment(CommonFields, total=False):
    work_shift_id: str
    participant_id: str
    status: str
    actual_hours: Optional[float]
    wage_cost_cents: Optional[int]
    quality_defect_count: int
    customer_complaint_count: int
    released_reason: Optional[str]


class SupportActivity(CommonFields, total=False):
    participant_id: str
    category: str
    duration_minutes: int
    cost_cents: int
    status: str
    delivered_by_user_id: Optional[str]
    delivered_at: Optional[str]
    voided_reason: Optional[str]
    cost_entry_id: Optional[str]


class Employer(CommonFields, total=False):
    organization_name: str
    industry_code: str
    min_starting_wage_cents_per_hour: int
    partnership_status: str
    placement_count: int
    failed_retention_count: int
    confirmed_retention_count: int
    retention_reliability_pct: Optional[float]


class Placement(CommonFields, total=False):
    participant_id: str
    employer_id: str
    hire_date: str
    starting_wage_cents_per_hour: int
    weekly_hours: float
    employment_status: str
    wage_verification_status: str
    retention_outcome: str
    verified_wage_cents_per_hour: Optional[int]
    separation_date: Optional[str]
    separation_days_after_hire: Optional[int]
    wage_progression_pct: Optional[float]
    at_risk_flag: bool


class RetentionCheckpoint(CommonFields, total=False):
    placement_id: str
    interval_days: int
    due_date: str
    status: str
    still_employed: Optional[bool]
    verified_wage_cents_per_hour: Optional[int]
    confirmed_at: Optional[str]


class SubsidyPeriod(CommonFields, total=False):
    business_line_id: str
    period_start: str
    period_end: str
    supervisor_hours: float
    trainee_hours: float
    status: str
    allocation_basis: str
    revenue_cents: Optional[int]
    mission_share: float
    mission_cost_cents: int
    business_operating_cost_cents: int
    total_cost_cents: int
    true_cost_per_trainee_hour_cents: Optional[float]
    subsidy_per_trainee_hour_cents: Optional[float]
    margin_pct: Optional[float]
    subsidy_rate: Optional[float]
    subsidy_draw_cents: Optional[int]
    closed_at: Optional[str]


class CostEntry(CommonFields, total=False):
    subsidy_period_id: str
    category: str
    classification: str
    amount_cents: int
    allocated_mission_cents: int
    allocated_business_cents: int
    source_activity_id: Optional[str]
    status: str
    voided_at: Optional[str]


COMMON_FIELD_NAMES = ("id", "created_at", "updated_at", "version")

AnyRow = Dict[str, Any]
