"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD exactly. Every entity in this domain is mutable
and carries the full complement of id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles -----------------------------------------------------------------
class UserRole(str, Enum):
    SHIPPER_OPS = "ShipperOps"
    CARRIER_OPS = "CarrierOps"
    DOCK_OPS = "DockOps"
    FREIGHT_AUDITOR = "FreightAuditor"


# --- Status enums ----------------------------------------------------------
class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CarrierGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    PROBATION = "PROBATION"


class ContractRateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    PLANNED = "PLANNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ShipmentTenderStatus(str, Enum):
    UNTENDERED = "UNTENDERED"
    TENDERED = "TENDERED"
    BOOKED = "BOOKED"


class ShipmentExecutionStatus(str, Enum):
    PENDING = "PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TenderStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class LoadStatus(str, Enum):
    BUILDING = "BUILDING"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class DockAppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class FreightInvoiceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    AUDITED = "AUDITED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class TransportMode(str, Enum):
    TL = "TL"
    LTL = "LTL"
    PARCEL = "PARCEL"
    INTERMODAL = "INTERMODAL"


class ClaimType(str, Enum):
    OSD_SHORTAGE = "OSD_SHORTAGE"
    OSD_OVERAGE = "OSD_OVERAGE"
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"


# --- Entity TypedDicts (all common_fields: true) ---------------------------
class Carrier(TypedDict):
    id: str
    name: str
    scac: str
    mode: str
    status: str
    delivered_count: int
    on_time_count: int
    claim_count: int
    on_time_pct: Optional[float]
    scorecard_grade: str
    created_at: str
    updated_at: str
    version: int


class ContractRate(TypedDict):
    id: str
    carrier_id: str
    mode: str
    origin_zone: str
    dest_zone: str
    base_rate_per_mile_cents: int
    min_charge_cents: int
    fuel_surcharge_pct: float
    effective_start_minute: int
    effective_end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_ref: str
    origin_zone: str
    dest_zone: str
    weight_lbs: int
    declared_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    mode: str
    distance_miles: int
    weight_lbs: int
    load_id: Optional[str]
    assigned_carrier_id: Optional[str]
    contract_rate_id: Optional[str]
    quoted_cost_cents: Optional[int]
    audited_cost_cents: Optional[int]
    promised_eta_minute: int
    actual_delivery_minute: Optional[int]
    tender_status: str
    execution_status: str
    created_at: str
    updated_at: str
    version: int


class Tender(TypedDict):
    id: str
    shipment_id: str
    carrier_id: Optional[str]
    contract_rate_id: Optional[str]
    offered_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Load(TypedDict):
    id: str
    carrier_id: str
    planned_capacity_lbs: int
    consolidated_weight_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DockAppointment(TypedDict):
    id: str
    load_id: str
    dock_door: str
    start_minute: int
    end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FreightInvoice(TypedDict):
    id: str
    shipment_id: str
    invoiced_linehaul_cents: int
    invoiced_accessorial_codes: List[str]
    variance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    shipment_id: str
    claim_type: str
    claimed_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
