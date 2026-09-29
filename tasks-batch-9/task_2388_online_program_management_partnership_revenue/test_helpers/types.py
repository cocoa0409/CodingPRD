"""Typed shapes for every resource the API exposes, transcribed from the PRD.

The PRD (2.4) splits resources into two families. Nine resources carry the full
identity set of `id`, `created_at`, `updated_at` and `version`. The tuition
ledger entry and the marketing ledger entry are append-only facts and carry only
`id` and `created_at` -- their TypedDicts deliberately omit `updated_at` and
`version`.
"""

from __future__ import annotations

from typing import List, Literal, Optional, TypedDict

# --- Enumerations ---------------------------------------------------------

PartnershipStatus = Literal["DRAFT", "UNDER_REVIEW", "EXECUTED", "WIND_DOWN", "CLOSED_OUT"]
ContractStructure = Literal["REVENUE_SHARE", "FEE_FOR_SERVICE"]
RecognitionMethod = Literal["PERIOD_STRAIGHT_LINE", "MILESTONE_CHRONOLOGICAL"]
ContractAction = Literal["SUBMIT_FOR_REVIEW", "REQUEST_CHANGES", "EXECUTE", "WIND_DOWN", "CLOSE_OUT"]

ProgramStatus = Literal[
    "DRAFT",
    "SUBMITTED",
    "REVISION_REQUESTED",
    "APPROVED",
    "REJECTED",
    "LAUNCHED",
    "SUSPENDED",
    "TEACH_OUT",
    "CLOSED",
]
ProgramLifecycleAction = Literal[
    "SUBMIT",
    "REQUEST_REVISION",
    "APPROVE",
    "REJECT",
    "LAUNCH",
    "SUSPEND",
    "RESUME",
    "BEGIN_TEACH_OUT",
    "CLOSE",
]
DeliveryModality = Literal["ASYNCHRONOUS", "SYNCHRONOUS", "HYBRID"]
CredentialLevel = Literal["CERTIFICATE", "BACHELORS", "MASTERS", "DOCTORATE"]

CourseDesignStatus = Literal[
    "NOT_STARTED", "IN_DESIGN", "FACULTY_REVIEW", "APPROVED", "RETIRED", "DESIGN_SUSPENDED"
]
CourseDesignAction = Literal[
    "START_DESIGN", "SUBMIT_FOR_FACULTY_REVIEW", "REQUEST_REVISION", "APPROVE", "RETIRE"
]
ContentOwner = Literal["UNIVERSITY", "PARTNER", "JOINT"]

ServiceDomain = Literal[
    "MARKETING",
    "LEAD_GENERATION",
    "ENROLLMENT_COUNSELING",
    "COURSE_DESIGN",
    "FACULTY_TRAINING",
    "TECH_PLATFORM",
    "STUDENT_ADVISING",
    "TUTORING",
    "RETENTION_OUTREACH",
    "CAREER_SERVICES",
    "ACCESSIBILITY_ACCOMMODATIONS",
    "FIELD_PLACEMENT",
]
ResponsibleParty = Literal["UNIVERSITY", "PARTNER"]

PerformanceStatus = Literal[
    "NOT_RATED", "MEETS_STANDARD", "WATCH", "PROBATION", "INACTIVE_PENDING_REVIEW"
]
IncentiveEligibility = Literal[
    "PENDING_COMPLIANCE_REVIEW", "ELIGIBLE", "SUSPENDED", "PROHIBITED_PLAN_ON_FILE"
]
# The two prohibited request-only plan shapes are never persisted (PRD 3.5).
CompPlanType = Literal[
    "NONE_ON_FILE",
    "FIXED_SALARY",
    "SALARY_PLUS_QUALITATIVE",
    "GRADUATION_MILESTONE",
    "PER_ENROLLMENT_COMMISSION",
    "PER_APPLICATION_BOUNTY",
]
VariableBasis = Literal[
    "NONE",
    "QUALITATIVE_MULTI_FACTOR",
    "GRADUATION_COUNT",
    "ENROLLMENT_COUNT",
    "APPLICATION_COUNT",
]
ComplianceDecision = Literal["APPROVE", "SUSPEND", "REJECT_PLAN"]

LeadStatus = Literal["NEW", "CONTACTED", "APPLIED", "ENROLLED", "DISQUALIFIED"]
LeadAdvanceAction = Literal["CONTACT", "APPLY", "DISQUALIFY"]
SourceChannel = Literal["PAID_SEARCH", "PAID_SOCIAL", "ORGANIC", "EMPLOYER_REFERRAL", "LIST_PURCHASE"]
DisqualificationReason = Literal[
    "NOT_QUALIFIED", "UNREACHABLE", "WITHDREW_INTEREST", "PROGRAM_TEACH_OUT"
]

EnrollmentStatus = Literal["ENROLLED", "ACTIVE", "COMPLETED", "WITHDRAWN"]
AcademicAction = Literal["RECORD_PROGRESS", "COMPLETE", "WITHDRAW"]

TuitionEntryType = Literal["PAYMENT", "REFUND"]
TuitionGeneratedBy = Literal["BURSAR_POST", "WITHDRAWAL_REFUND"]

MarketingEntryType = Literal["SPEND", "CREDIT_MEMO"]
MarketingChannel = Literal["PAID_SEARCH", "PAID_SOCIAL", "DISPLAY", "EVENTS", "LIST_PURCHASE"]

StatementStatus = Literal[
    "CALCULATED", "UNIVERSITY_APPROVED", "DISPUTED", "RESOLVED_ADJUSTED", "STALE", "REMITTED"
]
StatementAction = Literal["APPROVE", "DISPUTE", "RESOLVE", "REMIT", "RECALCULATE"]

