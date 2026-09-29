"""Domain types for the Transplant Living Donor Program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    TRANSPLANT_COORDINATOR = "TransplantCoordinator"
    DONOR_ADVOCATE = "DonorAdvocate"
    EVALUATION_REVIEWER = "EvaluationReviewer"
    QUALITY_OFFICER = "QualityOfficer"
    FINANCE_ADMIN = "FinanceAdmin"


class StaffRole(str, Enum):
    TRANSPLANT_COORDINATOR = "TRANSPLANT_COORDINATOR"
    LIVING_DONOR_ADVOCATE = "LIVING_DONOR_ADVOCATE"
    EVALUATION_REVIEWER = "EVALUATION_REVIEWER"
    QUALITY_OFFICER = "QUALITY_OFFICER"
    SURGEON = "SURGEON"


class OrganType(str, Enum):
    KIDNEY = "KIDNEY"
    LIVER = "LIVER"


class AboBloodType(str, Enum):
    O = "O"
    A = "A"
    B = "B"
    AB = "AB"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ListingStatus(str, Enum):
    WORKUP = "WORKUP"
    APPROVED_NOT_LISTED = "APPROVED_NOT_LISTED"
    DECLINED = "DECLINED"
    ACTIVE = "ACTIVE"
    INACTIVE_HOLD = "INACTIVE_HOLD"
    REMOVED = "REMOVED"
    TRANSPLANTED = "TRANSPLANTED"


class AdvocacyStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    DISCLOSED = "DISCLOSED"
    ATTESTED = "ATTESTED"
    OBJECTED = "OBJECTED"


class ClinicalStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    EXCLUDED = "EXCLUDED"
    DEFERRED = "DEFERRED"


class DonorOverallStatus(str, Enum):
    REFERRED = "REFERRED"
    EVAL_IN_PROGRESS = "EVAL_IN_PROGRESS"
    APPROVED = "APPROVED"
    CONDITIONAL_APPROVED = "CONDITIONAL_APPROVED"
    EXCLUDED = "EXCLUDED"
    ADVOCATE_BLOCKED = "ADVOCATE_BLOCKED"
    CHAIN_COMMITTED = "CHAIN_COMMITTED"
    DONATED = "DONATED"


class EvaluationDomain(str, Enum):
    MEDICAL = "MEDICAL"
    PSYCHOSOCIAL = "PSYCHOSOCIAL"


class EvaluationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    EXCLUDED = "EXCLUDED"
    DEFERRED = "DEFERRED"


class EvaluationOutcome(str, Enum):
    CLEARED = "CLEARED"
    EXCLUDED = "EXCLUDED"
    DEFERRED = "DEFERRED"


class ExclusionCode(str, Enum):
    EX_BMI_TOO_HIGH = "EX_BMI_TOO_HIGH"
    EX_RENAL_FUNCTION_LOW = "EX_RENAL_FUNCTION_LOW"
    EX_HYPERTENSION = "EX_HYPERTENSION"
    EX_DIABETES_RANGE = "EX_DIABETES_RANGE"
    EX_UNDERAGE = "EX_UNDERAGE"
    EX_COERCION_SUSPECTED = "EX_COERCION_SUSPECTED"
    EX_SUBSTANCE_USE = "EX_SUBSTANCE_USE"
    EX_CAPACITY_ABSENT = "EX_CAPACITY_ABSENT"


class ChainType(str, Enum):
    PAIRED_LOOP = "PAIRED_LOOP"
    NDD_CHAIN = "NDD_CHAIN"


class ChainStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    SUSPENDED = "SUSPENDED"
    COMMITTED = "COMMITTED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    BROKEN = "BROKEN"


class SegmentStatus(str, Enum):
    PLANNED = "PLANNED"
    OFFER_SENT = "OFFER_SENT"
    DECLINED = "DECLINED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"
    TRANSPLANTED = "TRANSPLANTED"


class BookingRole(str, Enum):
    DONOR_RECOVERY = "DONOR_RECOVERY"
    RECIPIENT_IMPLANT = "RECIPIENT_IMPLANT"


class BookingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class FollowUpIntervalCode(str, Enum):
    SIX_MONTH = "SIX_MONTH"
    ONE_YEAR = "ONE_YEAR"
    TWO_YEAR = "TWO_YEAR"


class FollowUpStatus(str, Enum):
    DUE = "DUE"
    SUBMITTED_COMPLETE = "SUBMITTED_COMPLETE"
    INCOMPLETE = "INCOMPLETE"
    DELINQUENT = "DELINQUENT"
    WAIVED = "WAIVED"


class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class FlagLevel(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    FLAGGED = "FLAGGED"


class PlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class PlanAction(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    CLOSE = "CLOSE"


class ClaimType(str, Enum):
    MEDICAL = "MEDICAL"
    TRAVEL = "TRAVEL"
    LOST_WAGES = "LOST_WAGES"


class CoverageSource(str, Enum):
    RECIPIENT_INSURANCE = "RECIPIENT_INSURANCE"
    NLDAC_GRANT = "NLDAC_GRANT"
    PROGRAM_FUND = "PROGRAM_FUND"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


class TransplantProgram(TypedDict):
    id: str
    name: str
    center_code: str
    organ_type: str
    cooling_off_days: int
    follow_up_completeness_threshold_pct: float
    follow_up_compliance_threshold_pct: float
    expected_one_year_survival_rate: float
    donor_fund_pool_cents: int
    lost_wage_daily_cap_cents: int
    lost_wage_weekly_cap_cents: int
    donor_fund_committed_cents: int
    donor_fund_remaining_cents: int
    follow_up_compliance_pct: float
    cit_breach_count: int
    compliance_posture: str
    last_sweep_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    program_id: str
    full_name: str
    staff_role: str
    npi: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class RecipientCandidate(TypedDict):
    id: str
    program_id: str
    mrn: str
    abo_blood_type: str
    age_years: int
    cpra: float
    dialysis_years: float
    medical_urgency_points: int
    listing_status: str
    candidacy_approved_by_staff_id: Optional[str]
    registered_at: Optional[str]
    active_days_total: int
    waitlist_priority_score: float
    offer_decline_count: int
    created_at: str
    updated_at: str
    version: int


class WaitlistStatusEvent(TypedDict):
    """A waitlist event is an immutable audit record: it carries only id and created_at."""
    id: str
    recipient_candidate_id: str
    from_status: Optional[str]
    to_status: str
    reason_code: str
    effective_at: str
    actor_user_id: str
    created_at: str


class DonorCandidate(TypedDict):
    id: str
    program_id: str
    intended_recipient_id: Optional[str]
    referred_by_staff_id: str
    advocate_staff_id: Optional[str]
    mrn: str
    abo_blood_type: str
    age_years: int
    advocacy_status: str
    disclosure_at: Optional[str]
    disclosure_sequence: int
    cooling_off_ends_at: Optional[str]
    attestation_at: Optional[str]
    objection_reason_code: Optional[str]
    medical_status: str
    psychosocial_status: str
    medical_risk_points: int
    psychosocial_risk_points: int
    deferral_count: int
    screening_risk_index: float
    final_risk_index: Optional[float]
    overall_status: str
    donated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonorEvaluation(TypedDict):
    id: str
    donor_candidate_id: str
    reviewer_staff_id: str
    domain: str
    status: str
    bmi: Optional[float]
    egfr_ml_min: Optional[float]
    systolic_bp: Optional[int]
    hba1c: Optional[float]
    coercion_flag: Optional[bool]
    unmanaged_substance_use: Optional[bool]
    decisional_capacity_ok: Optional[bool]
    financial_hardship_score: Optional[int]
    social_support_score: Optional[int]
    exclusion_codes: List[str]
    hard_exclusion_count: int
    risk_points: int
    submission_count: int
    determined_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExchangeChain(TypedDict):
    id: str
    program_id: str
    chain_type: str
    status: str
    segment_count: int
    is_closed_loop: bool
    total_planned_cit_minutes: int
    committed_donor_count: int
    validated_at: Optional[str]
    committed_at: Optional[str]
    break_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChainSegment(TypedDict):
    id: str
    exchange_chain_id: str
    position: int
    donor_candidate_id: str
    recipient_candidate_id: str
    predecessor_segment_id: Optional[str]
    status: str
    planned_cross_clamp_at: Optional[str]
    planned_reperfusion_at: Optional[str]
    planned_transport_minutes: Optional[int]
    offer_sent_at: Optional[str]
    offer_response_deadline_at: Optional[str]
    offer_responded_at: Optional[str]
    decline_reason_code: Optional[str]
    planned_cit_minutes: Optional[int]
    actual_cross_clamp_at: Optional[str]
    actual_reperfusion_at: Optional[str]
    actual_cit_minutes: Optional[int]
    cit_breach: bool
    created_at: str
    updated_at: str
    version: int


class OperatingRoom(TypedDict):
    id: str
    program_id: str
    room_code: str
    turnover_buffer_minutes: int
    reserved_minutes_total: int
    created_at: str
    updated_at: str
    version: int


class ProcedureBooking(TypedDict):
    id: str
    operating_room_id: str
    chain_segment_id: str
    surgeon_staff_id: str
    booking_role: str
    start_at: str
    end_at: str
    status: str
    duration_minutes: int
    cancel_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonorFollowUp(TypedDict):
    id: str
    donor_candidate_id: str
    interval_code: str
    due_on: str
    required_fields_count: int
    submitted_field_count: int
    completeness_pct: float
    status: str
    submitted_at: Optional[str]
    waiver_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramOutcomeReview(TypedDict):
    id: str
    program_id: str
    period_start_on: str
    period_end_on: str
    cohort_size: int
    observed_survivor_count: int
    expected_survival_rate_used: float
    expected_survivor_count: float
    oe_ratio: Optional[float]
    flag_level: str
    requires_improvement_plan: bool
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImprovementPlan(TypedDict):
    id: str
    program_outcome_review_id: str
    title: str
    milestone_count: int
    target_completion_on: str
    status: str
    decision_reason_code: Optional[str]
    decided_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonorCostClaim(TypedDict):
    id: str
    donor_candidate_id: str
    claim_type: str
    coverage_source: str
    submitted_amount_cents: int
    lost_wage_days: Optional[int]
    service_from_on: str
    service_to_on: str
    estimated_reimbursement_cents: int
    adjudicated_reimbursement_cents: Optional[int]
    insurance_part_cents: int
    grant_part_cents: int
    fund_part_cents: int
    unfunded_cents: Optional[int]
    status: str
    adjudicated_at: Optional[str]
    adjudicated_by_user_id: Optional[str]
    reversal_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int
