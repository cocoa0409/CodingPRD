"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the Roll-Off Dumpster Rental PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles (PRD §2.1) ---
class UserRole(str, Enum):
    CONTRACTOR = "Contractor"
    DISPATCHER = "Dispatcher"
    YARD_ADMIN = "YardAdmin"
    SCALE_OPERATOR = "ScaleOperator"
    PERMIT_OFFICER = "PermitOfficer"
    BILLING_CLERK = "BillingClerk"


# --- Status enums ---
class ContainerStatus(str, Enum):
    IN_YARD = "IN_YARD"
    ASSIGNED = "ASSIGNED"
    ON_SITE = "ON_SITE"
    AWAITING_DUMP = "AWAITING_DUMP"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RouteStatus(str, Enum):
    PLANNING = "PLANNING"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class OrderLogisticsStatus(str, Enum):
    BOOKED = "BOOKED"
    SCHEDULED = "SCHEDULED"
    ON_SITE = "ON_SITE"
    AWAITING_PICKUP = "AWAITING_PICKUP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    ESTIMATED = "ESTIMATED"
    FINALIZED = "FINALIZED"


class StopType(str, Enum):
    DELIVERY = "DELIVERY"
    SWAP = "SWAP"
    PICKUP = "PICKUP"


class StopStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class ContaminationKind(str, Enum):
    NONE = "NONE"
    TIRES = "TIRES"
    APPLIANCES = "APPLIANCES"
    HAZMAT = "HAZMAT"


class SizeCode(str, Enum):
    YD10 = "YD10"
    YD20 = "YD20"
    YD30 = "YD30"
    YD40 = "YD40"


# --- Entity TypedDicts ---
# Entities carrying the full id/created_at/updated_at/version triple.
class ContainerType(TypedDict):
    id: str
    size_code: str
    base_rate_cents: int
    included_days: int
    overage_day_cents: int
    included_tonnage_lbs: int
    overage_rate_cents_per_lb: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class ContractorAccount(TypedDict):
    id: str
    business_name: str
    credit_limit_cents: int
    outstanding_cents: int
    available_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict):
    id: str
    container_type_id: str
    asset_tag: str
    yard_code: str
    status: str
    current_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    service_date: str
    truck_code: str
    capacity_stops: int
    stop_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalOrder(TypedDict):
    id: str
    account_id: str
    container_type_id: str
    container_id: Optional[str]
    site_address: str
    requested_delivery_date: str
    delivered_on: Optional[str]
    picked_up_on: Optional[str]
    rental_days: int
    requires_street_permit: bool
    logistics_status: str
    billing_status: str
    estimated_total_cents: int
    final_total_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceStop(TypedDict):
    id: str
    order_id: str
    route_id: Optional[str]
    stop_type: str
    sequence: Optional[int]
    estimated_weight_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StreetPermit(TypedDict):
    id: str
    order_id: str
    municipality: str
    permit_fee_cents: int
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    order_id: str
    account_id: str
    base_cents: int
    overage_day_cents: int
    tonnage_cents: int
    permit_cents: int
    contamination_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only entities — id + created_at only, NO updated_at, NO version.
class WeighTicket(TypedDict):
    id: str
    order_id: str
    service_stop_id: str
    gross_weight_lbs: int
    tare_weight_lbs: int
    net_weight_lbs: int
    contaminated: bool
    contamination_kind: str
    created_at: str


class ClockState(TypedDict):
    id: str
    current_date: str
    created_at: str
