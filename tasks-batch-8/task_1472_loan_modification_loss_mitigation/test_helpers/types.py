"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    SERVICING_ADMIN = "ServicingAdmin"
    BORROWER = "Borrower"
    LOSS_MIT_AGENT = "LossMitAgent"
    UNDERWRITER = "Underwriter"
    APPEAL_REVIEWER = "AppealReviewer"
    SERVICING_OPS = "ServicingOps"
    FORECLOSURE_COUNSEL = "ForeclosureCounsel"


class BorrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"


class WorkoutStatus(str, Enum):
    PERFORMING = "PERFORMING"
    DELINQUENT = "DELINQUENT"
    LOSS_MIT_REVIEW = "LOSS_MIT_REVIEW"
    TRIAL = "TRIAL"
    MOD_PENDING = "MOD_PENDING"
    PERMANENTLY_MODIFIED = "PERMANENTLY_MODIFIED"


class ForeclosureStatus(str, Enum):
    NONE = "NONE"
    REFERRED = "REFERRED"
    SALE_SCHEDULED = "SALE_SCHEDULED"
    SALE_HOLD = "SALE_HOLD"
    SALE_COMPLETED = "SALE_COMPLETED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    COMPLETE_PACKAGE = "COMPLETE_PACKAGE"
    EVALUATED_OFFER = "EVALUATED_OFFER"
    EVALUATED_DENIAL = "EVALUATED_DENIAL"
    APPEAL_REVIEW = "APPEAL_REVIEW"
    TRIAL_ACTIVE = "TRIAL_ACTIVE"
    TRIAL_PASSED = "TRIAL_PASSED"
    APPROVED = "APPROVED"
    CLOSED_DENIED = "CLOSED_DENIED"
    WITHDRAWN = "WITHDRAWN"


class HardshipType(str, Enum):
    UNEMPLOYMENT = "UNEMPLOYMENT"
    INCOME_REDUCTION = "INCOME_REDUCTION"
    MEDICAL = "MEDICAL"
    DIVORCE = "DIVORCE"
    DISASTER = "DISASTER"
    OTHER = "OTHER"


class DocType(str, Enum):
    PAYSTUB = "PAYSTUB"
    TAX_RETURN = "TAX_RETURN"
    PROFIT_LOSS = "PROFIT_LOSS"
    BANK_STATEMENT = "BANK_STATEMENT"
    HARDSHIP_AFFIDAVIT = "HARDSHIP_AFFIDAVIT"


class DocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PayFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    SEMIMONTHLY = "SEMIMONTHLY"
    MONTHLY = "MONTHLY"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EvaluationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class EvaluationResult(str, Enum):
    OFFER = "OFFER"
    DENIAL = "DENIAL"


class TrialPlanStatus(str, Enum):
    OFFERED = "OFFERED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TrialPaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID_ON_TIME = "PAID_ON_TIME"
    PAID_LATE = "PAID_LATE"
    PAID_INSUFFICIENT = "PAID_INSUFFICIENT"
    MISSED = "MISSED"


class ModificationStatus(str, Enum):
    DRAFT = "DRAFT"
    DOCS_SENT = "DOCS_SENT"
    SIGNED = "SIGNED"
    RECORDED = "RECORDED"
    RESCINDED = "RESCINDED"


class DenialNoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    APPEALED = "APPEALED"
    SUPERSEDED = "SUPERSEDED"
    AFFIRMED = "AFFIRMED"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AFFIRMED = "AFFIRMED"
    OVERTURNED = "OVERTURNED"


class ForeclosureCaseStatus(str, Enum):
    REFERRED = "REFERRED"
    SALE_SCHEDULED = "SALE_SCHEDULED"
    SALE_HOLD = "SALE_HOLD"
    SALE_COMPLETED = "SALE_COMPLETED"
    CANCELLED = "CANCELLED"


class EscrowAnalysisType(str, Enum):
    STANDARD_ANNUAL = "STANDARD_ANNUAL"
    POST_MODIFICATION = "POST_MODIFICATION"


class EscrowAnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"
    CANCELLED = "CANCELLED"


class DenialReason(str, Enum):
    NO_ELIGIBLE_PROGRAM = "NO_ELIGIBLE_PROGRAM"
    TARGET_NOT_ACHIEVABLE = "TARGET_NOT_ACHIEVABLE"
    INCOME_UNVERIFIABLE = "INCOME_UNVERIFIABLE"
    TRIAL_PLAN_FAILED = "TRIAL_PLAN_FAILED"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Entities with full common fields carry id + created_at + updated_at + version.
