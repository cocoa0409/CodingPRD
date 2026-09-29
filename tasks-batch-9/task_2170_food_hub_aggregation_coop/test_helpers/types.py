"""Domain types for the Food Hub Aggregation Cooperative API.

Entity TypedDicts, status enums and the cooperative role enum, all named
exactly as the PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    HUB_ADMIN = "HubAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PRODUCER = "Producer"
    BUYER = "Buyer"
    BOARD_DIRECTOR = "BoardDirector"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ProducerOnboardingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class FoodSafetyTier(str, Enum):
    TIER_NONE = "TIER_NONE"
    TIER_BASIC = "TIER_BASIC"
    TIER_AUDITED = "TIER_AUDITED"


class DocumentType(str, Enum):
    GAP_AUDIT = "GAP_AUDIT"
    LIABILITY_INSURANCE = "LIABILITY_INSURANCE"
    HACCP_PLAN = "HACCP_PLAN"
    ORGANIC_CERT = "ORGANIC_CERT"
    WATER_TEST = "WATER_TEST"


class DocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class UnitOfMeasure(str, Enum):
    CASE = "CASE"
    LB = "LB"
    EACH = "EACH"


class StorageClass(str, Enum):
    AMBIENT = "AMBIENT"
    CHILL = "CHILL"
    FROZEN = "FROZEN"


class BuyerType(str, Enum):
    SCHOOL_DISTRICT = "SCHOOL_DISTRICT"
    HOSPITAL = "HOSPITAL"
    UNIVERSITY = "UNIVERSITY"
    CORRECTIONS = "CORRECTIONS"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    AGGREGATED = "AGGREGATED"
    SCHEDULED = "SCHEDULED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"


class SettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    SHORT = "SHORT"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    STAGED = "STAGED"
    DELIVERED = "DELIVERED"
    SHORT_CLOSED = "SHORT_CLOSED"
    REVERSED = "REVERSED"


class DockSlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class RiskClass(str, Enum):
    RAW_ANIMAL = "RAW_ANIMAL"
    PRODUCE = "PRODUCE"
    READY_TO_EAT = "READY_TO_EAT"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    RECEIVED = "RECEIVED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADED = "LOADED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"


class RejectionReasonCode(str, Enum):
    TEMP_ABUSE = "TEMP_ABUSE"
    DAMAGE = "DAMAGE"
    SPEC_MISMATCH = "SPEC_MISMATCH"
    SHORT_COUNT = "SHORT_COUNT"
    LATE_DELIVERY = "LATE_DELIVERY"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class CycleStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RATIFIED = "RATIFIED"
    DISTRIBUTED = "DISTRIBUTED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Entity shapes.  The PRD states that all twelve entity types carry id,
# created_at, updated_at and version.
# --------------------------------------------------------------------------
class Producer(TypedDict):
    id: str
    legal_name: str
    region_code: str
    contact_email: str
    onboarding_status: str
    food_safety_tier: str
    compliance_ok: bool
    review_cycles: int
    suspension_count: int
    paid_in_capital_cents: int
    voting_shares: int
    patronage_volume_cents: int
    shrink_charge_cents: int
    retained_patronage_cents: int
    created_at: str
    updated_at: str
    version: int


class ProducerDocument(TypedDict):
    id: str
    producer_id: str
    doc_type: str
    issued_on: str
    expires_on: str
    status: str
    adjudicated_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    producer_id: str
    commodity_code: str
    unit_of_measure: str
    storage_class: str
    pack_weight_lb: float
    units_per_pallet: int
    producer_unit_price_cents: int
    status: str
    quantity_offered: int
    quantity_committed: int
    quantity_available: int
    offer_window_start: Optional[str]
    offer_window_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    legal_name: str
    buyer_type: str
    dock_zone_code: str
    payment_terms_days: int
    credit_limit_cents: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class BuyerOrder(TypedDict):
    id: str
    buyer_id: str
    requested_delivery_date: str
    fulfillment_status: str
    settlement_status: str
    producer_subtotal_cents: int
    hub_margin_cents: int
    order_total_cents: int
    margin_tier_bp: int
    invoiced_total_cents: int
    paid_total_cents: int
    credit_memo_cents: int
    invoice_due_date: Optional[str]
    route_id: Optional[str]
    route_sequence_no: Optional[int]
    planned_arrival_at: Optional[str]
    service_minutes: Optional[int]
    order_pallets: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    commodity_code: str
    storage_class: str
    unit_of_measure: str
    quantity_requested: int
    max_unit_price_cents: int
    quantity_allocated: int
    quantity_delivered: int
    quantity_rejected: int
    line_producer_cents: int
    line_margin_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    order_line_id: str
    product_id: str
    quantity: int
    producer_unit_price_cents: int
    margin_bp: int
    producer_amount_cents: int
    hub_margin_cents: int
    buyer_amount_cents: int
    delivered_quantity: int
    rejected_quantity: int
    producer_charge_cents: int
    hub_absorbed_cents: int
    staged_temp_c: Optional[float]
    temp_excursion: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DockSlot(TypedDict):
    id: str
    door_code: str
    storage_class: str
    window_start: str
    window_end: str
    pallet_capacity: int
    temp_setpoint_c: float
    sanitation_buffer_minutes: int
    pallets_booked: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DockAppointment(TypedDict):
    id: str
    dock_slot_id: str
    producer_id: str
    arrival_start: str
    arrival_end: str
    pallets: int
    risk_class: str
    received_pallets: int
    recorded_temp_c: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict):
    id: str
    route_date: str
    vehicle_code: str
    storage_class: str
    pallet_capacity: int
    depot_departure_at: str
    pallets_loaded: int
    stop_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RejectionClaim(TypedDict):
    id: str
    allocation_id: str
    quantity_rejected: int
    reason_code: str
    note: Optional[str]
    filed_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    status: str
    producer_fault_bp: int
    buyer_credit_cents: int
    producer_charge_cents: int
    hub_absorbed_cents: int
    created_at: str
    updated_at: str
    version: int


class PatronageCycle(TypedDict):
    id: str
    fiscal_year: int
    distributable_pool_cents: int
    status: str
    proposed_by_user_id: str
    ratified_by_user_id: Optional[str]
    basis_snapshot_total_cents: int
    eligible_producer_count: int
    distributed_total_cents: int
    remainder_cents: int
    created_at: str
    updated_at: str
    version: int


LineReceipt = TypedDict("LineReceipt", {"allocation_id": str, "delivered_quantity": int})

__all__ = [
    "UserRole",
    "ProducerOnboardingStatus",
    "FoodSafetyTier",
    "DocumentType",
    "DocumentStatus",
    "ProductStatus",
    "UnitOfMeasure",
    "StorageClass",
    "BuyerType",
    "FulfillmentStatus",
    "SettlementStatus",
    "OrderLineStatus",
    "AllocationStatus",
    "DockSlotStatus",
    "RiskClass",
    "AppointmentStatus",
    "RouteStatus",
    "RejectionReasonCode",
    "ClaimStatus",
    "CycleStatus",
    "Producer",
    "ProducerDocument",
    "Product",
    "Buyer",
    "BuyerOrder",
    "OrderLine",
    "Allocation",
    "DockSlot",
    "DockAppointment",
    "DeliveryRoute",
    "RejectionClaim",
    "PatronageCycle",
    "LineReceipt",
]
