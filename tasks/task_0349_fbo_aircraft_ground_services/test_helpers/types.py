"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the common server-managed fields id, created_at,
updated_at, and version (see PRD §2.4), so every TypedDict below lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status / enum types ──────────────────────────────────────────────

class OperatorAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FuelType(str, Enum):
    JET_A = "JET_A"
    AVGAS = "AVGAS"


class WeightClass(str, Enum):
    LIGHT = "LIGHT"
    MID = "MID"
    HEAVY = "HEAVY"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class ServiceVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_GROUND = "ON_GROUND"
    SERVICING = "SERVICING"
    READY_FOR_DEPARTURE = "READY_FOR_DEPARTURE"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class SpotType(str, Enum):
    HANGAR = "HANGAR"
    TIE_DOWN = "TIE_DOWN"
    RAMP = "RAMP"


class SpotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ParkingAssignmentStatus(str, Enum):
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"


class FuelOrderLogisticsStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    FUELED = "FUELED"
    CANCELLED = "CANCELLED"


class FuelOrderReconciliationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RECONCILED = "RECONCILED"
    IN_REVIEW = "IN_REVIEW"
    ADJUSTED = "ADJUSTED"


class IntoPlaneOutcome(str, Enum):
    RECONCILED = "RECONCILED"
    FLAGGED = "FLAGGED"


class RampServiceType(str, Enum):
    LAVATORY = "LAVATORY"
    GPU = "GPU"
    DE_ICE = "DE_ICE"
    CREW_CAR = "CREW_CAR"
    CATERING = "CATERING"


class RampServiceStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeiceFluidType(str, Enum):
    TYPE_I = "TYPE_I"
    TYPE_IV = "TYPE_IV"


class RampSlotStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"
    USED = "USED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    VOID = "VOID"


class UserRole(str, Enum):
    OPS_DISPATCHER = "OpsDispatcher"
    FUEL_TECH = "FuelTech"
    BILLING_CLERK = "BillingClerk"
    LINE_MANAGER = "LineManager"
    OPERATOR = "Operator"


# ─── Entity TypedDicts (all common_fields: true → id/created_at/updated_at/version) ──

class Operator(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    account_status: str
    jeta_month_cumulative_gallons: int
    open_invoice_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    operator_id: str
    tail_number: str
    fuel_type: str
    mtow_lb: int
    weight_class: str
    created_at: str
    updated_at: str
    version: int


class FuelContract(TypedDict):
    id: str
    operator_id: str
    product: str
    base_price_cents_per_gal: int
    tankering_fee_cents_per_gal: int
    contract_status: str
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict):
    id: str
    operator_id: str
    aircraft_id: str
    arrival_utc: str
    departure_utc: str
    nights: int
    status: str
    services_outstanding: int
    created_at: str
    updated_at: str
    version: int


class ParkingAssignment(TypedDict):
    id: str
    service_visit_id: str
    spot_id: str
    occupy_start_utc: str
    occupy_end_utc: str
    status: str
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ParkingSpot(TypedDict):
    id: str
    label: str
    spot_type: str
    max_weight_class: str
    spot_status: str
    created_at: str
    updated_at: str
    version: int


class FuelOrder(TypedDict):
    id: str
    service_visit_id: str
    aircraft_id: str
    fuel_contract_id: str
    product: str
    ordered_gallons: int
    tankering: bool
    logistics_status: str
    reconciliation_status: str
    priced_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class IntoPlaneTicket(TypedDict):
    id: str
    fuel_order_id: str
    delivered_gallons: int
    variance_gallons: int
    variance_pct: float
    outcome: str
    created_at: str
    updated_at: str
    version: int


class RampService(TypedDict):
    id: str
    service_visit_id: str
    service_type: str
    status: str
    deice_fluid_gallons: int
    deice_fluid_type: Optional[str]
    deice_holdover_minutes: int
    charge_cents: int
    created_at: str
    updated_at: str
    version: int


class RampSlot(TypedDict):
    id: str
    service_visit_id: str
    pad_id: str
    window_start_utc: str
    window_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    operator_id: str
    service_visit_id: str
    total_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
