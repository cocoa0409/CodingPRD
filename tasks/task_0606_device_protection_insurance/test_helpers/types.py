"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SUBSCRIBER = "Subscriber"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    LOGISTICS_AGENT = "LogisticsAgent"


class RiskFlag(str, Enum):
    GREEN = "GREEN"
    WATCH = "WATCH"
    BLOCKED = "BLOCKED"


class EnrollmentStatus(str, Enum):
    PENDING_ELIGIBILITY = "PENDING_ELIGIBILITY"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class PremiumInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    ROUTED_REPAIR = "ROUTED_REPAIR"
    ROUTED_REPLACE = "ROUTED_REPLACE"
    FULFILLED = "FULFILLED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ClaimPeril(str, Enum):
    CRACKED = "CRACKED"
    LOST = "LOST"
    THEFT = "THEFT"


class ClaimRouting(str, Enum):
    REPAIR = "REPAIR"
    REPLACE = "REPLACE"


class DenialReason(str, Enum):
    FRAUD = "FRAUD"
    INELIGIBLE = "INELIGIBLE"
    LIMIT_EXCEEDED = "LIMIT_EXCEEDED"
    NO_COVERAGE = "NO_COVERAGE"


class FraudScreenOutcome(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class RepairOrderStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AdvancedExchangeStatus(str, Enum):
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURN_DUE = "RETURN_DUE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TradeInGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    EWASTE = "EWASTE"


class TradeInStatus(str, Enum):
    RECEIVED = "RECEIVED"
    GRADED = "GRADED"
    CREDITED = "CREDITED"
    RECYCLED = "RECYCLED"


# common_fields: true — id + created_at + updated_at + version
class Customer(TypedDict):
    id: str
    full_name: str
    carrier_account_number: str
    risk_flag: str
    lifetime_approved_claim_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — write-once reference artifact: only id + created_at
class Plan(TypedDict):
    id: str
    code: str
    monthly_premium_cents: int
    base_deductible_cents: int
    loss_deductible_multiplier_bps: int
    annual_claim_limit: int
    replacement_value_cap_cents: int
    created_at: str


# common_fields: false — write-once reference artifact: only id + created_at
class ReplacementSku(TypedDict):
    id: str
    model_name: str
    msrp_cents: int
    depreciation_rate_bps_per_month: int
    stock_on_hand: int
    created_at: str


# common_fields: true
class Enrollment(TypedDict):
    id: str
    customer_id: str
    plan_id: str
    imei: str
    device_model: str
    device_purchase_date: str
    replacement_sku_id: str
    status: str
    enrolled_at: Optional[str]
    premium_paid_through_cycle: int
    open_claim_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class PremiumInvoice(TypedDict):
    id: str
    enrollment_id: str
    cycle_index: int
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Claim(TypedDict):
    id: str
    enrollment_id: str
    peril: str
    incident_at: str
    police_report_number: Optional[str]
    status: str
    routing: Optional[str]
    deductible_cents: int
    replacement_value_cents: int
    net_payout_cents: int
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — write-once record artifact: only id + created_at
class FraudScreen(TypedDict):
    id: str
    claim_id: str
    customer_id: str
    velocity_count: int
    outcome: str
    created_at: str


# common_fields: true
class RepairOrder(TypedDict):
    id: str
    claim_id: str
    repair_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class AdvancedExchange(TypedDict):
    id: str
    claim_id: str
    replacement_sku_id: str
    status: str
    return_due_at: Optional[str]
    nonreturn_fee_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class TradeIn(TypedDict):
    id: str
    advanced_exchange_id: str
    condition_grade: str
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
