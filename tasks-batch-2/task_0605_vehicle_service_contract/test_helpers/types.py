"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ADMIN_UNDERWRITER = "AdminUnderwriter"
    CONTRACT_ADMIN = "ContractAdmin"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    REPAIR_FACILITY = "RepairFacility"
    AUDITOR = "Auditor"


class CoveragePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ReinsurancePoolStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class AncillaryProductStatus(str, Enum):
    BUNDLED = "BUNDLED"
    REFUNDED = "REFUNDED"
    CLAIMED = "CLAIMED"


class RepairFacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClaimAdjudicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ClaimPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    VOID = "VOID"


class RepairAuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    DISBURSED = "DISBURSED"
    REVERSED = "REVERSED"


class CancellationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REFUNDED = "REFUNDED"
    REJECTED = "REJECTED"


# --- Entities carrying the full common-field set (id, created_at, updated_at, version) ---

class CoveragePlan(TypedDict):
    id: str
    name: str
    tier: str
    term_months: int
    term_miles: int
    max_vehicle_age_years: int
    max_odometer_at_sale: int
    base_premium_cents: int
    deductible_cents: int
    labor_rate_cap_cents_per_hour: int
    rental_benefit_cents_per_day: int
    rental_max_days: int
    towing_benefit_cents: int
    reinsurance_cession_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ReinsurancePool(TypedDict):
    id: str
    name: str
    ceded_premium_cents: int
    paid_loss_cents: int
    reserve_held_cents: int
    surplus_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    coverage_plan_id: str
    reinsurance_pool_id: str
    vin: str
    vehicle_model_year: int
    odometer_at_sale: int
    sale_date: str
    sale_price_cents: int
    financed: bool
    finance_term_months: int
    earned_premium_cents: int
    paid_claim_total_cents: int
    cancellation_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AncillaryProduct(TypedDict):
    id: str
    contract_id: str
    product_type: str
    premium_cents: int
    gap_cap_cents: int
    refundable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairFacility(TypedDict):
    id: str
    name: str
    posted_labor_rate_cents_per_hour: int
    network_status: str
    direct_pay_enrolled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    contract_id: str
    repair_facility_id: str
    reinsurance_pool_id: str
    odometer_at_claim: int
    claim_date: str
    complaint: str
    requested_amount_cents: int
    adjudicated_amount_cents: int
    rental_days_claimed: int
    towing_claimed: bool
    reserve_cents: int
    adjudication_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict):
    id: str
    claim_id: str
    line_type: str
    part_number: Optional[str]
    requested_amount_cents: int
    labor_hours: float
    covered: bool
    allowed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class RepairAuthorization(TypedDict):
    id: str
    claim_id: str
    repair_facility_id: str
    covered_repair_cents: int
    deductible_applied_cents: int
    rental_payout_cents: int
    towing_payout_cents: int
    total_payout_cents: int
    pay_target: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Cancellation(TypedDict):
    id: str
    contract_id: str
    reason: str
    request_date: str
    refund_basis: str
    gross_refund_cents: int
    cancellation_fee_cents: int
    claims_offset_cents: int
    net_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only / singleton records: only id + created_at ---

class LedgerEntry(TypedDict):
    id: str
    reinsurance_pool_id: str
    contract_id: Optional[str]
    entry_type: str
    amount_cents: int
    memo: str
    created_at: str


class ClockState(TypedDict):
    id: str
    current_utc: str
    created_at: str
