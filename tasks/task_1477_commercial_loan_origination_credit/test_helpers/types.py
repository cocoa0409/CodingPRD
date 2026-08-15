"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    BANK_ADMIN = "BankAdmin"
    RELATIONSHIP_MANAGER = "RelationshipManager"
    CREDIT_ANALYST = "CreditAnalyst"
    APPRAISAL_MANAGER = "AppraisalManager"
    COMMITTEE_CHAIR = "CommitteeChair"
    COMMITTEE_MEMBER = "CommitteeMember"
    CREDIT_POLICY_OFFICER = "CreditPolicyOfficer"
    CREDIT_ADMINISTRATOR = "CreditAdministrator"


class ProductType(str, Enum):
    CRE_TERM = "CRE_TERM"
    CRE_CONSTRUCTION = "CRE_CONSTRUCTION"
    CI_WORKING_CAPITAL = "CI_WORKING_CAPITAL"
    EQUIPMENT = "EQUIPMENT"
    AGRICULTURE = "AGRICULTURE"


class BorrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class ApplicationStatus(str, Enum):
    INTAKE = "INTAKE"
    SPREADING = "SPREADING"
    EXCEPTION_REVIEW = "EXCEPTION_REVIEW"
    APPRAISAL_REVIEW = "APPRAISAL_REVIEW"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    TERM_SHEET_NEGOTIATION = "TERM_SHEET_NEGOTIATION"
    COMMITMENT = "COMMITMENT"
    DOCUMENTATION = "DOCUMENTATION"
    CLOSING = "CLOSING"
    FUNDED = "FUNDED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class StatementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SPREAD = "SPREAD"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class ExceptionRuleCode(str, Enum):
    DSCR_MINIMUM = "DSCR_MINIMUM"
    STRESS_DSCR_MINIMUM = "STRESS_DSCR_MINIMUM"
    SINGLE_BORROWER_LIMIT = "SINGLE_BORROWER_LIMIT"
    REG_O_INSIDER = "REG_O_INSIDER"
    LTV_MAXIMUM = "LTV_MAXIMUM"
    COLLATERAL_COVERAGE_MIN = "COLLATERAL_COVERAGE_MIN"
    COVENANT_BREACH = "COVENANT_BREACH"
    REQUIRED_DOC_WAIVER = "REQUIRED_DOC_WAIVER"