TeachOutPlanStatus = Literal["DRAFT", "CERTIFIED", "SUPERSEDED"]
AssetTransferScope = Literal[
    "NONE", "COURSE_CONTENT_ONLY", "COURSE_CONTENT_AND_LEAD_DATA", "FULL_PLATFORM"
]


# --- Resources carrying the full identity set (PRD 2.4) ------------------


class Partnership(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    university_name: str
    university_ipeds_id: str
    partner_org_name: str
    contract_structure: ContractStructure
    term_months: int
    effective_date: str
    expiry_date: str
    revenue_recognition_method: RecognitionMethod
    marketing_budget_cents: int
    revenue_share_tiers: List[dict]
    refund_schedule: List[dict]
    exclusivity_cip_codes: List[str]
    bundled_services_exception_claimed: bool
    fee_schedule_monthly_cents: int
    status: PartnershipStatus
    change_request_count: int
    executed_date: Optional[str]
    wind_down_effective_date: Optional[str]
    collected_tuition_cents: int
    recognized_revenue_cents: int
    contract_year_recognized_cents: int
    remitted_to_partner_cents: int
    holdback_balance_cents: int
    unrecouped_marketing_spend_cents: int
    marketing_budget_remaining_cents: int


class Program(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    partnership_id: str
    program_name: str
    cip_code: str
    delivery_modality: DeliveryModality
    credential_level: CredentialLevel
    tuition_per_credit_cents: int
    credits_to_complete: int
    enrollment_cap: int
    projected_annual_enrollments: int
    competitor_program_count: int
    regional_wage_premium_pct: float
    employer_partner_count: int
    prior_year_inquiry_volume: int
    required_service_domains: List[ServiceDomain]
    launch_window_start: str
    launch_window_end: str
    status: ProgramStatus
    revision_round: int
    demand_score_screening: float
    demand_score_confirmed: float
    active_enrollment_count: int
    total_enrollment_count: int
    recognized_revenue_cents: int
    marketing_spend_net_cents: int
    blended_cac_cents: Optional[int]
    launched_at: Optional[str]
    teach_out_started_at: Optional[str]
    closed_at: Optional[str]


class Course(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    course_code: str
    title: str
    credits: int
    content_owner: ContentOwner
    design_cost_cents: int
    required_for_launch: bool
    ip_license_grant_back: bool
    prerequisite_course_id: Optional[str]
    design_status: CourseDesignStatus
    revision_round: int
    faculty_approver_name: Optional[str]


class ServiceScopeAssignment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    service_domain: ServiceDomain
    responsible_party: ResponsibleParty
    sla_response_hours: int
    cost_bearer: ResponsibleParty


class EnrollmentCounselor(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    partnership_id: str
    full_name: str
    employer: ResponsibleParty
    monthly_base_salary_cents: int
    comp_plan_type: CompPlanType
    annual_base_cents: int
    variable_component_cents: int
    variable_basis: VariableBasis
    performance_status: PerformanceStatus
    incentive_eligibility: IncentiveEligibility
    conversion_rate: float
    open_pipeline_count: int
    rated_lead_count: int
    enrolled_lead_count: int
    sla_breach_count: int
    clawback_pending_cents: int
    last_review_user_id: Optional[str]


class Lead(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    counselor_id: str
    source_channel: SourceChannel
    prospect_external_id: str
    status: LeadStatus
    hours_to_first_contact: Optional[int]
    qualified_at: Optional[str]
    disqualification_reason: Optional[DisqualificationReason]


class Enrollment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    lead_id: str
    student_external_id: str
    credits_enrolled: int
    credits_completed: int
    term_start_date: str
    term_end_date: str
    status: EnrollmentStatus
    tuition_per_credit_snapshot_cents: int
    tuition_charged_cents: int
    collected_cents: int
    refunded_cents: int
    recognized_to_date_cents: int
    withdrawal_date: Optional[str]
    refund_pct_applied: Optional[float]
    days_elapsed_at_withdrawal: Optional[int]


class RemittanceStatement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    partnership_id: str
    period_start: str
    period_end: str
    status: StatementStatus
    recognition_method_applied: RecognitionMethod
    line_count: int
    recognized_revenue_cents: int
    share_gross_cents: int
    marketing_recoupment_cents: int
    subtotal_cents: int
    holdback_pct: float
    holdback_cents: int
    fee_for_service_cents: int
    net_payable_cents: int
    adjustment_delta_cents: int
    requires_recalculation: bool
    authored_by_user_id: str
    approved_by_user_id: Optional[str]
    resolved_by_user_id: Optional[str]
    dispute_reason: Optional[str]
    remittance_reference: Optional[str]
    remitted_at: Optional[str]


class TeachOutPlan(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    teach_out_end_date: str
    student_notification_date: str
    asset_transfer_scope: AssetTransferScope
    partner_obligation_note: Optional[str]
    status: TeachOutPlanStatus
    affected_enrollment_count: int
    remaining_credit_count: int
    teach_out_cost_cents: int
    holdback_applied_cents: int
    partner_obligation_cents: int
    university_residual_cents: int
    transferred_asset_value_cents: int
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]


# --- Append-only ledger resources: `id` and `created_at` only (PRD 2.4) --


class TuitionPayment(TypedDict, total=False):
    id: str
    created_at: str
    enrollment_id: str
    entry_type: TuitionEntryType
    amount_cents: int
    posted_date: str
    reference_note: Optional[str]
    generated_by: TuitionGeneratedBy


class MarketingSpendEntry(TypedDict, total=False):
    id: str
    created_at: str
    program_id: str
    entry_type: MarketingEntryType
    channel: MarketingChannel
    amount_cents: int
    spend_date: str
    reversal_note: Optional[str]
