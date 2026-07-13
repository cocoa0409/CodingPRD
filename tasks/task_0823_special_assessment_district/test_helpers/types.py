"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    DISTRICT_ADMINISTRATOR = "DistrictAdministrator"
    COUNTY_TREASURER = "CountyTreasurer"
    PARCEL_OWNER = "ParcelOwner"
    AUDITOR = "Auditor"


class DistrictStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PROTEST_PERIOD = "PROTEST_PERIOD"
    FORMED = "FORMED"
    ABANDONED = "ABANDONED"


class ParcelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUBDIVIDED = "SUBDIVIDED"
    PAID_OFF = "PAID_OFF"
    IN_FORECLOSURE = "IN_FORECLOSURE"
    WITHDRAWN = "WITHDRAWN"


class RollStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SUPERSEDED = "SUPERSEDED"


class BondStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    ISSUED = "ISSUED"
    CALLED = "CALLED"
    RETIRED = "RETIRED"
    DEFAULTED = "DEFAULTED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    PAID = "PAID"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    QUOTED = "QUOTED"
    HONORED = "HONORED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class LienStatus(str, Enum):
    RECORDED = "RECORDED"
    RELEASED = "RELEASED"
    FORECLOSED = "FORECLOSED"


class LienType(str, Enum):
    ASSESSMENT = "ASSESSMENT"
    DELINQUENCY = "DELINQUENCY"


class ForeclosureStatus(str, Enum):
    INITIATED = "INITIATED"
    NOTICED = "NOTICED"
    JUDGMENT = "JUDGMENT"
    SALE = "SALE"
    REDEEMED = "REDEEMED"
    CANCELLED = "CANCELLED"


class FormationMethod(str, Enum):
    BENEFIT_UNITS = "BENEFIT_UNITS"
    FRONT_FOOTAGE = "FRONT_FOOTAGE"
    LAND_AREA = "LAND_AREA"


# ---- Entity TypedDicts ----
# Mutable resources carry id + created_at + updated_at + version.

class AssessmentDistrict(TypedDict, total=False):
    id: str
    name: str
    formation_method: str
    total_project_cost_cents: int
    incidental_cost_cents: int
    protest_threshold_pct: float
    status: str
    total_benefit_units: float
    total_apportioned_principal_cents: Optional[int]
    formed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict, total=False):
    id: str
    district_id: str
    parent_parcel_id: Optional[str]
    apn: str
    owner_name: str
    land_area_sqft: float
    front_footage_ft: float
    benefit_units: float
    assessed_principal_cents: int
    remaining_principal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AssessmentRoll(TypedDict, total=False):
    id: str
    district_id: str
    method: str
    status: str
    total_apportioned_cents: int
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImprovementBond(TypedDict, total=False):
    id: str
    district_id: str
    coupon_rate_bps: int
    term_years: int
    issuance_date: str
    reserve_fund_pct: float
    reserve_fund_cents: int
    issuance_cost_cents: int
    admin_fee_bps: int
    prepayment_premium_pct: float
    par_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict, total=False):
    id: str
    parcel_id: str
    bond_id: str
    installment_year: int
    due_date: str
    principal_cents: int
    interest_cents: int
    admin_fee_cents: int
    penalty_cents: int
    redemption_interest_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoffQuote(TypedDict, total=False):
    id: str
    parcel_id: str
    quote_mode: str
    quote_date: str
    remaining_principal_cents: int
    accrued_interest_cents: int
    prepayment_premium_cents: int
    reserve_credit_cents: int
    total_payoff_cents: int
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lien(TypedDict, total=False):
    id: str
    parcel_id: str
    lien_type: str
    amount_cents: int
    recorded_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ForeclosureAction(TypedDict, total=False):
    id: str
    parcel_id: str
    delinquent_installment_count: int
    delinquent_amount_cents: int
    redemption_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only records: id + created_at ONLY (no updated_at, no version).

class ProtestFiling(TypedDict, total=False):
    id: str
    parcel_id: str
    filed_by: str
    weight_units: float
    created_at: str


class Payment(TypedDict, total=False):
    id: str
    installment_id: str
    amount_cents: int
    payment_date: str
    paid_by: str
    reversed: bool
    reversed_at: Optional[str]
    created_at: str