class ExceptionSeverity(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    WAIVED = "WAIVED"
    RESOLVED_BY_CHANGE = "RESOLVED_BY_CHANGE"


class AppraiserStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"


class CollateralClass(str, Enum):
    REAL_ESTATE = "REAL_ESTATE"
    EQUIPMENT = "EQUIPMENT"
    RECEIVABLES = "RECEIVABLES"
    INVENTORY = "INVENTORY"
    AGRICULTURAL = "AGRICULTURAL"


class AppraisalStatus(str, Enum):
    ENGAGED = "ENGAGED"
    REPORT_RECEIVED = "REPORT_RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CommitteeLevel(str, Enum):
    SMALL = "SMALL"
    STANDARD = "STANDARD"
    LARGE = "LARGE"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ADJOURNED = "ADJOURNED"


class VoteValue(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    REMAND = "REMAND"


class DecisionStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    REMANDED = "REMANDED"


class RatingBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FULL = "FULL"


class TermSheetStatus(str, Enum):
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class LetterStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    FUNDED = "FUNDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class ChecklistCategory(str, Enum):
    DOCUMENT = "DOCUMENT"
    CLOSING_CONDITION = "CLOSING_CONDITION"


class ChecklistSeverity(str, Enum):
    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"


class ChecklistStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


class FundingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class CovenantType(str, Enum):
    DSCR_MIN = "DSCR_MIN"
    LEVERAGE_MAX = "LEVERAGE_MAX"
    CAPEX_LIMIT = "CAPEX_LIMIT"
    DISTRIBUTION_BLOCK = "DISTRIBUTION_BLOCK"


class CovenantFrequency(str, Enum):
    ANNUAL = "ANNUAL"
    QUARTERLY = "QUARTERLY"


class CovenantStatus(str, Enum):
    MONITORING = "MONITORING"
    COMPLIANT = "COMPLIANT"
    BREACH_PENDING = "BREACH_PENDING"
    CURED = "CURED"
    WAIVED = "WAIVED"


class ParticipationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    FUNDED = "FUNDED"
    RELEASED = "RELEASED"


class BankOfficer(TypedDict, total=False):
    id: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


class Borrower(TypedDict, total=False):
    id: str
    legal_name: str
    naics_code: str
    is_reg_o_insider: bool
    relationship_since: str
    status: str
    committed_exposure_cents: int
    funded_exposure_cents: int
    total_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict, total=False):
    id: str
    borrower_id: str
    originating_officer_id: str
    product_type: str
    requested_amount_cents: int
    term_months: int
    purpose: Optional[str]
    status: str
    dscr_standard: Optional[float]
    dscr_stress: Optional[float]
    risk_rating: Optional[int]
    rating_basis: Optional[str]
    proposed_amount_cents: Optional[int]
    committee_level_required: Optional[str]
    total_appraised_value_cents: int
    total_eligible_collateral_cents: int
    total_liquidation_collateral_cents: int
    bank_hold_amount_cents: int
    bank_hold_fee_cents: Optional[int]
    funded_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class FinancialStatement(TypedDict, total=False):
    id: str
    loan_application_id: str
    restatement_of_id: Optional[str]
    period_end_date: str
    revenue_cents: int
    ebitda_cents: int
    addbacks_cents: int
    distributions_cents: int
    maintenance_capex_cents: int
    existing_annual_debt_service_cents: int
    total_assets_cents: int
    total_liabilities_cents: int
    status: str
    spread_by_officer_id: Optional[str]
    finalized_by_officer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PolicyException(TypedDict, total=False):
    id: str
    loan_application_id: str
    rule_code: str
    severity: str
    status: str
    detail: str
    waived_by_officer_id: Optional[str]
    waiver_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appraiser(TypedDict, total=False):
    id: str
    name: str
    license_number: str
    max_concurrent_engagements: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict, total=False):
    id: str
    loan_application_id: str
    appraiser_id: str
    collateral_class: str
    engagement_start_date: str
    engagement_end_date: str
    appraised_value_cents: Optional[int]
    orderly_liquidation_value_cents: Optional[int]
    eligible_value_cents: Optional[int]
    liquidation_basis_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitteeSession(TypedDict, total=False):
    id: str
    level: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitteeDecision(TypedDict, total=False):
    id: str
    loan_application_id: str
    committee_session_id: str
    level_required: str
    votes_required: int
    votes: List[dict]
    votes_for: int
    votes_against: int
    chair_approved: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TermSheet(TypedDict, total=False):
    id: str
    loan_application_id: str
    amount_cents: int
    rate_bps: int
    term_months: int
    expires_at: str
    origination_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitmentLetter(TypedDict, total=False):
    id: str
    loan_application_id: str
    committed_amount_cents: int
    rate_bps: int
    term_months: int
    origination_fee_cents: int
    expiry_date: Optional[str]
    rate_lock_expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DocumentChecklistItem(TypedDict, total=False):
    id: str
    loan_application_id: str
    category: str
    label: str
    is_required: bool
    severity: str
    status: str
    waived_by_officer_id: Optional[str]
    waiver_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingAuthorization(TypedDict, total=False):
    id: str
    loan_application_id: str
    amount_cents: int
    disbursement_date: str
    requested_by_officer_id: str
    authorized_by_officer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Covenant(TypedDict, total=False):
    id: str
    loan_application_id: str
    covenant_type: str
    threshold_value: float
    frequency: str
    status: str
    last_reviewed_period: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Participation(TypedDict, total=False):
    id: str
    loan_application_id: str
    participant_bank_name: str
    allocated_amount_cents: int
    fee_share_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
