"""Domain types: entity TypedDicts, status enums, role enum for the Problem Loan Workout API."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    WORKOUT_OFFICER = "WorkoutOfficer"
    SPECIAL_ASSETS_MANAGER = "SpecialAssetsManager"
    CREDIT_COMMITTEE = "CreditCommittee"
    APPRAISAL_DESK = "AppraisalDesk"
    LEGAL_COUNSEL = "LegalCounsel"
    LOAN_ACCOUNTING = "LoanAccounting"
    PORTFOLIO_ANALYST = "PortfolioAnalyst"
    SYSTEM_ADMIN = "SystemAdmin"


class BorrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXITED = "EXITED"


class LoanStatus(str, Enum):
    PERFORMING = "PERFORMING"
    WATCHLIST = "WATCHLIST"
    WORKOUT = "WORKOUT"
    FORECLOSURE = "FORECLOSURE"
    RESOLVED = "RESOLVED"


class WorkoutCaseStatus(str, Enum):
    WATCHLIST = "WATCHLIST"
    ACTION_PLAN = "ACTION_PLAN"
    NEGOTIATION = "NEGOTIATION"
    IMPAIRMENT_REVIEW = "IMPAIRMENT_REVIEW"
    LEGAL = "LEGAL"
    RESOLUTION = "RESOLUTION"
    CLOSED = "CLOSED"


class TdrStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    PENDING_EVALUATION = "PENDING_EVALUATION"
    TDR_CONFIRMED = "TDR_CONFIRMED"
    TDR_REJECTED = "TDR_REJECTED"


class ResolutionPath(str, Enum):
    NONE = "NONE"
    FORECLOSURE = "FORECLOSURE"
    DEED_IN_LIEU = "DEED_IN_LIEU"
    NOTE_SALE = "NOTE_SALE"
    RETURN_TO_PERFORMING = "RETURN_TO_PERFORMING"


class ActionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_BORROWER_REVIEW = "UNDER_BORROWER_REVIEW"
    COUNTERED = "COUNTERED"
    RESUBMITTED = "RESUBMITTED"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    APPROVED = "APPROVED"
    CONSUMMATED = "CONSUMMATED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class CollateralStatus(str, Enum):
    PLEDGED = "PLEDGED"
    UNDER_REVALUATION = "UNDER_REVALUATION"
    RELEASED = "RELEASED"
    LIQUIDATED = "LIQUIDATED"


class AppraisalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ImpairmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class ReferralStatus(str, Enum):
    PENDING_COUNSEL = "PENDING_COUNSEL"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    DISMISSED = "DISMISSED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Borrower(TypedDict, total=False):
    id: str
    legal_name: str
    tax_id: str
    naics_code: str
    internal_risk_rating: int
    guarantor_name: str
    guarantor_net_worth_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    borrower_id: str
    loan_number: str
    original_principal_cents: int
    current_principal_cents: int
    contractual_rate_bps: int
    days_past_due: int
    is_tdr: bool
    nonaccrual: bool
    charged_off_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkoutCase(TypedDict, total=False):
    id: str
    loan_id: str
    entry_trigger: str
    risk_rating_at_entry: int
    case_officer_id: str
    loss_given_default_cents: int
    impairment_reserve_cents: int
    tdr_status: str
    unapplied_cash_cents: int
    resolution_path: str
    status: str
    version_anchor: int
    created_at: str
    updated_at: str
    version: int


class ActionPlan(TypedDict, total=False):
    id: str
    case_id: str
    plan_text: str
    target_resolution_date: str
    milestone_count: int
    supersedes_plan_id: str
    approval_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RestructureProposal(TypedDict, total=False):
    id: str
    case_id: str
    proposal_kind: str
    concession_rate_bps: int
    term_extension_months: int
    principal_forgiveness_cents: int
    borrower_concession_cents: int
    tdr_flag: bool
    negotiation_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CollateralItem(TypedDict, total=False):
    id: str
    loan_id: str
    collateral_type: str
    description: str
    liquidation_discount_bps: int
    current_appraised_value_cents: int
    current_liquidation_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CollateralAppraisal(TypedDict, total=False):
    id: str
    collateral_id: str
    appraised_value_cents: int
    effective_date: str
    appraiser_id: str
    staleness_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpairmentAssessment(TypedDict, total=False):
    id: str
    case_id: str
    method: str
    probability_of_default_bps: int
    loss_given_default_bps: int
    expected_cash_flows: List[Any]
    computed_reserve_cents: int
    is_active: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LegalReferral(TypedDict, total=False):
    id: str
    case_id: str
    referral_kind: str
    target_guarantor_name: str
    demand_amount_cents: int
    statute_deadline: str
    decision_rationale: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger records (common_fields: false): id + created_at only ---

class ChargeOffEvent(TypedDict, total=False):
    id: str
    created_at: str
    case_id: str
    amount_cents: int
    reason_code: str
    booked_at: str
    is_partial: bool


class RecoveryEvent(TypedDict, total=False):
    id: str
    created_at: str
    case_id: str
    amount_cents: int
    recovery_source: str
    allocation_mode: str
    booked_at: str


class ExitStrategyDecision(TypedDict, total=False):
    id: str
    created_at: str
    case_id: str
    chosen_path: str
    npv_foreclosure_cents: int
    npv_deed_in_lieu_cents: int
    decision_rule_outcome: str
    override_justification: str
    decided_at: str
