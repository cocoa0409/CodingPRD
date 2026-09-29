"""Domain types for the Fix-Flip Hard Money Lending API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD
names them. Append-only journals (ledger entries, interest accrual periods,
exit milestones) carry only `id` and `created_at` — PRD §2.7 states that
`updated_at` and `version` are absent from those three record types.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    BORROWER = "Borrower"
    CONTRACTOR = "Contractor"
    LOAN_OFFICER = "LoanOfficer"
    CREDIT_COMMITTEE = "CreditCommittee"
    LOAN_SERVICER = "LoanServicer"
    DRAW_INSPECTOR = "DrawInspector"
    PLATFORM_ADMIN = "PlatformAdmin"


class EntityType(str, Enum):
    LLC = "LLC"
    CORP = "CORP"
    LP = "LP"
    SOLE_PROP = "SOLE_PROP"


class BorrowerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    APPROVED_SPONSOR = "APPROVED_SPONSOR"
    SUSPENDED = "SUSPENDED"


class GuaranteeStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"


class ExperienceTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"
    TIER_D = "TIER_D"


class SuspensionReason(str, Enum):
    RECERT_BELOW_FLOOR = "RECERT_BELOW_FLOOR"
    ADMIN_SUSPENSION = "ADMIN_SUSPENSION"
    LOAN_DEFAULT = "LOAN_DEFAULT"


class BorrowerAction(str, Enum):
    APPROVE_SPONSOR = "APPROVE_SPONSOR"
    RECERTIFY = "RECERTIFY"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


class PropertyStatus(str, Enum):
    UNDER_CONTRACT = "UNDER_CONTRACT"
    BORROWER_OWNED = "BORROWER_OWNED"
    LENDER_REO = "LENDER_REO"
    SOLD = "SOLD"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SIZED = "SIZED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class RehabLineItemStatus(str, Enum):
    PROPOSED = "PROPOSED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOID = "VOID"
    FULLY_RELEASED = "FULLY_RELEASED"


class ScopeCode(str, Enum):
    ROOF = "ROOF"
    KITCHEN = "KITCHEN"
    BATH = "BATH"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    HVAC = "HVAC"
    FOUNDATION = "FOUNDATION"
    EXTERIOR = "EXTERIOR"
    FLOORING = "FLOORING"
    PERMITS = "PERMITS"
    CONTINGENCY = "CONTINGENCY"


class ScopeDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"


class DayCountConvention(str, Enum):
    PER_DIEM_360 = "PER_DIEM_360"
    PER_DIEM_365 = "PER_DIEM_365"


class LoanPaymentStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"
    PAID_OFF = "PAID_OFF"
    CHARGED_OFF = "CHARGED_OFF"


class LoanConstructionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    LENDER_COMPLETING = "LENDER_COMPLETING"
    LENDER_COMPLETE = "LENDER_COMPLETE"


class LoanExitStatus(str, Enum):
    NOT_LISTED = "NOT_LISTED"
    LISTED = "LISTED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    REFI_IN_PROCESS = "REFI_IN_PROCESS"
    EXITED = "EXITED"
    FORECLOSED = "FORECLOSED"


class DrawRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INSPECTION_ORDERED = "INSPECTION_ORDERED"
    INSPECTED = "INSPECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    FUNDED = "FUNDED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    SUSPENDED = "SUSPENDED"


class VerificationMethod(str, Enum):
    INSPECTION = "INSPECTION"
    PHOTO = "PHOTO"


class InspectionVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DrawDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"
    REJECT = "REJECT"


class WaiverType(str, Enum):
    PARTIAL_CONDITIONAL = "PARTIAL_CONDITIONAL"
    PARTIAL_UNCONDITIONAL = "PARTIAL_UNCONDITIONAL"
    FINAL_UNCONDITIONAL = "FINAL_UNCONDITIONAL"


class LienWaiverStatus(str, Enum):
    COLLECTED = "COLLECTED"
    DISPUTED = "DISPUTED"


class WaiverDisputeAction(str, Enum):
    DISPUTE = "DISPUTE"
    RESOLVE = "RESOLVE"


class PaymentIntent(str, Enum):
    REGULAR = "REGULAR"
    PAYOFF = "PAYOFF"


class LedgerEntryType(str, Enum):
    INITIAL_FUNDING = "INITIAL_FUNDING"
    DRAW_DISBURSEMENT = "DRAW_DISBURSEMENT"
    RESERVE_SWEEP = "RESERVE_SWEEP"
    BORROWER_PAYMENT = "BORROWER_PAYMENT"
    EXTENSION_FEE = "EXTENSION_FEE"
    HOLDBACK_DECOMMIT = "HOLDBACK_DECOMMIT"
    COMPLETION_ADVANCE = "COMPLETION_ADVANCE"
    REO_SALE_PROCEEDS = "REO_SALE_PROCEEDS"
    PAYOFF = "PAYOFF"
    CHARGE_OFF = "CHARGE_OFF"


class MilestoneType(str, Enum):
    LISTED = "LISTED"
    PRICE_REDUCED = "PRICE_REDUCED"
    DELISTED = "DELISTED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CONTRACT_FALLOUT = "CONTRACT_FALLOUT"
    REFI_APPLICATION = "REFI_APPLICATION"
    REFI_APPRAISAL_COMPLETE = "REFI_APPRAISAL_COMPLETE"
    REFI_COMMITMENT_ISSUED = "REFI_COMMITMENT_ISSUED"


class ForeclosureCaseStatus(str, Enum):
    NOTICE_FILED = "NOTICE_FILED"
    TAKEOVER_COMPLETE = "TAKEOVER_COMPLETE"
    COMPLETION_FUNDED = "COMPLETION_FUNDED"
    RESOLVED = "RESOLVED"


# --------------------------------------------------------------------------
# Entities carrying the full common-property set (id/created_at/updated_at/version)
# --------------------------------------------------------------------------


class Borrower(TypedDict):
    id: str
    legal_entity_name: str
    entity_type: str
    guarantor_name: str
    flips_last_24mo: int
    flips_lifetime: int
    credit_score: int
    liquidity_cents: int
    prior_default_count: int
    declared_target_loan_cents: int
    status: str
    guarantee_status: str
    guarantee_effective_date: Optional[str]
    suspension_reason: Optional[str]
    intake_experience_score: float
    recertified_experience_score: Optional[float]
    recertified_at: Optional[str]
    effective_experience_score: float
    experience_tier: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    address_line: str
    county_code: str
    purchase_price_cents: int
    as_is_value_cents: int
    arv_cents: int
    appraisal_date: str
    status: str
    valuation_revision_count: int
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    business_name: str
    license_number: str
    license_expires_on: str
    w9_on_file: bool
    joint_check_required: bool
    license_status: str
    payable: bool
    collected_waiver_coverage_cents: int
    released_to_contractor_cents: int
    open_waiver_headroom_cents: int
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict):
    id: str
    borrower_id: str
    property_id: str
    term_months: int
    quoted_rate_bps: int
    interest_reserve_months: int
    day_count_convention: str
    status: str
    intake_experience_score: float
    pricing_tier: str
    approved_rehab_total_cents: int
    cap_purchase_advance_cents: Optional[int]
    cap_ltc_cents: Optional[int]
    cap_ltarv_cents: Optional[int]
    max_total_loan_cents: Optional[int]
    sized_initial_funding_cents: Optional[int]
    sized_interest_reserve_cents: Optional[int]
    sized_committed_amount_cents: Optional[int]
    sizing_arv_cents: Optional[int]
    sizing_rate_bps: Optional[int]
    sizing_stale: bool
    sized_at: Optional[str]
    sized_by_user_id: Optional[str]
    approved_loan_amount_cents: Optional[int]
    approved_rate_bps: Optional[int]
    alloc_initial_funding_cents: Optional[int]
    alloc_interest_reserve_cents: Optional[int]
    alloc_rehab_holdback_cents: Optional[int]
    decided_by_user_id: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RehabLineItem(TypedDict):
    id: str
    application_id: str
    scope_code: str
    description: str
    cost_cents: int
    contractor_id: str
    approved_cost_cents: Optional[int]
    reviewer_note: Optional[str]
    revision_round: int
    released_cents: int
    released_percent: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    application_id: str
    borrower_id: str
    closing_date: str
    term_months: int
    day_count_convention: str
    note_rate_bps: int
    default_rate_bps: int
    maturity_date: str
    committed_amount_cents: int
    funded_principal_cents: int
    repaid_principal_cents: int
    reserved_release_cents: int
    undisbursed_holdback_cents: int
    interest_reserve_balance_cents: int
    interest_reserve_funded_cents: int
    decommitted_holdback_cents: int
    available_rehab_pool_cents: int
    commitment_balance_check_cents: int
    accrued_interest_unpaid_cents: int
    fee_balance_cents: int
    payoff_quote_cents: int
    payment_status: str
    construction_status: str
    exit_status: str
    extension_count: int
    extension_months_total: int
    last_accrual_through: Optional[str]
    delinquent_since: Optional[str]
    default_effective_date: Optional[str]
    days_on_market: int
    exit_watch_flag: bool
    charge_off_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DrawRequest(TypedDict):
    id: str
    loan_id: str
    sequence_number: int
    verification_method: str
    requested_total_cents: int
    approved_release_cents: Optional[int]
    reviewed_by_user_id: Optional[str]
    funded_by_user_id: Optional[str]
    funded_at: Optional[str]
    photo_count: Optional[int]
    superseded_by_draw_request_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DrawLineItem(TypedDict):
    id: str
    draw_request_id: str
    rehab_line_item_id: str
    claimed_percent_complete: float
    verified_percent_complete: Optional[float]
    effective_percent_complete: Optional[float]
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    released_cents: int
    created_at: str
    updated_at: str
    version: int


class InspectionVisit(TypedDict):
    id: str
    draw_request_id: str
    inspector_id: str
    window_start: str
    window_end: str
    reported_at: Optional[str]
    site_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LienWaiver(TypedDict):
    id: str
    loan_id: str
    contractor_id: str
    waiver_type: str
    amount_covered_cents: int
    through_date: str
    counts_toward_coverage: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ForeclosureCase(TypedDict):
    id: str
    loan_id: str
    notice_date: str
    county_code: str
    redemption_expires_on: str
    takeover_date: Optional[str]
    completion_budget_cents: Optional[int]
    completion_advanced_cents: int
    sale_price_cents: Optional[int]
    sale_date: Optional[str]
    selling_costs_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    recovery_cents: Optional[int]
    charge_off_cents: Optional[int]
    surplus_returned_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only journals — PRD §2.7: only `id` and `created_at`
# --------------------------------------------------------------------------


class LedgerEntry(TypedDict):
    id: str
    loan_id: str
    entry_type: str
    amount_cents: int
    effective_date: str
    memo: str
    source_ref: str
    created_at: str


class InterestAccrualPeriod(TypedDict):
    id: str
    loan_id: str
    period_start: str
    period_end: str
    day_count: int
    note_rate_days: int
    default_rate_days: int
    principal_snapshot_cents: int
    note_rate_interest_cents: int
    default_rate_interest_cents: int
    interest_accrued_cents: int
    swept_from_reserve_cents: int
    unpaid_added_cents: int
    created_at: str


class ExitMilestone(TypedDict):
    id: str
    loan_id: str
    milestone_type: str
    effective_date: str
    listing_price_cents: Optional[int]
    lender_name: Optional[str]
    note: Optional[str]
    derived_exit_status: str
    created_at: str


LINE_ALLOCATION_KEYS = ["rehab_line_item_id", "claimed_percent_complete"]
LINE_VERIFICATION_KEYS = ["rehab_line_item_id", "verified_percent_complete"]

APPEND_ONLY_ENTITIES: List[str] = [
    "LedgerEntry",
    "InterestAccrualPeriod",
    "ExitMilestone",
]
