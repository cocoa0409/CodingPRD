"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the PRD's entity surface. Entities that carry only `id` + `created_at`
(ServiceAddress, ServicePlan, UsageRecord, AccountCredit per PRD §2.4) omit
`updated_at` and `version`.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum ---
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    PROVISIONING_AGENT = "ProvisioningAgent"
    NETWORK_OPS = "NetworkOps"
    DISPATCHER = "Dispatcher"


# --- Status enums ---
class AccountStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISCONNECTED = "DISCONNECTED"
    TRANSFERRED = "TRANSFERRED"


class ServiceState(str, Enum):
    PROVISIONING = "PROVISIONING"
    ONLINE = "ONLINE"
    THROTTLED = "THROTTLED"
    OFFLINE = "OFFLINE"


class CoverageStatus(str, Enum):
    SERVICEABLE = "SERVICEABLE"
    NOT_SERVICEABLE = "NOT_SERVICEABLE"
    PRE_ORDER = "PRE_ORDER"


class Technology(str, Enum):
    FIBER = "FIBER"
    CABLE = "CABLE"
    DSL = "DSL"
    FIXED_WIRELESS = "FIXED_WIRELESS"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    GIG = "GIG"
    MULTI_GIG = "MULTI_GIG"


class OveragePolicy(str, Enum):
    BILL = "BILL"
    THROTTLE = "THROTTLE"
    UNLIMITED = "UNLIMITED"


class EquipmentKind(str, Enum):
    MODEM = "MODEM"
    ROUTER = "ROUTER"
    GATEWAY = "GATEWAY"


class EquipmentStatus(str, Enum):
    IN_INVENTORY = "IN_INVENTORY"
    LEASED = "LEASED"
    RETURN_PENDING = "RETURN_PENDING"
    RETURNED = "RETURNED"
    LOST = "LOST"


class OrderType(str, Enum):
    NEW_INSTALL = "NEW_INSTALL"
    TRANSFER_IN = "TRANSFER_IN"
    UPGRADE = "UPGRADE"


class InstallMode(str, Enum):
    TECH_INSTALL = "TECH_INSTALL"
    SELF_INSTALL = "SELF_INSTALL"


class ServiceOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    KIT_SHIPPED = "KIT_SHIPPED"
    ACTIVATED = "ACTIVATED"
    CANCELLED = "CANCELLED"


class InstallSlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class InstallAppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BillingState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FINALIZED = "FINALIZED"


class ThrottleState(str, Enum):
    UNCAPPED = "UNCAPPED"
    THROTTLED = "THROTTLED"


class OutageStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    CREDITED = "CREDITED"
    DISMISSED = "DISMISSED"


class CreditSourceType(str, Enum):
    OUTAGE = "OUTAGE"
    LEASE_PRORATE = "LEASE_PRORATE"
    GOODWILL = "GOODWILL"
    TRANSFER_WAIVER = "TRANSFER_WAIVER"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts ---

# common_fields: false — only id + created_at
class ServiceAddress(TypedDict):
    id: str
    created_at: str
    line1: str
    postal_code: str
    coverage_status: str
    technology: str
    max_serviceable_mbps: int
    self_install_eligible: bool


# common_fields: false — only id + created_at
class ServicePlan(TypedDict):
    id: str
    created_at: str
    code: str
    tier: str
    download_mbps: int
    throttled_mbps: int
    monthly_fee_cents: int
    included_gb: int
    overage_policy: str
    contract_term_months: int
    etf_full_cents: int


# common_fields: true
class Account(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    service_address_id: str
    plan_id: str
    customer_user_id: str
    status: str
    service_state: str
    contract_start_iso: Optional[str]
    credit_balance_cents: int
    equipment_unit_id: Optional[str]


# common_fields: true
class EquipmentUnit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    account_id: Optional[str]
    kind: str
    serial: str
    lease_fee_cents_per_cycle: int
    status: str
    leased_at_iso: Optional[str]


# common_fields: true
class ServiceOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    account_id: str
    order_type: str
    install_mode: str
    requested_plan_id: str
    equipment_unit_id: Optional[str]
    status: str


# common_fields: true
class InstallSlot(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    technician_id: str
    window_start_iso: str
    window_end_iso: str
    capacity: int
    booked_count: int
    status: str


# common_fields: true
class Technician(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    travel_buffer_minutes: int
    active: bool


# common_fields: true
class InstallAppointment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    service_order_id: str
    install_slot_id: str
    technician_id: str
    start_iso: str
    end_iso: str
    status: str


# common_fields: true
class BillingCycle(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    account_id: str
    cycle_start_iso: str
    cycle_end_iso: str
    usage_gb: int
    billing_state: str
    throttle_state: str
    overage_charge_cents: int
    total_due_cents: int


# common_fields: false — only id + created_at
class UsageRecord(TypedDict):
    id: str
    created_at: str
    account_id: str
    billing_cycle_id: str
    posted_at_iso: str
    gb: int


# common_fields: true
class OutageEvent(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    account_id: str
    billing_cycle_id: str
    started_at_iso: str
    ended_at_iso: Optional[str]
    duration_minutes: int
    status: str


# common_fields: false — only id + created_at
class AccountCredit(TypedDict):
    id: str
    created_at: str
    account_id: str
    source_type: str
    source_id: Optional[str]
    amount_cents: int
    applied: bool


# common_fields: true
class TransferRequest(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    account_id: str
    to_service_address_id: str
    to_plan_id: str
    waive_etf: bool
    status: str
