"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.8, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    AGENT = "Agent"
    UNDERWRITER = "Underwriter"
    POLICY_ISSUER = "PolicyIssuer"
    POLICYHOLDER = "Policyholder"


class Gender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    OTHER = "OTHER"


class ProductType(str, Enum):
    WHOLE_LIFE_PARTICIPATING = "WHOLE_LIFE_PARTICIPATING"
    WHOLE_LIFE_NON_PARTICIPATING = "WHOLE_LIFE_NON_PARTICIPATING"
    TERM_CONVERTIBLE = "TERM_CONVERTIBLE"
    UNIVERSAL_LIFE = "UNIVERSAL_LIFE"


class PremiumMode(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMI_ANNUAL = "SEMI_ANNUAL"
    ANNUAL = "ANNUAL"


class UnderwritingClass(str, Enum):
    PREFERRED_NON_TOBACCO = "PREFERRED_NON_TOBACCO"
    STANDARD_NON_TOBACCO = "STANDARD_NON_TOBACCO"
    PREFERRED_TOBACCO = "PREFERRED_TOBACCO"
    STANDARD_TOBACCO = "STANDARD_TOBACCO"
    SUBSTANDARD_TABLE_B = "SUBSTANDARD_TABLE_B"
    SUBSTANDARD_TABLE_D = "SUBSTANDARD_TABLE_D"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ISSUED = "ISSUED"


class PremiumPaymentStatus(str, Enum):
    CURRENT = "CURRENT"
    GRACE = "GRACE"
    LAPSED = "LAPSED"
    REINSTATED_PENDING = "REINSTATED_PENDING"
    PAID_UP = "PAID_UP"


class FormStatus(str, Enum):
    IN_FORCE = "IN_FORCE"
    REDUCED_PAID_UP = "REDUCED_PAID_UP"
    EXTENDED_TERM = "EXTENDED_TERM"
    CONVERTED = "CONVERTED"
    SURRENDERED = "SURRENDERED"
    DEATH_CLAIMED = "DEATH_CLAIMED"


class BillingCycleStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    GRACE = "GRACE"
    LAPSED = "LAPSED"
    WAIVED = "WAIVED"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REPAID = "REPAID"
    FORECLOSED = "FORECLOSED"


class DividendStatus(str, Enum):
    DECLARED = "DECLARED"
    APPLIED = "APPLIED"
    FORFEITED = "FORFEITED"


class DividendOption(str, Enum):
    CASH = "CASH"
    PREMIUM_REDUCTION = "PREMIUM_REDUCTION"
    ACCUMULATE_AT_INTEREST = "ACCUMULATE_AT_INTEREST"
    PAID_UP_ADDITIONS = "PAID_UP_ADDITIONS"


class ElectionType(str, Enum):
    CASH_SURRENDER = "CASH_SURRENDER"
    REDUCED_PAID_UP = "REDUCED_PAID_UP"
    EXTENDED_TERM = "EXTENDED_TERM"


class ReinstatementStatus(str, Enum):
    PENDING = "PENDING"
    EVIDENCE_REQUIRED = "EVIDENCE_REQUIRED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class UnderwriterDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class RiderType(str, Enum):
    WAIVER_OF_PREMIUM = "WAIVER_OF_PREMIUM"
    ACCIDENTAL_DEATH_BENEFIT = "ACCIDENTAL_DEATH_BENEFIT"
    TERM_CHILD = "TERM_CHILD"
    GUARANTEED_INSURABILITY = "GUARANTEED_INSURABILITY"


class RiderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXERCISED = "EXERCISED"


class ConversionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class LedgerEntryType(str, Enum):
    PREMIUM_CREDIT = "PREMIUM_CREDIT"
    COI_DEBIT = "COI_DEBIT"
    LOAN_DISBURSEMENT = "LOAN_DISBURSEMENT"
    LOAN_REPAYMENT_CREDIT = "LOAN_REPAYMENT_CREDIT"
    DIVIDEND_CREDIT = "DIVIDEND_CREDIT"
    RIDER_PREMIUM_DEBIT = "RIDER_PREMIUM_DEBIT"
    SURRENDER_DEBIT = "SURRENDER_DEBIT"
    MONTHLY_FEE_DEBIT = "MONTHLY_FEE_DEBIT"


# ---------------------------------------------------------------------------
# Entity TypedDicts.  Entities carrying the standard resource properties of
# PRD §2.5 have id + created_at + updated_at + version.  The two append-only
# families (loan interest accrual rows and cash-value ledger entries) carry
# ONLY id + created_at per PRD §2.5.
# ---------------------------------------------------------------------------


class InsuredPerson(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    tobacco_user: bool
    gender: str
    created_at: str
    updated_at: str
    version: int


class CoiRateEntry(TypedDict):
    attained_age: int
    monthly_rate_per_thousand_cents: int


class SurrenderChargeEntry(TypedDict):
    policy_year_min_inclusive: int
    surrender_charge_pct_bps: int


class ProductTemplate(TypedDict):
    id: str
    product_code: str
    product_type: str
    participating: bool
    allows_policy_loans: bool
    min_face_amount_cents: int
    max_face_amount_cents: int
    base_monthly_premium_rate_per_thousand_cents: int
    coi_rate_table: List[CoiRateEntry]
    surrender_charge_schedule: List[SurrenderChargeEntry]
    created_at: str
    updated_at: str
    version: int


class PolicyApplication(TypedDict):
    id: str
    insured_person_id: str
    product_template_id: str
    requested_face_amount_cents: int
    premium_mode: str
    underwriting_class: Optional[str]
    substandard_extra_pct_bps: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    application_id: str
    insured_person_id: str
    product_template_id: str
    policy_number: str
    issue_date: str
    face_amount_cents: int
    premium_mode: str
    modal_premium_cents: int
    underwriting_class: str
    premium_payment_status: str
    form_status: str
    grace_period_end_date: Optional[str]
    cash_value_cents: int
    outstanding_loan_principal_cents: int
    accrued_loan_interest_cents: int
    dividend_accumulation_cents: int
    dividend_option: Optional[str]
    paid_to_date: str
    attained_age_at_issue: int
    policy_year: int
    created_at: str
    updated_at: str
    version: int


class PremiumBillingCycle(TypedDict):
    id: str
    policy_id: str
    cycle_index: int
    period_start_date: str
    period_end_date: str
    due_amount_cents: int
    paid_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PolicyLoan(TypedDict):
    id: str
    policy_id: str
    requested_amount_cents: int
    origination_date: str
    annual_interest_rate_bps: int
    outstanding_principal_cents: int
    accrued_interest_cents: int
    last_accrual_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanInterestAccrual(TypedDict):
    # Append-only family (PRD §2.5): only id + created_at, no updated_at/version.
    id: str
    loan_id: str
    accrual_period_start: str
    accrual_period_end: str
    principal_base_cents: int
    days_accrued: int
    interest_accrued_cents: int
    created_at: str


class DividendDeclaration(TypedDict):
    id: str
    policy_id: str
    policy_year: int
    declared_amount_cents: int
    applied_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NonforfeitureElection(TypedDict):
    id: str
    policy_id: str
    election_type: str
    effective_date: str
    cash_value_at_election_cents: int
    outstanding_loan_offset_cents: int
    surrender_charge_cents: int
    net_available_cents: int
    resulting_face_amount_cents: int
    resulting_term_months: int
    payout_cents: int
    created_at: str
    updated_at: str
    version: int


class ReinstatementRequest(TypedDict):
    id: str
    policy_id: str
    request_date: str
    back_premium_due_cents: int
    back_premium_paid_cents: int
    evidence_of_insurability: bool
    underwriter_decision: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict):
    id: str
    policy_id: str
    rider_type: str
    rider_face_amount_cents: int
    rider_monthly_premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConversionRequest(TypedDict):
    id: str
    source_policy_id: str
    target_product_template_id: str
    requested_face_amount_cents: int
    attained_age_at_conversion: int
    new_policy_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CashValueLedgerEntry(TypedDict):
    # Append-only family (PRD §2.5): only id + created_at, no updated_at/version.
    id: str
    policy_id: str
    entry_type: str
    amount_cents: int
    posting_date: str
    resulting_cash_value_cents: int
    created_at: str
