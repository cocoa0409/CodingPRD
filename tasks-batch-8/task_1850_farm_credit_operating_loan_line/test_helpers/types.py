"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    BORROWER = "Borrower"
    LOAN_OFFICER = "LoanOfficer"
    CREDIT_COMMITTEE = "CreditCommittee"
    INSURANCE_ADJUSTER = "InsuranceAdjuster"
    ASSOCIATION_BOARD = "AssociationBoard"
    SYSTEM = "System"


class BorrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LoanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    RESTRUCTURING = "RESTRUCTURING"
    PAID_OFF = "PAID_OFF"
    CHARGED_OFF = "CHARGED_OFF"
    FORECLOSED = "FORECLOSED"


class PaymentPosture(str, Enum):
    CURRENT = "CURRENT"
    WATCH = "WATCH"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"


class CropBudgetStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    ACTUALIZED = "ACTUALIZED"


class CollateralStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RELEASED = "RELEASED"


class CollateralType(str, Enum):
    CHATTEL_CROP = "CHATTEL_CROP"
    EQUIPMENT = "EQUIPMENT"
    REAL_ESTATE = "REAL_ESTATE"


class PerfectionState(str, Enum):
    PERFECTED = "PERFECTED"
    UNPERFECTED = "UNPERFECTED"


class UCCFilingStatus(str, Enum):
    FILED = "FILED"
    CONTINUED = "CONTINUED"
    LAPSED = "LAPSED"
    TERMINATED = "TERMINATED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class ClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    ADJUSTED = "ADJUSTED"
    APPROVED = "APPROVED"
    UNDER_APPEAL = "UNDER_APPEAL"
    PAID = "PAID"
    DENIED = "DENIED"


class DrawStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
    DISBURSED = "DISBURSED"
    RESCINDED = "RESCINDED"


class DrawPurpose(str, Enum):
    SEED = "SEED"
    FERTILIZER = "FERTILIZER"
    FUEL = "FUEL"
    LABOR = "LABOR"
    EQUIPMENT_REPAIR = "EQUIPMENT_REPAIR"
    LIVING_EXPENSE = "LIVING_EXPENSE"


class RepaymentStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class RepaymentSource(str, Enum):
    HARVEST_PROCEEDS = "HARVEST_PROCEEDS"
    INSURANCE_INDEMNITY = "INSURANCE_INDEMNITY"
    OTHER = "OTHER"


class CovenantOutcome(str, Enum):
    COMPLIANT = "COMPLIANT"
    BREACH = "BREACH"


class CovenantStatus(str, Enum):
    RECORDED = "RECORDED"
    WAIVED = "WAIVED"
    VOIDED = "VOIDED"


class PlanType(str, Enum):
    STANDARD = "STANDARD"
    DISASTER = "DISASTER"


class AmortizationStyle(str, Enum):
    EQUAL_INSTALLMENT = "EQUAL_INSTALLMENT"
    BALLOON = "BALLOON"


class PlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class DeferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    IN_EFFECT = "IN_EFFECT"
    EXPIRED = "EXPIRED"
    ENDED_EARLY = "ENDED_EARLY"


class DistributionStatus(str, Enum):
    DECLARED = "DECLARED"
    ALLOCATED = "ALLOCATED"
    PAID = "PAID"


class MarginCallStatus(str, Enum):
    ISSUED = "ISSUED"
    CURED = "CURED"
    ESCALATED = "ESCALATED"


# --- Entity TypedDicts (all entities carry the four common properties) ---

class Association(TypedDict):
    id: str
    name: str
    charter_number: str
    review_index: int
    active_disaster_declarations: List[Dict[str, Any]]
    current_fiscal_year: int
    created_at: str
    updated_at: str
    version: int


class Borrower(TypedDict):
    id: str
    association_id: str
    legal_name: str
    tax_id: str
    county: str
    status: str
    patronage_eligible: bool
    active_covenant_breach_count: int
    created_at: str
    updated_at: str
    version: int


class LoanAccount(TypedDict):
    id: str
    borrower_id: str
    association_id: str
    requested_commitment_cents: int
    approved_commitment_cents: Optional[int]
    rate_bps: int
    season_year: int
    maturity_date: str
    status: str
    payment_posture: str
    consecutive_delinquent_reviews: int
    outstanding_principal_cents: int
    accrued_interest_cents: int
    last_accrual_date: Optional[str]
    borrowing_base_cents: int
    pending_draw_cents: int
    created_at: str
    updated_at: str
    version: int


class CropBudget(TypedDict):
    id: str
    loan_account_id: str
    season_year: int
    crop_type: str
    acres: int
    projected_revenue_cents: int
    projected_expenses_cents: int
    actual_revenue_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Collateral(TypedDict):
    id: str
    loan_account_id: str
    collateral_type: str
    description: str
    appraised_value_cents: int
    prior_lien_cents: int
    status: str
    perfection_state: str
    created_at: str
    updated_at: str
    version: int


class UCCFiling(TypedDict):
    id: str
    collateral_id: str
    filing_number: str
    jurisdiction: str
    filed_date: str
    lapse_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    borrower_id: str
    assigned_loan_id: Optional[str]
    policy_number: str
    crop_type: str
    county: str
    coverage_start: str
    coverage_end: str
    coverage_amount_cents: int
    status: str
    assignment_status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict):
    id: str
    policy_id: str
    loan_account_id: str
    claimed_loss_cents: int
    adjuster_approved_cents: Optional[int]
    indemnity_to_lender_cents: Optional[int]
    applied_interest_cents: Optional[int]
    applied_principal_cents: Optional[int]
    remitted_to_borrower_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DrawRequest(TypedDict):
    id: str
    loan_account_id: str
    amount_cents: int
    purpose: str
    disbursement_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Repayment(TypedDict):
    id: str
    loan_account_id: str
    amount_cents: int
    source: str
    applied_interest_cents: int
    applied_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CovenantEvaluation(TypedDict):
    id: str
    loan_account_id: str
    borrower_id: str
    as_of_date: str
    current_assets_cents: int
    current_liabilities_cents: int
    working_capital_cents: int
    current_ratio_milli: int
    required_ratio_milli: int
    outcome: str
    recorded_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RestructurePlan(TypedDict):
    id: str
    loan_account_id: str
    plan_type: str
    amortization_style: str
    extension_months: int
    new_rate_bps: int
    capitalize_interest: bool
    base_balance_cents: int
    new_installment_cents: int
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeferralRequest(TypedDict):
    id: str
    loan_account_id: str
    disaster_ref: str
    requested_start: str
    requested_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PatronageDistribution(TypedDict):
    id: str
    association_id: str
    fiscal_year: int
    pool_cents: int
    allocated_cents: int
    undistributed_cents: int
    allocation_lines: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarginCallNotice(TypedDict):
    id: str
    loan_account_id: str
    deficiency_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
