"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class RackStatus(str, Enum):
    OPEN = "OPEN"
    SHORTAGE = "SHORTAGE"
    FROZEN = "FROZEN"


class ProductFamily(str, Enum):
    GASOLINE = "GASOLINE"
    DIESEL = "DIESEL"
    JET = "JET"


class CreditStatus(str, Enum):
    GOOD = "GOOD"
    HOLD = "HOLD"


class PriceScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class LiftingRightStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class SupplyContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    DEFAULTED = "DEFAULTED"


class PricingTier(str, Enum):
    RACK = "RACK"
    RACK_MINUS_1 = "RACK_MINUS_1"
    RACK_MINUS_2 = "RACK_MINUS_2"


class ExchangeAgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AllocationMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    RATCHET = "RATCHET"


class AllocationNoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class LiftingTicketStatus(str, Enum):
    RESERVED = "RESERVED"
    BOL_ISSUED = "BOL_ISSUED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class JurisdictionLevel(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    COUNTY = "COUNTY"
    CITY = "CITY"


class TaxRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class BolEventType(str, Enum):
    RESERVED = "RESERVED"
    POSTED = "POSTED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class CreditHoldEventType(str, Enum):
    PLACED = "PLACED"
    RELEASED = "RELEASED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RACK_PRICE_ANALYST = "RackPriceAnalyst"
    ALLOCATION_MANAGER = "AllocationManager"
    TERMINAL_OPERATOR = "TerminalOperator"
    EXCHANGE_COORDINATOR = "ExchangeCoordinator"
    CREDIT_ANALYST = "CreditAnalyst"
    BILLING_CLERK = "BillingClerk"
    CONTRACT_ADMINISTRATOR = "ContractAdministrator"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).


class Terminal(TypedDict, total=False):
    id: str
    terminal_code: str
    legal_name: str
    state_code: str
    county_code: str
    city_code: str
    rack_status: str
    inventory_gallons: int
    daily_allocation_pool_gallons: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    product_code: str
    display_name: str
    product_family: str
    is_brandable: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    customer_code: str
    legal_name: str
    credit_limit_cents: int
    open_lifting_exposure_cents: int
    credit_status: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RackPriceSchedule(TypedDict, total=False):
    id: str
    terminal_id: str
    product_id: str
    effective_date: str
    posted_rack_cents_per_gal: int
    branded_premium_cents_per_gal: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiftingRight(TypedDict, total=False):
    id: str
    customer_id: str
    terminal_id: str
    product_id: str
    contract_id: str
    daily_ratable_gallons: int
    lifted_today_gallons: int
    reserved_gallons: int
    allocated_gallons: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyContract(TypedDict, total=False):
    id: str
    customer_id: str
    start_date: str
    end_date: str
    volume_commitment_gallons: int
    lifted_to_date_gallons: int
    pricing_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExchangeAgreement(TypedDict, total=False):
    id: str
    delivering_terminal_id: str
    receiving_supplier_code: str
    product_id: str
    monthly_exchange_cap_gallons: int
    delivered_this_month_gallons: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationNotice(TypedDict, total=False):
    id: str
    terminal_id: str
    effective_date: str
    total_pool_gallons: int
    allocation_method: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiftingTicket(TypedDict, total=False):
    id: str
    lifting_right_id: str
    customer_id: str
    terminal_id: str
    product_id: str
    requested_gallons: int
    branded: bool
    additive_package_code: Optional[str]
    unit_price_cents_per_gal: int
    additive_cost_cents: int
    tax_cents: int
    gross_cents: int
    bol_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxJurisdictionRule(TypedDict, total=False):
    id: str
    jurisdiction_level: str
    jurisdiction_code: str
    product_family: str
    rate_cents_per_gal: int
    effective_start_date: str
    effective_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit resources: id + created_at + occurred_at only (PRD §2.5);
# updated_at and version are absent from these records.


class BolEvent(TypedDict, total=False):
    id: str
    lifting_ticket_id: str
    event_type: str
    event_payload: dict
    occurred_at: str
    created_at: str


class CreditHoldLog(TypedDict, total=False):
    id: str
    customer_id: str
    event_type: str
    trigger_reason: str
    open_exposure_cents_at_event: int
    occurred_at: str
    created_at: str
