"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Fiscal years, airlines, agreements,
rate settings, capital projects, settlements, settlement lines, and PFC
applications carry the four standard system-managed fields (id, created_at,
updated_at, version). ConsultationComment, ActivityRecord, and MIIVote are
immutable event records and carry only id + created_at among the common
properties (PRD section on common resource properties).
"""
from enum import Enum
from typing import Optional, TypedDict


class FiscalYearStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Methodology(str, Enum):
    RESIDUAL = "RESIDUAL"
    COMPENSATORY = "COMPENSATORY"
    HYBRID = "HYBRID"


class CarrierClass(str, Enum):
    PASSENGER = "PASSENGER"
    CARGO = "CARGO"
    CHARTER = "CHARTER"


class SignatureStatus(str, Enum):
    SIGNATORY = "SIGNATORY"
    NON_SIGNATORY = "NON_SIGNATORY"


class CreditStanding(str, Enum):
    GOOD = "GOOD"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"


class RatesSettingStatus(str, Enum):
    DRAFT = "DRAFT"
    CONSULTATION = "CONSULTATION"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class CapitalProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    MII_VOTING = "MII_VOTING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VETOED = "VETOED"
    CANCELLED = "CANCELLED"


class CostCenter(str, Enum):
    AIRFIELD = "AIRFIELD"
    TERMINAL = "TERMINAL"


class Ballot(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPUTED = "COMPUTED"
    AIRLINE_REVIEW = "AIRLINE_REVIEW"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"
    FINALIZED = "FINALIZED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    CREDITED = "CREDITED"
    WRITTEN_OFF = "WRITTEN_OFF"


class PFCStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    AIRPORT_FINANCE = "AirportFinance"
    AIRPORT_DIRECTOR = "AirportDirector"
    SIGNATORY_AIRLINE = "SignatoryAirline"
    AIRPORT_AUDITOR = "AirportAuditor"


# --- common_fields: true entities (id + created_at + updated_at + version) ---

class FiscalYear(TypedDict, total=False):
    id: str
    year_label: str
    methodology: str
    status: str
    airfield_opex_cents: int
    terminal_opex_cents: int
    nonairline_airfield_revenue_cents: int
    nonairline_terminal_revenue_cents: int
    terminal_total_space_sqft: int
    forecast_landed_weight_kg: int
    prior_year_surplus_cents: int
    total_projected_landed_weight_kg: int
    total_signatory_landed_weight_kg: int
    total_rented_space_sqft: int
    settlement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Airline(TypedDict, total=False):
    id: str
    iata_code: str
    legal_name: str
    carrier_class: str
    pfc_approved: bool
    mii_eligible_weight_kg: int
    created_at: str
    updated_at: str
    version: int


class AirlineAgreement(TypedDict, total=False):
    id: str
    airline_id: str
    fiscal_year_id: str
    signature_status: str
    credit_standing: str
    rented_space_sqft: int
    countersign_deadline: Optional[str]
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RatesSetting(TypedDict, total=False):
    id: str
    fiscal_year_id: str
    status: str
    airfield_requirement_cents: int
    signatory_landing_fee_per_1000kg_cents: int
    non_signatory_landing_fee_per_1000kg_cents: int
    terminal_rental_rate_per_sqft_year_cents: int
    adopted_at: Optional[str]
    consultation_comment_count: int
    created_at: str
    updated_at: str
    version: int


class CapitalProject(TypedDict, total=False):
    id: str
    fiscal_year_id: str
    project_name: str
    cost_center: str
    budget_cents: int
    mii_threshold_pct: int
    status: str
    votes_for_count: int
    votes_for_weight_kg: int
    votes_against_weight_kg: int
    created_at: str
    updated_at: str
    version: int


class AnnualSettlement(TypedDict, total=False):
    id: str
    fiscal_year_id: str
    status: str
    actual_airfield_requirement_cents: int
    actual_terminal_requirement_cents: int
    total_billed_landing_cents: int
    total_billed_terminal_cents: int
    total_true_up_cents: int
    created_at: str
    updated_at: str
    version: int


class AirlineSettlementLine(TypedDict, total=False):
    id: str
    annual_settlement_id: str
    airline_id: str
    actual_airfield_share_cents: int
    actual_terminal_share_cents: int
    billed_landing_cents: int
    billed_terminal_cents: int
    true_up_cents: int
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class PFCApplication(TypedDict, total=False):
    id: str
    fiscal_year_id: str
    airline_id: str
    enplaned_passengers: int
    pfc_amount_cents: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- common_fields: false — immutable event records (id + created_at only) ---

class ConsultationComment(TypedDict, total=False):
    id: str
    rates_setting_id: str
    airline_id: str
    body: str
    submitted_at: str
    created_at: str
    # deliberately NO updated_at, NO version


class ActivityRecord(TypedDict, total=False):
    id: str
    fiscal_year_id: str
    airline_id: str
    activity_date: str
    landed_weight_kg: int
    signature_status_at_activity: str
    billed_landing_fee_cents: int
    created_at: str
    # deliberately NO updated_at, NO version


class MIIVote(TypedDict, total=False):
    id: str
    capital_project_id: str
    airline_id: str
    ballot: str
    cast_at: str
    created_at: str
    # deliberately NO updated_at, NO version
