"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource in this system carries
the standard quartet of system-managed fields (id, created_at, updated_at,
version) described in the PRD's common-resource-properties section.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    MASTER_SERVICER = "MasterServicer"
    SPECIAL_SERVICER = "SpecialServicer"
    BORROWER = "Borrower"
    INSPECTOR = "Inspector"


class PaymentStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"
    MATURITY_DEFAULT = "MATURITY_DEFAULT"


class ServicingStatus(str, Enum):
    PERFORMING = "PERFORMING"
    WATCHLIST = "WATCHLIST"
    SPECIAL_SERVICING = "SPECIAL_SERVICING"


class DscrBasis(str, Enum):
    TTM = "TTM"
    T3_ANNUALIZED = "T3_ANNUALIZED"


class AssumptionFeeBasis(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    ORIGINAL = "ORIGINAL"


class PropertyType(str, Enum):
    OFFICE = "OFFICE"
    RETAIL = "RETAIL"
    INDUSTRIAL = "INDUSTRIAL"
    MULTIFAMILY = "MULTIFAMILY"
    HOTEL = "HOTEL"


class StatementType(str, Enum):
    RENT_ROLL = "RENT_ROLL"
    OPERATING_STATEMENT = "OPERATING_STATEMENT"


class StatementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AssessmentType(str, Enum):
    DSCR = "DSCR"
    LTV = "LTV"


class AssessmentStatus(str, Enum):
    OPEN = "OPEN"
    CONFORMING = "CONFORMING"
    CURED = "CURED"
    WAIVED = "WAIVED"


class ReserveAccountType(str, Enum):
    TI_LC = "TI_LC"
    REPLACEMENT = "REPLACEMENT"


class DisbursementPurpose(str, Enum):
    TENANT_IMPROVEMENT = "TENANT_IMPROVEMENT"
    LEASING_COMMISSION = "LEASING_COMMISSION"
    CAPITAL_REPAIR = "CAPITAL_REPAIR"


class DisbursementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    FUNDED = "FUNDED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    REJECTED = "REJECTED"


class EstoppelStatus(str, Enum):
    PENDING = "PENDING"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ConditionRating(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    CRITICAL = "CRITICAL"


class CoverageType(str, Enum):
    PROPERTY = "PROPERTY"
    LIABILITY = "LIABILITY"
    FLOOD = "FLOOD"


class InsurancePolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class AssumptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    WITHDRAWN = "WITHDRAWN"


class ExtensionOptionStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    EXERCISED = "EXERCISED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class WatchlistCriterion(str, Enum):
    REPORTING_DELINQUENCY = "REPORTING_DELINQUENCY"
    POOR_INSPECTION = "POOR_INSPECTION"
    INSURANCE_LAPSE = "INSURANCE_LAPSE"
    MATURITY_RISK = "MATURITY_RISK"
    RISK_SCORE = "RISK_SCORE"


class WatchlistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class Borrower(TypedDict, total=False):
    id: str
    legal_name: str
    tax_id: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    borrower_id: str
    loan_number: str
    original_principal_cents: int
    current_balance_cents: int
    note_rate: float
    origination_date: str
    maturity_date: str
    payment_status: str
    servicing_status: str
    delinquent_since: Optional[str]
    days_delinquent: int
    dscr_covenant_threshold: float
    ltv_covenant_threshold: float
    dscr_basis: str
    assumption_fee_basis: str
    current_dscr: Optional[float]
    current_ltv: Optional[float]
    capitalized_advances_cents: int
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    loan_id: str
    address: str
    property_type: str
    appraised_value_cents: int
    appraisal_date: str
    appraised_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancialStatement(TypedDict, total=False):
    id: str
    loan_id: str
    statement_type: str
    period_start: str
    period_end: str
    net_operating_income_cents: Optional[int]
    occupancy_pct: Optional[float]
    due_date: str
    submitted_late: bool
    status: str
    rejection_reason: Optional[str]
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CovenantAssessment(TypedDict, total=False):
    id: str
    loan_id: str
    statement_id: Optional[str]
    assessment_type: str
    basis: Optional[str]
    computed_value: Optional[float]
    threshold_value: float
    breach: bool
    status: str
    assessed_at: str
    waived_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReserveAccount(TypedDict, total=False):
    id: str
    loan_id: str
    account_type: str
    balance_cents: int
    held_cents: int
    retained_cents: int
    target_balance_cents: int
    elevated_retainage: bool
    disbursement_frozen: bool
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class DisbursementLineItem(TypedDict):
    description: str
    amount_cents: int


class DisbursementRequest(TypedDict, total=False):
    id: str
    reserve_account_id: str
    purpose: str
    line_items: List[DisbursementLineItem]
    amount_cents: int
    retainage_pct: float
    status: str
    funded_cents: int
    retained_cents: int
    funded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    property_id: str
    tenant_name: str
    suite_ref: str
    commencement_date: str
    expiry_date: str
    base_rent_cents_monthly: int
    sqft: int
    term_months: int
    status: str
    lender_approval_required: bool
    estoppel_required: bool
    conditions: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EstoppelCertificate(TypedDict, total=False):
    id: str
    lease_id: str
    status: str
    due_date: str
    executed_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict, total=False):
    id: str
    full_name: str
    license_no: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class PropertyInspection(TypedDict, total=False):
    id: str
    property_id: str
    inspector_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    condition_rating: Optional[str]
    findings: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    property_id: str
    coverage_type: str
    coverage_amount_cents: int
    start_date: str
    end_date: str
    force_placed: bool
    premium_advance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AssumptionRequest(TypedDict, total=False):
    id: str
    loan_id: str
    proposed_assumptor_name: str
    proposed_assumptor_tax_id: str
    proposed_net_worth_cents: int
    status: str
    fee_cents: Optional[int]
    decided_at: Optional[str]
    approval_expires_at: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExtensionOption(TypedDict, total=False):
    id: str
    loan_id: str
    option_seq: int
    exercise_window_start: str
    exercise_window_end: str
    extension_months: int
    fee_pct: float
    status: str
    exercised_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class WatchlistEntry(TypedDict, total=False):
    id: str
    loan_id: str
    criterion: str
    status: str
    risk_score_at_creation: Optional[int]
    escalation_review: bool
    source_ref: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
