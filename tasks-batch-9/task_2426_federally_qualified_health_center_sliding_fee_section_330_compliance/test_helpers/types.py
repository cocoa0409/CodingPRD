"""Domain types for the FQHC Sliding Fee & Section 330 Compliance API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BOARD_CHAIR = "BoardChair"
    ELIGIBILITY_VERIFIER = "EligibilityVerifier"
    PATIENT_SERVICES_REP = "PatientServicesRep"
    BILLING_SPECIALIST = "BillingSpecialist"
    PROJECT_OFFICER = "ProjectOfficer"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class OperationalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONDITIONS_IMPOSED = "CONDITIONS_IMPOSED"


class ScopePosture(str, Enum):
    OPEN = "OPEN"
    CHANGE_FROZEN = "CHANGE_FROZEN"


class GovernancePosture(str, Enum):
    GOVERNANCE_COMPLIANT = "GOVERNANCE_COMPLIANT"
    GOVERNANCE_DEFICIENT = "GOVERNANCE_DEFICIENT"


class BoardMemberStatus(str, Enum):
    SEATED = "SEATED"
    RESIGNED = "RESIGNED"


class SeatType(str, Enum):
    PATIENT = "PATIENT"
    NON_PATIENT = "NON_PATIENT"


class ExpertiseCategory(str, Enum):
    FINANCE = "FINANCE"
    LEGAL = "LEGAL"
    COMMUNITY = "COMMUNITY"
    HEALTH_PROFESSION = "HEALTH_PROFESSION"


class ServiceSiteStatus(str, Enum):
    PROPOSED = "PROPOSED"
    IN_SCOPE = "IN_SCOPE"
    ON_HOLD = "ON_HOLD"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class SiteType(str, Enum):
    SERVICE_DELIVERY = "SERVICE_DELIVERY"
    INTERMITTENT = "INTERMITTENT"
    ADMINISTRATIVE = "ADMINISTRATIVE"


class HoldReason(str, Enum):
    SCOPE_FROZEN = "SCOPE_FROZEN"


class ServiceDefinitionStatus(str, Enum):
    PENDING = "PENDING"
    IN_SCOPE = "IN_SCOPE"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class ServiceCategory(str, Enum):
    REQUIRED_PRIMARY = "REQUIRED_PRIMARY"
    ADDITIONAL = "ADDITIONAL"


class DeliveryMethod(str, Enum):
    COLUMN_I_DIRECT = "COLUMN_I_DIRECT"
    COLUMN_II_CONTRACT = "COLUMN_II_CONTRACT"
    COLUMN_III_REFERRAL = "COLUMN_III_REFERRAL"


class ScopeChangeRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    HELD = "HELD"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ScopeChangeRequestType(str, Enum):
    ADD_SITE = "ADD_SITE"
    REMOVE_SITE = "REMOVE_SITE"
    ADD_SERVICE = "ADD_SERVICE"
    REMOVE_SERVICE = "REMOVE_SERVICE"


class ScopeDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"
    DENY = "DENY"


class FeeScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class ReviewStatus(str, Enum):
    CURRENT = "CURRENT"
    REVIEW_DUE = "REVIEW_DUE"
    OUT_OF_DATE = "OUT_OF_DATE"


class DiscountKind(str, Enum):
    NOMINAL = "NOMINAL"
    PERCENT_DISCOUNT = "PERCENT_DISCOUNT"
    NONE = "NONE"


class SlidingFeeStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class IncomeVerificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    INSUFFICIENT_DOCUMENTATION = "INSUFFICIENT_DOCUMENTATION"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class DocumentationType(str, Enum):
    TAX_RETURN = "TAX_RETURN"
    PAY_STUBS = "PAY_STUBS"
    W2 = "W2"
    SELF_DECLARATION = "SELF_DECLARATION"
    REFUSED = "REFUSED"


class VerificationDecision(str, Enum):
    VERIFY = "VERIFY"
    MARK_INSUFFICIENT = "MARK_INSUFFICIENT"


class PpsClaimStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    PAID = "PAID"
    PENDING_ADJUSTMENT = "PENDING_ADJUSTMENT"
    RECONCILED = "RECONCILED"
    VOID = "VOID"


class WraparoundStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    REBILL_REQUIRED = "REBILL_REQUIRED"
    RECEIVED = "RECEIVED"


class PayerType(str, Enum):
    SELF_PAY = "SELF_PAY"
    MEDICAID_MCO = "MEDICAID_MCO"
    MEDICAID_FFS = "MEDICAID_FFS"
    MEDICARE = "MEDICARE"
    PRIVATE = "PRIVATE"


class ChargeBasis(str, Enum):
    SLIDING_FEE_TIER = "SLIDING_FEE_TIER"
    FULL_CHARGE_UNVERIFIED = "FULL_CHARGE_UNVERIFIED"
    THIRD_PARTY = "THIRD_PARTY"


class VoidReason(str, Enum):
    DUPLICATE = "DUPLICATE"
    CODING_ERROR = "CODING_ERROR"
    NONPAYMENT = "NONPAYMENT"
    SITE_OUT_OF_SCOPE = "SITE_OUT_OF_SCOPE"


class WaiverStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class WaiverReason(str, Enum):
    HOMELESS = "HOMELESS"
    NO_INCOME = "NO_INCOME"
    HARDSHIP_ATTESTATION = "HARDSHIP_ATTESTATION"


class WaiverDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class UDSReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class UDSReportDecision(str, Enum):
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class InclusionStatus(str, Enum):
    INCLUDED = "INCLUDED"
    EXCLUDED_ZERO_DENOMINATOR = "EXCLUDED_ZERO_DENOMINATOR"


class SiteVisitFindingStatus(str, Enum):
    OPEN = "OPEN"
    CAP_SUBMITTED = "CAP_SUBMITTED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class Severity(str, Enum):
    CONDITION = "CONDITION"
    PROGRESS_REPORT_ONLY = "PROGRESS_REPORT_ONLY"


class CorrectiveActionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class CapDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


# ---------------------------------------------------------------------------
# Entity shapes
#
# Every resource below is a mutable, versioned record carrying
# id / created_at / updated_at / version — except PovertyGuideline, which is
# immutable and carries only id and created_at (PRD §2.4).
# ---------------------------------------------------------------------------


class HealthCenter(TypedDict):
    id: str
    legal_name: str
    grant_number: str
    pps_base_rate_cents: int
    medicare_upper_limit_cents: int
    nominal_fee_cap_cents: int
    scope_baseline_locked: bool
    operational_status: str
    scope_posture: str
    open_condition_count: int
    in_scope_site_count: int
    in_scope_service_count: int
    seated_board_count: int
    patient_seat_pct: float
    governance_posture: str
    wraparound_receivable_cents: int
    created_at: str
    updated_at: str
    version: int


class PovertyGuideline(TypedDict):
    """Immutable guideline year — carries only id and created_at."""

    id: str
    guideline_year: int
    base_amount_cents: int
    increment_cents: int
    created_at: str


class BoardMember(TypedDict):
    id: str
    health_center_id: str
    seat_number: int
    seat_type: str
    patient_id: Optional[str]
    expertise_category: Optional[str]
    derives_over_10pct_income_from_healthcare: bool
    term_start: str
    term_end: str
    status: str
    resignation_date: Optional[str]
    patient_seat_qualified: bool
    created_at: str
    updated_at: str
    version: int


class ServiceSite(TypedDict):
    id: str
    health_center_id: str
    site_name: str
    site_type: str
    address_line: str
    weekly_service_hours: int
    status: str
    in_scope_since: Optional[str]
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceDefinition(TypedDict):
    id: str
    health_center_id: str
    service_code: str
    service_category: str
    delivery_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScopeChangeRequest(TypedDict):
    id: str
    health_center_id: str
    target_site_id: Optional[str]
    target_service_definition_id: Optional[str]
    request_type: str
    justification: str
    status: str
    revision_round: int
    held_from_status: Optional[str]
    prepared_by_user_id: str
    reviewed_by_user_id: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeSchedule(TypedDict):
    id: str
    health_center_id: str
    fpg_year: int
    effective_start: str
    effective_end: str
    nominal_fee_cents: int
    status: str
    board_vote_date: Optional[str]
    adopted_at: Optional[str]
    adopted_by_user_id: Optional[str]
    last_reviewed_at: Optional[str]
    reviewed_against_guideline_year: Optional[int]
    review_status: str
    superseded_by_fee_schedule_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiscountTier(TypedDict):
    id: str
    fee_schedule_id: str
    tier_label: str
    fpg_min_pct: float
    fpg_max_pct: Optional[float]
    discount_kind: str
    discount_pct: Optional[float]
    sort_order: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    mrn: str
    full_name: str
    household_size: int
    sliding_fee_status: str
    patient_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class IncomeVerification(TypedDict):
    id: str
    patient_id: str
    declared_annual_income_cents: int
    household_size: int
    documentation_type: str
    effective_date: str
    expires_at: str
    status: str
    resubmit_round: int
    submitted_by_user_id: str
    verified_by_user_id: Optional[str]
    insufficiency_reason: Optional[str]
    guideline_year_used: Optional[int]
    fpg_percent: Optional[float]
    uds_guideline_year_used: Optional[int]
    uds_fpg_percent: Optional[float]
    assigned_discount_tier_id: Optional[str]
    assigned_tier_label: Optional[str]
    supersedes_income_verification_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict):
    id: str
    patient_id: str
    service_site_id: str
    service_definition_id: str
    fee_schedule_id: str
    income_verification_id: Optional[str]
    pinned_discount_tier_id: Optional[str]
    encounter_date: str
    payer_type: str
    gross_charge_cents: int
    patient_charge_cents: int
    charge_basis: str
    sliding_fee_applied: bool
    charge_adjustment_cents: int
    waived_amount_cents: int
    pps_encounter_rate_cents: int
    mco_paid_cents: int
    wraparound_due_cents: int
    pps_claim_status: str
    wraparound_status: str
    claim_reference: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InabilityToPayWaiver(TypedDict):
    id: str
    encounter_id: str
    waiver_reason: str
    status: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    waived_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class UDSReport(TypedDict):
    id: str
    health_center_id: str
    reporting_year: int
    status: str
    total_patient_count: int
    patients_at_or_below_100_count: int
    patients_101_to_150_count: int
    patients_151_to_200_count: int
    patients_over_200_count: int
    unverified_patient_count: int
    composite_quality_rate_pct: Optional[float]
    included_measure_count: int
    computed_at: Optional[str]
    submitted_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    return_reason: Optional[str]
    return_round: int
    created_at: str
    updated_at: str
    version: int


class QualityMeasureResult(TypedDict):
    id: str
    uds_report_id: str
    measure_code: str
    numerator: int
    denominator: int
    benchmark_pct: float
    rate_pct: Optional[float]
    inclusion_status: str
    meets_benchmark: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class SiteVisitFinding(TypedDict):
    id: str
    health_center_id: str
    service_site_id: Optional[str]
    requirement_code: str
    severity: str
    finding_summary: str
    cap_due_days: int
    cap_due_at: str
    status: str
    escalated_at: Optional[str]
    issued_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict):
    id: str
    site_visit_finding_id: str
    narrative: str
    milestone_count: int
    target_completion_date: str
    status: str
    submit_round: int
    prepared_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GovernanceSummary(TypedDict):
    """Read-only summary exposing every intermediate the majority test uses."""

    health_center_id: str
    seated_board_count: int
    qualified_patient_seat_count: int
    non_patient_seat_count: int
    healthcare_industry_seat_count: int
    patient_seat_pct: float
    governance_posture: str
    version: int
