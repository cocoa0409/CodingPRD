"""Domain types: entity TypedDicts, status enums, role enum for the Marine Dealer API."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    MANAGER = "Manager"
    SALES_REP = "SalesRep"
    SERVICE_ADVISOR = "ServiceAdvisor"
    PARTS_CLERK = "PartsClerk"


class UnitStatus(str, Enum):
    INTAKE = "INTAKE"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class FloorPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CURTAILED = "CURTAILED"
    PAID_OFF = "PAID_OFF"
    SUPERSEDED = "SUPERSEDED"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    FUNDED = "FUNDED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ConsignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    RETURNED = "RETURNED"


class RepairOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    INVOICED = "INVOICED"


class ServiceLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"
    CONSUMED = "CONSUMED"


class BerthStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class SlipReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


# All entities carry common_fields: id, created_at, updated_at, version.

class Unit(TypedDict):
    id: str
    hin: str
    make: str
    model: str
    model_year: int
    unit_type: str
    length_ft: float
    cost_cents: int
    list_price_cents: int
    acquisition_type: str
    open_recall: bool
    status: str
    warranty_registered: bool
    aging_days: int
    floor_plan_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class FloorPlan(TypedDict):
    id: str
    unit_id: str
    lender_name: str
    principal_cents: int
    outstanding_principal_cents: int
    apr_bps: int
    advanced_at: str
    curtailment_pct_bps: int
    status: str
    accrued_interest_cents: int
    payoff_cents: int
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict):
    id: str
    unit_id: str
    customer_name: str
    sale_price_cents: int
    financing_type: str
    tax_rate_bps: int
    doc_fee_cents: int
    down_payment_cents: int
    trade_allowance_cents: int
    trade_lien_payoff_cents: int
    status: str
    trade_equity_cents: int
    tax_cents: int
    amount_due_cents: int
    created_at: str
    updated_at: str
    version: int


class Consignment(TypedDict):
    id: str
    unit_id: str
    consignor_name: str
    agreed_floor_cents: int
    commission_bps: int
    status: str
    payout_cents: int
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    unit_id: str
    service_bay_id: str
    customer_name: str
    ro_type: str
    flat_rate_code: Optional[str]
    flat_rate_hours: Optional[float]
    flat_rate_parts_cents: Optional[int]
    estimated_hours: Optional[float]
    labor_rate_cents_per_hour: int
    tax_rate_bps: int
    scheduled_start: str
    scheduled_end: str
    status: str
    estimate_total_cents: int
    final_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ServiceLine(TypedDict):
    id: str
    repair_order_id: str
    line_type: str
    part_id: Optional[str]
    hours: Optional[float]
    quantity: Optional[int]
    unit_price_cents: Optional[int]
    warranty_covered: bool
    status: str
    extended_cents: int
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict):
    id: str
    sku: str
    name: str
    on_hand_qty: int
    unit_cost_cents: int
    list_price_cents: int
    reorder_point: int
    reserved_qty: int
    available_qty: int
    is_low: bool
    created_at: str
    updated_at: str
    version: int


class Berth(TypedDict):
    id: str
    berth_code: str
    berth_type: str
    max_length_ft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceBay(TypedDict):
    id: str
    bay_code: str
    bay_type: str
    created_at: str
    updated_at: str
    version: int


class SlipReservation(TypedDict):
    id: str
    berth_id: str
    unit_id: str
    start_date: str
    end_date: str
    daily_rate_cents: int
    status: str
    nights: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int
