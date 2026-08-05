"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    BROKER_AGENT = "BrokerAgent"
    BROKER_MANAGER = "BrokerManager"
    SUPPLIER = "Supplier"
    CUSTOMER = "Customer"
    OPS_ADMIN = "OpsAdmin"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class UtilityAccountStatus(str, Enum):
    PENDING_LOA = "PENDING_LOA"
    VERIFIED = "VERIFIED"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"


class AuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class RfpStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    BEST_AND_FINAL = "BEST_AND_FINAL"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SHORTLISTED = "SHORTLISTED"
    AWARDED = "AWARDED"
    WITHDRAWN = "WITHDRAWN"
    VOID = "VOID"


class ContractStatus(str, Enum):
    PENDING_CUSTOMER = "PENDING_CUSTOMER"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ENROLLMENT_SUBMITTED = "ENROLLMENT_SUBMITTED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    DROPPED = "DROPPED"
    EXPIRED = "EXPIRED"
    RENEWED = "RENEWED"


class CommissionStatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    APPROVED = "APPROVED"
    TRUED_UP = "TRUED_UP"
    VOIDED = "VOIDED"


class CommissionBasis(str, Enum):
    ESTIMATED = "ESTIMATED"
    ACTUAL = "ACTUAL"


class DrStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    PERFORMED = "PERFORMED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class RateAlert(str, Enum):
    NONE = "NONE"
    RATE_DROP = "RATE_DROP"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Customer(TypedDict):
    id: str
    legal_name: str
    email: str
    segment: str
    service_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BrokerUser(TypedDict):
    id: str
    full_name: str
    email: str
    staff_role: str
    approval_limit_cents: int
    pipeline_commission_cents: int
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    name: str
    commodity: str
    service_states: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilityAccount(TypedDict):
    id: str
    customer_id: str
    broker_agent_id: str
    utility_name: str
    account_number: str
    commodity: str
    state_code: str
    estimated_annual_usage_kwh: int
    reserved_dr_kw: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Authorization(TypedDict):
    id: str
    account_id: str
    scope: str
    signed_at: Optional[str]
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# UsageRecord — common_fields: false, append-only: only id + created_at
class UsageRecord(TypedDict):
    id: str
    account_id: str
    period_month: str
    usage_kwh: int
    source: str
    is_actual: bool
    created_at: str


class Rfp(TypedDict):
    id: str
    account_id: str
    broker_agent_id: str
    term_months_requested: int
    green_pct_requested: int
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    rfp_id: str
    supplier_id: str
    rate_mills_per_kwh: int
    term_months: int
    green_pct: int
    broker_adder_mills: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    account_id: str
    quote_id: str
    supplier_id: str
    broker_agent_id: str
    renewed_from_contract_id: Optional[str]
    term_months: int
    rate_mills_per_kwh: int
    broker_adder_mills: int
    rec_adder_mills: int
    green_pct: int
    estimated_annual_usage_kwh: int
    start_date: str
    end_date: str
    requested_switch_date: str
    confirmed_switch_date: Optional[str]
    renewal_window_open: bool
    rate_alert: str
    latest_market_rate_mills: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict):
    id: str
    contract_id: str
    basis: str
    gross_commission_cents: int
    actual_gross_cents: Optional[int]
    true_up_delta_cents: Optional[int]
    clawback_cents: int
    net_commission_cents: int
    approved_by_manager_id: Optional[str]
    trued_up_by_manager_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DemandResponseEnrollment(TypedDict):
    id: str
    account_id: str
    program_name: str
    season_start: str
    season_end: str
    committed_kw: int
    incentive_per_kw_cents: int
    performed_kw: Optional[int]
    provisional_incentive_cents: int
    settled_incentive_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
