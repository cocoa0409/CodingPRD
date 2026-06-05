"""Domain types: entity TypedDicts, status enums, role enum for the HELOC platform."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    LOAN_OFFICER = "LoanOfficer"
    LOAN_SERVICER = "LoanServicer"
    BORROWER = "Borrower"
    AUDITOR = "Auditor"


class KycStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class PropertyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class HelocStatus(str, Enum):
    APPLICATION = "APPLICATION"
    DRAW = "DRAW"
    REPAYMENT = "REPAYMENT"
    FROZEN = "FROZEN"
    DEFAULTED = "DEFAULTED"
    CLOSED = "CLOSED"


class LienPosition(str, Enum):
    FIRST = "FIRST"
    SECOND = "SECOND"


class DrawStatus(str, Enum):
    BOOKED = "BOOKED"
    REVERSED = "REVERSED"


class FeeType(str, Enum):
    ANNUAL = "ANNUAL"
    EARLY_CLOSURE = "EARLY_CLOSURE"


class SettlementStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


class CovenantType(str, Enum):
    MAX_CLTV = "MAX_CLTV"
    MIN_DSCR = "MIN_DSCR"
    MAX_DELINQUENCY_DAYS = "MAX_DELINQUENCY_DAYS"


class CovenantStatus(str, Enum):
    SATISFIED = "SATISFIED"
    BREACHED = "BREACHED"
    CURED = "CURED"


class LienRecordStatus(str, Enum):
    RECORDED = "RECORDED"
    RELEASED = "RELEASED"


# --- Entity TypedDicts (common_fields: true => id, created_at, updated_at, version) ---

class Property(TypedDict):
    id: str
    street_address: str
    appraised_value_cents: int
    senior_lien_balance_cents: int
    county_fips: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Borrower(TypedDict):
    id: str
    full_name: str
    annual_income_cents: int
    monthly_debt_obligation_cents: int
    credit_score: int
    kyc_status: str
    created_at: str
    updated_at: str
    version: int


class IndexRate(TypedDict):
    id: str
    index_name: str
    rate_bps: int
    effective_date: str
    superseded: bool
    created_at: str
    updated_at: str
    version: int


class Heloc(TypedDict):
    id: str
    borrower_id: str
    property_id: str
    lien_position: str
    credit_limit_cents: int
    margin_bps: int
    rate_ceiling_bps: int
    annual_fee_cents: int
    origination_date: str
    draw_period_years: int
    repayment_period_years: int
    status: str
    current_balance_cents: int
    available_credit_cents: int
    current_apr_bps: int
    accrued_interest_cents: int
    delinquency_days: int
    anniversary_count: int
    created_at: str
    updated_at: str
    version: int


class Draw(TypedDict):
    id: str
    heloc_id: str
    amount_cents: int
    requested_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    heloc_id: str
    amount_cents: int
    posted_at: str
    interest_applied_cents: int
    principal_applied_cents: int
    fee_applied_cents: int
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict):
    id: str
    heloc_id: str
    fee_type: str
    amount_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class Covenant(TypedDict):
    id: str
    heloc_id: str
    covenant_type: str
    threshold_value: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LienRecord(TypedDict):
    id: str
    heloc_id: str
    property_id: str
    position: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- DefaultEvent (common_fields: false => only id + created_at, no updated_at/version) ---

class DefaultEvent(TypedDict):
    id: str
    heloc_id: str
    covenant_id: str
    trigger_type: str
    observed_value: int
    declared_by_user_id: str
    created_at: str
