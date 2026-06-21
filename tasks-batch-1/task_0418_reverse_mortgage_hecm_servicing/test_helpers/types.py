"""Domain types: entity TypedDicts, status enums, role enum.

Reverse Mortgage / HECM Servicing API.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SERVICER_OPS = "ServicerOps"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BORROWER = "Borrower"
    HUD_AUDITOR = "HudAuditor"
    SYSTEM = "System"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class LoanServicingStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT_OCCUPANCY = "DELINQUENT_OCCUPANCY"
    DELINQUENT_PROPERTY_CHARGE = "DELINQUENT_PROPERTY_CHARGE"


class LoanDispositionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DUE_AND_PAYABLE = "DUE_AND_PAYABLE"
    DEFERRED = "DEFERRED"
    IN_RESOLUTION = "IN_RESOLUTION"
    TERMINATED = "TERMINATED"


class DrawType(str, Enum):
    LUMP_SUM = "LUMP_SUM"
    LINE_OF_CREDIT = "LINE_OF_CREDIT"
    TENURE = "TENURE"
    TERM = "TERM"


class DisbursementKind(str, Enum):
    INITIAL = "INITIAL"
    LINE_DRAW = "LINE_DRAW"
    SCHEDULED = "SCHEDULED"


class DisbursementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class LesaFundingMode(str, Enum):
    FULLY_FUNDED = "FULLY_FUNDED"
    PARTIALLY_FUNDED = "PARTIALLY_FUNDED"


class LesaStatus(str, Enum):
    FUNDED = "FUNDED"
    EXHAUSTED = "EXHAUSTED"


class ChargeType(str, Enum):
    PROPERTY_TAX = "PROPERTY_TAX"
    HAZARD_INSURANCE = "HAZARD_INSURANCE"


class PropertyChargePaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class OccupancyCertificationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    DELINQUENT = "DELINQUENT"


class MaturityEventType(str, Enum):
    BORROWER_DEATH = "BORROWER_DEATH"
    PERMANENT_VACANCY = "PERMANENT_VACANCY"
    SALE_OF_PROPERTY = "SALE_OF_PROPERTY"
    TAX_INSURANCE_DEFAULT = "TAX_INSURANCE_DEFAULT"


class MaturityEventStatus(str, Enum):
    RECORDED = "RECORDED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class DeferralStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ResolutionPath(str, Enum):
    PAYOFF = "PAYOFF"
    SHORT_SALE = "SHORT_SALE"
    FORECLOSURE = "FORECLOSURE"


class ResolutionStatus(str, Enum):
    INITIATED = "INITIATED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class OccupancyStatus(str, Enum):
    OCCUPYING = "OCCUPYING"
    VACATED = "VACATED"
    DECEASED = "DECEASED"


class LedgerEntryType(str, Enum):
    ADVANCE = "ADVANCE"
    INTEREST_ACCRUAL = "INTEREST_ACCRUAL"
    MIP_ACCRUAL = "MIP_ACCRUAL"
    LESA_DRAW = "LESA_DRAW"
    REVERSAL = "REVERSAL"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

# common_fields: true — id + created_at + updated_at + version
class Lender(TypedDict):
    id: str
    name: str
    hud_lending_limit_cents: int
    clock_utc: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only reference row: only id + created_at
class PrincipalLimitFactor(TypedDict):
    id: str
    lender_id: str
    age: int
    expected_rate_bps: int
    factor_micros: int
    created_at: str


# common_fields: true
class Borrower(TypedDict):
    id: str
    lender_id: str
    full_name: str
    birthdate: str
    is_non_borrowing_spouse: bool
    nbs_qualifies: bool
    occupancy_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Loan(TypedDict):
    id: str
    lender_id: str
    borrower_id: str
    non_borrowing_spouse_id: Optional[str]
    appraised_value_cents: int
    expected_rate_bps: int
    annual_mip_rate_bps: int
    draw_type: str
    tenure_term_months: Optional[int]
    max_claim_amount_cents: int
    principal_limit_factor_micros: int
    gross_principal_limit_cents: int
    lesa_set_aside_cents: int
    net_principal_limit_cents: int
    initial_financed_costs_cents: int
    principal_balance_cents: int
    available_line_of_credit_cents: int
    monthly_payment_cents: int
    months_elapsed: int
    servicing_status: str
    disposition_status: str
    origination_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Disbursement(TypedDict):
    id: str
    loan_id: str
    kind: str
    requested_amount_cents: int
    approved_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class LesaSetAside(TypedDict):
    id: str
    loan_id: str
    funding_mode: str
    annual_property_charge_cents: int
    life_expectancy_years: int
    initial_amount_cents: int
    drawn_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class PropertyChargePayment(TypedDict):
    id: str
    loan_id: str
    lesa_set_aside_id: str
    charge_type: str
    coverage_start: str
    coverage_end: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class OccupancyCertification(TypedDict):
    id: str
    loan_id: str
    certification_year: int
    due_date: str
    certified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class MaturityEvent(TypedDict):
    id: str
    loan_id: str
    event_type: str
    event_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class NonBorrowingSpouseDeferral(TypedDict):
    id: str
    loan_id: str
    borrower_id: str
    maturity_event_id: str
    period_start: str
    period_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Resolution(TypedDict):
    id: str
    loan_id: str
    path: str
    appraised_at_resolution_cents: Optional[int]
    payoff_amount_cents: int
    deficiency_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger row: only id + created_at
class LedgerEntry(TypedDict):
    id: str
    loan_id: str
    entry_type: str
    source_ref_id: Optional[str]
    amount_cents: int
    balance_after_cents: int
    posted_month_index: int
    created_at: str
