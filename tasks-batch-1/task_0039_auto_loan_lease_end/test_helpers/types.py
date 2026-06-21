"""Domain types: entity TypedDicts, status enums, role enum.

All field names and states are taken verbatim from the PRD for the
Auto Loan & Lease End API.
"""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    FINANCE_MANAGER = "FinanceManager"
    BORROWER = "Borrower"
    AUDITOR = "Auditor"


class FicoTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FINANCED = "FINANCED"


class LoanStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"
    PAID_OFF = "PAID_OFF"


class LeaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MATURING = "MATURING"
    RETURNED = "RETURNED"
    PURCHASED = "PURCHASED"
    RENEWED = "RENEWED"
    SETTLED = "SETTLED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    MISSED = "MISSED"


class PaymentKind(str, Enum):
    SCHEDULED = "SCHEDULED"
    LATE_FEE = "LATE_FEE"
    PAYOFF = "PAYOFF"


class SettlementElection(str, Enum):
    RETURN = "RETURN"
    PURCHASE = "PURCHASE"
    RENEW = "RENEW"


# --- common_fields: true — id + created_at + updated_at + version ---

class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    fico_score: int
    fico_tier: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    vin: str
    make_model: str
    msrp_cents: int
    sale_price_cents: int
    residual_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    name: str
    tier_1_min_fico: int
    tier_2_min_fico: int
    tier_3_min_fico: int
    tier_1_apr: float
    tier_2_apr: float
    tier_3_apr: float
    tier_4_apr: float
    lease_money_factor: float
    default_rate_apr: float
    lease_tax_rate: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    customer_id: str
    vehicle_id: str
    rate_card_id: str
    down_payment_cents: int
    term_months: int
    gap_insurance: bool
    financed_principal_cents: int
    apr: float
    monthly_payment_cents: int
    payments_made_count: int
    principal_balance_cents: int
    missed_payment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict):
    id: str
    customer_id: str
    vehicle_id: str
    rate_card_id: str
    down_payment_cents: int
    term_months: int
    annual_mileage_allowance: int
    per_mile_overage_rate_cents: float
    disposition_fee_cents: int
    purchase_option_fee_cents: int
    gap_insurance: bool
    adjusted_cap_cost_cents: int
    base_monthly_cents: int
    monthly_payment_cents: int
    odometer_miles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseEndSettlement(TypedDict):
    id: str
    lease_id: str
    election: str
    odometer_miles: int
    per_year_excess_miles: List[int]
    renew_term_months: Optional[int]
    mileage_overage_cents: int
    disposition_charge_cents: int
    purchase_amount_cents: int
    total_due_cents: int
    renewed_lease_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- common_fields: false — append-only event: only id + created_at ---

class Payment(TypedDict):
    id: str
    loan_id: str
    amount_cents: int
    kind: str
    status: str
    late_fee_cents: int
    created_at: str
