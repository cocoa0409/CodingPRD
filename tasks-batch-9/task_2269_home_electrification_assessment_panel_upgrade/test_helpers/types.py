"""Domain enums and resource shapes for the Home Electrification Rebates API.

Enumerated values and field sets are taken from the PRD: the role list of §2.1,
the audit-field contract of §2.4, and the entity descriptions of §3.1-§3.9.

Per §2.4, `Program`, `MeasureCatalogItem`, `Household`, `IncomeVerification`,
`Contractor`, `Assessment`, `RebateProject`, `ProjectMeasure`, `Reservation`,
`StackingDeclaration` and `Inspection` carry `id`, `created_at`, `updated_at`
and `version`, while `Inspector`, `EligibleMeasure` and `ClawbackAction` are
append-only rows carrying only `id` and `created_at`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles (§2.1)
# --------------------------------------------------------------------------- #


class UserRole:
    APPLICANT = "Applicant"
    CONTRACTOR = "Contractor"
    FIELD_INSPECTOR = "FieldInspector"
    PROGRAM_REVIEWER = "ProgramReviewer"
    PROGRAM_ADMIN = "ProgramAdmin"

    ALL = [
        APPLICANT,
        CONTRACTOR,
        FIELD_INSPECTOR,
        PROGRAM_REVIEWER,
        PROGRAM_ADMIN,
    ]


# --------------------------------------------------------------------------- #
# Status enumerations
# --------------------------------------------------------------------------- #


class ProgramStatus:
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MeasureCategory:
    HVAC = "HVAC"
    WATER_HEATING = "WATER_HEATING"
    APPLIANCE = "APPLIANCE"
    ENVELOPE = "ENVELOPE"
    ELECTRICAL_INFRASTRUCTURE = "ELECTRICAL_INFRASTRUCTURE"


class CombinedCapGroup:
    HVAC_GROUP = "HVAC_GROUP"
    WATER_GROUP = "WATER_GROUP"
    APPLIANCE_GROUP = "APPLIANCE_GROUP"
    ELECTRICAL_GROUP = "ELECTRICAL_GROUP"
    NONE = "NONE"

    #  §3.5 Stage 2 takes the groups in this fixed order.
    PRORATION_ORDER = [HVAC_GROUP, WATER_GROUP, APPLIANCE_GROUP, ELECTRICAL_GROUP]


class IncomeTier:
    LOW = "LOW"
    MODERATE = "MODERATE"
    STANDARD = "STANDARD"


class IncomeVerificationStatus:
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class IncomeVerificationDecision:
    VERIFY = "VERIFY"
    REJECT = "REJECT"


class ContractorStatus:
    PENDING_ENROLLMENT = "PENDING_ENROLLMENT"
    ENROLLED_ACTIVE = "ENROLLED_ACTIVE"
    SUSPENDED = "SUSPENDED"
    ENROLLMENT_REJECTED = "ENROLLMENT_REJECTED"


class EnrollmentDecision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class SuspensionAction:
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


class SuspensionReason:
    ADMIN_ACTION = "ADMIN_ACTION"
    QUALITY_SCORE = "QUALITY_SCORE"


class AssessmentStatus:
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class AssessmentDecision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class DisqualificationReason:
    RETIRED_CATALOG_ITEM = "RETIRED_CATALOG_ITEM"
    TIER_INELIGIBLE = "TIER_INELIGIBLE"
    PANEL_CAPACITY_INSUFFICIENT = "PANEL_CAPACITY_INSUFFICIENT"
    ANCHOR_MISSING = "ANCHOR_MISSING"
    PREREQUISITE_MISSING = "PREREQUISITE_MISSING"


class ProjectStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    INCOMPLETE = "INCOMPLETE"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    RESERVED = "RESERVED"
    CONTRACTOR_HOLD = "CONTRACTOR_HOLD"
    INSTALLED = "INSTALLED"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    REMEDIATION = "REMEDIATION"
    VERIFIED = "VERIFIED"
    PAID = "PAID"
    EXPIRED = "EXPIRED"
    FAILED_FINAL = "FAILED_FINAL"
    CLAWED_BACK = "CLAWED_BACK"


class ProjectReviewDecision:
    APPROVE = "APPROVE"
    RETURN_INCOMPLETE = "RETURN_INCOMPLETE"
    REJECT = "REJECT"


class InstallStatus:
    PLANNED = "PLANNED"
    INSTALLED = "INSTALLED"
    VOID = "VOID"


class VerificationStatus:
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    CLAWED_BACK = "CLAWED_BACK"


class LineRejectionReason:
    INSPECTION_DEFICIENCY = "INSPECTION_DEFICIENCY"
    ANCHOR_REJECTED = "ANCHOR_REJECTED"


class ReservationStatus:
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"
    CLAWED_BACK = "CLAWED_BACK"


class ReleaseReason:
    EXPIRY = "EXPIRY"
    FAILED_REINSPECTION = "FAILED_REINSPECTION"
    CLAWBACK = "CLAWBACK"


class StackingDeclarationStatus:
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class InspectionType:
    SPOT = "SPOT"
    POST_INSTALL = "POST_INSTALL"


class InspectionStatus:
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InspectionResult:
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class ClawbackReason:
    FAILED_REINSPECTION = "FAILED_REINSPECTION"
    POST_PAYMENT_INSPECTION_FAILURE = "POST_PAYMENT_INSPECTION_FAILURE"


class QuoteVariant:
    PROVISIONAL = "provisional"
    FINAL = "final"


# --------------------------------------------------------------------------- #
# Resource shapes — full audit set (§2.4)
# --------------------------------------------------------------------------- #


class Program(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    state_code: str
    status: str
    program_year: int
    budget_total_cents: int
    budget_available_cents: int
    budget_reserved_cents: int
    budget_committed_cents: int
    budget_clawed_back_cents: int
    reservation_ttl_days: int
    extension_window_days: int
    max_extension_days: int
    max_extensions_per_reservation: int
    low_tier_cap_cents: int
    moderate_tier_cap_cents: int
    standard_tier_cap_cents: int
    low_tier_cost_share_pct: float
    moderate_tier_cost_share_pct: float
    standard_tier_cost_share_pct: float
    ami_low_threshold_pct: float
    ami_moderate_threshold_pct: float
    group_cap_cents: int
    panel_upgrade_cap_cents: int
    federal_credit_pct: float
    federal_credit_cap_cents: int
    max_combined_benefit_pct: float
    max_remediations_per_project: int
    quality_suspension_threshold: int
    recertification_threshold: int
    status_note: Optional[str]


class MeasureCatalogItem(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    measure_code: str
    measure_name: str
    category: str
    unit_incentive_cents: int
    measure_cap_cents: int
    max_quantity: int
    combined_cap_group: str
    sort_order: int
    required_panel_capacity_amps: int
    upgraded_capacity_amps: int
    is_panel_upgrade: bool
    requires_qualifying_appliance: bool
    qualifies_as_appliance_anchor: bool
    prerequisite_measure_code: Optional[str]
    standard_tier_eligible: bool
    active: bool
    retirement_note: Optional[str]


class Household(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    applicant_name: str
    email: str
    service_address_line1: str
    county_code: str
    utility_territory_code: str
    household_size: int
    existing_panel_amps: int
    ami_percent: Optional[float]
    income_tier: Optional[str]
    rebate_cap_cents: int
    lifetime_cap_remaining_cents: int
    encumbered_cents: int


class IncomeVerification(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    status: str
    annual_household_income_cents: int
    county_median_income_cents: int
    household_size_attested: int
    document_reference: Optional[str]
    computed_ami_percent: Optional[float]
    assigned_income_tier: Optional[str]
    assigned_cap_cents: int
    submitted_by_user_id: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    reviewer_notes: Optional[str]


class Contractor(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    program_id: str
    business_name: str
    license_number: str
    license_expires_on: str
    insurance_expires_on: str
    crew_capacity: int
    status: str
    quality_score_rolling: int
    completed_inspection_count: int
    suspension_reason: Optional[str]
    enrollment_decided_by_user_id: Optional[str]
    decision_notes: Optional[str]


class Assessment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    contractor_id: str
    status: str
    assessed_panel_amps: int
    effective_panel_amps: int
    qualified_measure_count: int
    estimated_total_incentive_cents: int
    assessment_notes: Optional[str]
    approved_by_user_id: Optional[str]
    review_notes: Optional[str]


class RebateProject(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    household_id: str
    assessment_id: str
    contractor_id: str
    income_verification_id: str
    status: str
    estimated_project_cost_cents: int
    actual_project_cost_cents: Optional[int]
    provisional_total_incentive_cents: int
    final_total_incentive_cents: Optional[int]
    stacking_adjusted_state_incentive_cents: Optional[int]
    disbursed_amount_cents: int
    submission_count: int
    remediation_count: int
    conditional_pass_flag: bool
    install_start_date: Optional[str]
    install_end_date: Optional[str]
    installed_panel_amps: Optional[int]
    reviewed_by_user_id: Optional[str]
    review_notes: Optional[str]
    incomplete_reason: Optional[str]


class ProjectMeasure(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    measure_code: str
    planned_quantity: int
    estimated_cost_cents: int
    verified_quantity: Optional[int]
    actual_cost_cents: Optional[int]
    install_status: str
    verification_status: str
    rejection_reason: Optional[str]
    provisional_incentive_cents: int
    final_incentive_cents: Optional[int]
    pinned_unit_incentive_cents: int
    pinned_measure_cap_cents: int
    pinned_max_quantity: int
    pinned_sort_order: int
    pinned_combined_cap_group: str
    pinned_is_panel_upgrade: bool


class Reservation(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    program_id: str
    status: str
    reserved_amount_cents: int
    initial_reserved_amount_cents: int
    reserved_at: str
    expires_at: str
    extension_count: int
    extension_days_granted: int
    committed_at: Optional[str]
    release_reason: Optional[str]
    reservation_notes: Optional[str]


class StackingDeclaration(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    status: str
    utility_program_name: str
    utility_rebate_cents: int
    federal_credit_claimed_cents: Optional[int]
    computed_state_incentive_before_cents: int
    combined_benefit_limit_cents: int
    allowed_state_incentive_cents: int
    allowed_federal_credit_cents: int
    residual_overage_cents: int


class Inspection(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    inspector_id: str
    inspection_type: str
    status: str
    scheduled_start: str
    scheduled_end: str
    scheduled_by_user_id: str
    result_recorded_at: Optional[str]
    recorded_by_user_id: Optional[str]
    deficiency_count: int
    deficiency_severity_max: int
    rejected_measure_codes: List[str]
    notes: Optional[str]
    cancellation_reason: Optional[str]


# --------------------------------------------------------------------------- #
# Resource shapes — append-only rows carrying only id and created_at (§2.4)
# --------------------------------------------------------------------------- #


class Inspector(TypedDict, total=False):
    id: str
    created_at: str
    program_id: str
    inspector_name: str
    certification_id: str
    certification_expires_on: Optional[str]


class EligibleMeasure(TypedDict, total=False):
    id: str
    created_at: str
    assessment_id: str
    measure_code: str
    proposed_quantity: int
    estimated_cost_cents: int
    evaluation_order: int
    qualified: bool
    disqualification_reason: Optional[str]
    estimated_incentive_cents: int


class ClawbackAction(TypedDict, total=False):
    id: str
    created_at: str
    project_id: str
    reservation_id: str
    triggered_by_inspection_id: str
    reason: str
    disbursed_before_cents: int
    recovered_cents: int
    released_reservation_cents: int
    program_budget_available_after_cents: int
    household_cap_remaining_after_cents: int
    recorded_by_user_id: str


# --------------------------------------------------------------------------- #
# Computed-read shapes
# --------------------------------------------------------------------------- #


class IncentiveQuoteLine(TypedDict, total=False):
    measure_code: str
    raw_incentive_cents: int
    cost_share_cap_cents: int
    capped_line_cents: int
    allocated_cents: int


class IncentiveQuote(TypedDict, total=False):
    project_id: str
    variant: str
    lines: List[IncentiveQuoteLine]
    group_capped_total_cents: int
    household_cap_limit_cents: int
    total_incentive_cents: int
    group_cap_applied: bool
    household_cap_applied: bool
    residual_cents_assigned_to_measure_code: Optional[str]


class QualityReview(TypedDict, total=False):
    contractor_id: str
    rolling_window_score: int
    severity_weighted_score: int
    rolling_window_inspection_count: int
    weighted_inspection_count: int
    suspension_threshold: int
    recertification_threshold: int
    recertification_eligible: bool


class SweepResult(TypedDict, total=False):
    program_id: str
    swept_reservation_count: int
    released_cents: int
    expired_project_ids: List[str]
    program_budget_available_cents: int


class ClockState(TypedDict, total=False):
    current_utc: str
    previous_utc: str


JsonDict = Dict[str, Any]

__all__ = [
    "UserRole",
    "ProgramStatus",
    "MeasureCategory",
    "CombinedCapGroup",
    "IncomeTier",
    "IncomeVerificationStatus",
    "IncomeVerificationDecision",
    "ContractorStatus",
    "EnrollmentDecision",
    "SuspensionAction",
    "SuspensionReason",
    "AssessmentStatus",
    "AssessmentDecision",
    "DisqualificationReason",
    "ProjectStatus",
    "ProjectReviewDecision",
    "InstallStatus",
    "VerificationStatus",
    "LineRejectionReason",
    "ReservationStatus",
    "ReleaseReason",
    "StackingDeclarationStatus",
    "InspectionType",
    "InspectionStatus",
    "InspectionResult",
    "ClawbackReason",
    "QuoteVariant",
    "Program",
    "MeasureCatalogItem",
    "Household",
    "IncomeVerification",
    "Contractor",
    "Assessment",
    "RebateProject",
    "ProjectMeasure",
    "Reservation",
    "StackingDeclaration",
    "Inspection",
    "Inspector",
    "EligibleMeasure",
    "ClawbackAction",
    "IncentiveQuoteLine",
    "IncentiveQuote",
    "QualityReview",
    "SweepResult",
    "ClockState",
    "JsonDict",
]
