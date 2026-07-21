"""Domain types: entity TypedDicts, status enums, role enum.

All types describe the Home-Equity Investment (HEI) API resources as the PRD
declares them. Every persisted resource carries id, created_at, updated_at,
and version (PRD Section 2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD Section 2.1) ---
class UserRole(str, Enum):
    HOMEOWNER = "Homeowner"
    INVESTMENT_ANALYST = "InvestmentAnalyst"
    APPRAISER = "Appraiser"
    CLOSING_AGENT = "ClosingAgent"
    INSPECTOR = "Inspector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Status / method enums ---
class PropertyType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    CONDO = "CONDO"
    TOWNHOUSE = "TOWNHOUSE"
    MULTI_UNIT = "MULTI_UNIT"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    OFFERED = "OFFERED"
    FUNDED = "FUNDED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    ELEVATED = "ELEVATED"


class ValuationMethod(str, Enum):
    AVM = "AVM"
    APPRAISAL = "APPRAISAL"


class ValuationStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OfferStatus(str, Enum):
    PRESENTED = "PRESENTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COUNTERED = "COUNTERED"
    WITHDRAWN = "WITHDRAWN"


class AgreementStatus(str, Enum):
    FUNDED = "FUNDED"
    ACTIVE = "ACTIVE"
    EXIT_INITIATED = "EXIT_INITIATED"
    SETTLEMENT_PROPOSED = "SETTLEMENT_PROPOSED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    DEFAULTED = "DEFAULTED"


class CovenantStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    BREACH_NOTICED = "BREACH_NOTICED"
    CURED = "CURED"


class TitleStatus(str, Enum):
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    CLOUDED = "CLOUDED"


class LienStatus(str, Enum):
    PENDING = "PENDING"
    RECORDED = "RECORDED"
    RELEASED = "RELEASED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class SettlementType(str, Enum):
    SALE = "SALE"
    BUYOUT = "BUYOUT"


class SettlementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DISPUTED = "DISPUTED"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts (all resources carry the four common fields) ---
class Fund(TypedDict):
    id: str
    name: str
    total_capital_cents: int
    committed_capital_cents: int
    available_capital_cents: int
    created_at: str
    updated_at: str
    version: int


class Homeowner(TypedDict):
    id: str
    email: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    homeowner_id: str
    fund_id: str
    property_address: str
    property_type: str
    homeowner_estimated_value_cents: int
    existing_mortgage_balance_cents: int
    requested_investment_cents: int
    status: str
    combined_ltv: Optional[float]
    risk_band: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Valuation(TypedDict):
    id: str
    application_id: str
    method: str
    valued_amount_cents: int
    confidence_score: Optional[float]
    source_appointment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appraiser(TypedDict):
    id: str
    full_name: str
    region_code: str
    created_at: str
    updated_at: str
    version: int


class AppraisalAppointment(TypedDict):
    id: str
    appraiser_id: str
    valuation_id: str
    region_code: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    application_id: str
    fund_id: str
    valuation_id: str
    investment_amount_cents: int
    option_percentage: float
    risk_adjustment_pct: float
    term_months: int
    capped_annual_rate: float
    expires_at: str
    adjusted_start_value_cents: int
    status: str
    counter_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict):
    id: str
    offer_id: str
    application_id: str
    fund_id: str
    investment_amount_cents: int
    option_percentage: float
    adjusted_start_value_cents: int
    term_months: int
    capped_annual_rate: float
    funded_at: str
    maturity_at: str
    status: str
    covenant_status: str
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict):
    id: str
    agreement_id: str
    title_status: str
    lien_position: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict):
    id: str
    full_name: str
    region_code: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    agreement_id: str
    inspector_id: str
    scheduled_date: str
    status: str
    condition_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    agreement_id: str
    settlement_type: str
    sale_price_cents: Optional[int]
    current_appraised_value_cents: Optional[int]
    mortgage_payoff_cents: int
    ending_value_cents: int
    elapsed_months: int
    appreciation_share_cents: int
    settlement_fee_cents: int
    net_proceeds_cents: int
    homeowner_payout_cents: int
    status: str
    proposed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    settlement_id: str
    agreement_id: str
    reason: str
    disputed_value_cents: int
    resolved_value_cents: Optional[int]
    resolved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