# EvaluationStepResult is the single exception: only id + created_at (PRD §2.4).
# ---------------------------------------------------------------------------


class Borrower(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    mailing_address: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    borrower_id: str
    loan_number: str
    property_state_code: str
    unpaid_principal_balance_cents: int
    interest_rate_bp: int
    remaining_term_months: int
    arrears_cents: int
    suspense_cents: int
    deferred_principal_cents: int
    escrow_balance_cents: int
    escrow_monthly_cents: int
    current_pi_cents: int
    delinquency_days: int
    workout_status: str
    foreclosure_status: str
    created_at: str
    updated_at: str
    version: int


class LossMitApplication(TypedDict, total=False):
    id: str
    loan_id: str
    hardship_type: str
    stated_monthly_income_cents: int
    status: str
    verified_monthly_income_cents: int
    outstanding_doc_categories: List[str]
    completed_at: Optional[str]
    acknowledgement_due_at: str
    acknowledged_at: Optional[str]
    evaluation_deadline: Optional[str]
    active_evaluation_id: Optional[str]
    superseded_by_application_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackageDocument(TypedDict, total=False):
    id: str
    application_id: str
    doc_type: str
    status: str
    gross_per_period_cents: Optional[int]
    pay_frequency: Optional[str]
    pay_period_end_date: Optional[str]
    annual_gross_cents: Optional[int]
    ytd_net_income_cents: Optional[int]
    ytd_months: Optional[int]
    rejection_reason: Optional[str]
    received_at: str
    created_at: str
    updated_at: str
    version: int


class ProgramOption(TypedDict, total=False):
    id: str
    code: str
    waterfall_rank: int
    target_dti_bp: int
    rate_floor_bp: int
    rate_step_bp: int
    max_term_months: int
    max_forbearance_pct_bp: int
    min_delinquency_days: int
    max_delinquency_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WaterfallEvaluation(TypedDict, total=False):
    id: str
    application_id: str
    underwriter_user_id: str
    evaluated_at: str
    status: str
    result: str
    selected_program_id: Optional[str]
    denial_reasons: List[str]
    eval_base_cents: Optional[int]
    target_payment_cents: Optional[int]
    offered_rate_bp: Optional[int]
    offered_term_months: Optional[int]
    offered_forbearance_cents: Optional[int]
    offered_pi_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EvaluationStepResult(TypedDict, total=False):
    # Append-only snapshot: carries ONLY id + created_at (no updated_at/version).
    id: str
    evaluation_id: str
    program_code: str
    step_rank: int
    eligible: bool
    achieved_pi_cents: Optional[int]
    met_target: Optional[bool]
    selected: bool
    created_at: str


class TrialPaymentPlan(TypedDict, total=False):
    id: str
    application_id: str
    evaluation_id: str
    program_code: str
    trial_payment_cents: int
    periods: int
    first_due_date: str
    offer_deadline: str
    accepted_at: Optional[str]
    suspense_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TrialPayment(TypedDict, total=False):
    id: str
    trial_plan_id: str
    period_index: int
    due_date: str
    scheduled_amount_cents: int
    received_amount_cents: Optional[int]
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PermanentModification(TypedDict, total=False):
    id: str
    application_id: str
    trial_plan_id: str
    final_base_cents: int
    final_rate_bp: int
    final_term_months: int
    final_forbearance_cents: int
    final_pi_cents: int
    capitalized_arrears_cents: int
    prior_terms_snapshot: Dict[str, Any]
    status: str
    recorded_at: Optional[str]
    rescission_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DenialNotice(TypedDict, total=False):
    id: str
    application_id: str
    evaluation_id: Optional[str]
    underwriter_user_id: str
    reasons: List[str]
    issued_at: str
    appeal_deadline: str
    appeal_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    denial_notice_id: str
    grounds: str
    submitted_at: str
    reviewer_user_id: Optional[str]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ForeclosureCase(TypedDict, total=False):
    id: str
    loan_id: str
    county: str
    docket_number: str
    referred_at: str
    sale_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EscrowAnalysis(TypedDict, total=False):
    id: str
    loan_id: str
    modification_id: Optional[str]
    analysis_type: str
    comp_year_start_month: str
    comp_year_months: int
    projected_annual_disbursements_cents: int
    cushion_cents: int
    balance_at_analysis_cents: int
    shortage_cents: int
    surplus_cents: int
    monthly_spread_cents: int
    spread_last_month_cents: int
    new_monthly_escrow_cents: int
    refund_cents: int
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
