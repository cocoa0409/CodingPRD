"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class ClinicStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProductStatus(str, Enum):
    LISTED = "LISTED"
    DISCONTINUED = "DISCONTINUED"


class ProductType(str, Enum):
    RX_PHARMACEUTICAL = "RX_PHARMACEUTICAL"
    VACCINE = "VACCINE"
    EQUIPMENT = "EQUIPMENT"
    CONSUMABLE = "CONSUMABLE"


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    BACKORDERED = "BACKORDERED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class BackorderLineStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    PREPARING = "PREPARING"
    IN_TRANSIT = "IN_TRANSIT"
    QUARANTINED = "QUARANTINED"
    DELIVERED = "DELIVERED"
    DESTROYED = "DESTROYED"


class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    FINALIZED = "FINALIZED"


class AccrualStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    REVERSED = "REVERSED"


class CreditStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CREDITED = "CREDITED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class UserRole(str, Enum):
    CLINIC_BUYER = "ClinicBuyer"
    ACCOUNT_MANAGER = "AccountManager"
    SUPPLY_CHAIN_PLANNER = "SupplyChainPlanner"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SYSTEM_ADMIN = "SystemAdmin"


# All resources carry the common system-managed fields of PRD §2.5:
# id, created_at, updated_at, version.


class Clinic(TypedDict, total=False):
    id: str
    clinic_name: str
    license_number: str
    dea_registration_number: Optional[str]
    ship_to_address: str
    status: str
    credit_limit_cents: int
    credit_used_cents: int
    minimum_order_value_cents: int
    delivery_frequency_per_week: int
    free_freight_threshold_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    product_name: str
    manufacturer_code: str
    product_type: str
    is_controlled_substance: bool
    requires_cold_chain: bool
    unit_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ManufacturerAuthorization(TypedDict, total=False):
    id: str
    clinic_id: str
    manufacturer_code: str
    valid_from: str
    valid_until: str
    approved_ship_to_address: str
    quarterly_quantity_cap: int
    quantity_approved_this_quarter: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    product_id: str
    lot_number: str
    expiry_date: str
    qty_on_hand: int
    qty_allocated: int
    qty_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    clinic_id: str
    ship_to_address: str
    delivery_window_start: str
    delivery_window_end: str
    status: str
    merchandise_subtotal_cents: Optional[int]
    bundle_discount_cents: Optional[int]
    merchandise_net_cents: Optional[int]
    equipment_surcharge_cents: Optional[int]
    freight_fee_cents: Optional[int]
    total_cents: Optional[int]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    qty_requested: int
    qty_allocated: int
    lot_id: Optional[str]
    unit_price_cents: Optional[int]
    line_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BackorderLine(TypedDict, total=False):
    id: str
    order_line_id: str
    qty_open: int
    allocation_sequence: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TemperatureReading(TypedDict, total=False):
    recorded_at: str
    temperature_celsius: float


class Shipment(TypedDict, total=False):
    id: str
    order_id: str
    carrier_name: str
    carrier_cold_chain_certified: bool
    requires_cold_chain: bool
    temperature_log: List[TemperatureReading]
    has_unresolved_excursion: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BundleProgram(TypedDict, total=False):
    id: str
    program_name: str
    manufacturer_code: str
    qualifying_product_types: List[str]
    min_distinct_categories: int
    bundle_discount_pct: int
    rebate_base_rate_bp: int
    rebate_bonus_rate_bp: int
    bonus_threshold_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BundleEnrollment(TypedDict, total=False):
    id: str
    clinic_id: str
    program_id: str
    quarter: str
    status: str
    qtd_qualifying_cents: int
    created_at: str
    updated_at: str
    version: int


class RebateAccrual(TypedDict, total=False):
    id: str
    enrollment_id: str
    order_id: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShortDateCredit(TypedDict, total=False):
    id: str
    clinic_id: str
    order_line_id: str
    lot_id: str
    qty: int
    days_to_expiry_at_request: int
    claimed_credit_cents: int
    final_credit_cents: Optional[int]
    received_qty: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
