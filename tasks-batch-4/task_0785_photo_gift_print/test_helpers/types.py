"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Photo-Gift & Print Service PRD. Enum string values are the exact
literals the API emits and accepts.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    CATALOG_ADMIN = "CatalogAdmin"
    PRODUCTION_OPERATOR = "ProductionOperator"


class ProductType(str, Enum):
    PHOTOBOOK = "PHOTOBOOK"
    CARD = "CARD"
    CANVAS = "CANVAS"
    CALENDAR = "CALENDAR"


class Finish(str, Enum):
    MATTE = "MATTE"
    GLOSSY = "GLOSSY"
    LINEN = "LINEN"
    LAY_FLAT = "LAY_FLAT"
    METAL = "METAL"


class ShipMethod(str, Enum):
    STANDARD = "STANDARD"
    EXPRESS = "EXPRESS"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    STORE_CREDIT = "STORE_CREDIT"


class RefundDestination(str, Enum):
    WALLET = "WALLET"
    CARD = "CARD"


class TemplateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ProjectState(str, Enum):
    DRAFT = "DRAFT"
    LAID_OUT = "LAID_OUT"
    IN_PROOF = "IN_PROOF"
    APPROVED = "APPROVED"


class PhotoStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PLACED = "PLACED"
    LOCKED = "LOCKED"


class ProofState(str, Enum):
    GENERATED = "GENERATED"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    SUPERSEDED = "SUPERSEDED"


class PromotionKind(str, Enum):
    PERCENT = "PERCENT"
    FLAT = "FLAT"
    FREE_SHIP = "FREE_SHIP"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    NEW = "NEW"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ProductionJobState(str, Enum):
    QUEUED = "QUEUED"
    PRINTING = "PRINTING"
    FINISHING = "FINISHING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class ShipmentState(str, Enum):
    LABEL_CREATED = "LABEL_CREATED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    VOID = "VOID"


# ── Entities (common_fields: true carry id/created_at/updated_at/version) ──

class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Address(TypedDict):
    id: str
    customer_id: str
    recipient_name: str
    line1: str
    line2: Optional[str]
    city: str
    region: str
    postal_code: str
    country: str
    is_default: bool
    created_at: str
    updated_at: str
    version: int


class Template(TypedDict):
    id: str
    product_type: str
    name: str
    status: str
    surface_count: int
    base_unit_price_cents: int
    production_days: int
    allowed_finishes: List[str]
    min_photos: int
    max_photos: int
    min_dpi: int
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    customer_id: str
    template_id: str
    title: str
    state: str
    photo_count: int
    placed_photo_count: int
    current_proof_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Photo — common_fields: false → carries ONLY id + created_at (no updated_at/version).
class Photo(TypedDict):
    id: str
    project_id: str
    filename: str
    width_px: int
    height_px: int
    dpi: int
    status: str
    created_at: str


class Proof(TypedDict):
    id: str
    project_id: str
    revision_number: int
    state: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    code: str
    kind: str
    value: int
    min_subtotal_cents: int
    stackable: bool
    per_customer_limit: int
    product_type_scope: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PromoWindow(TypedDict):
    id: str
    promotion_id: str
    starts_at: str
    ends_at: str
    created_at: str
    updated_at: str
    version: int


class SurgeWindow(TypedDict):
    id: str
    name: str
    starts_at: str
    ends_at: str
    turnaround_extra_days: int
    capacity_per_day: int
    product_type_scope: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    project_id: str
    ship_address_id: str
    reorder_of_id: Optional[str]
    quantity: int
    finish: str
    ship_method: str
    payment_method: str
    promo_codes: List[str]
    unit_price_cents: int
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    total_cents: int
    paid_cents: int
    refund_cents: int
    refund_destination: Optional[str]
    promised_ship_date: Optional[str]
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class ProductionJob(TypedDict):
    id: str
    order_id: str
    quantity: int
    scheduled_date: str
    surge_window_id: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    address_id: str
    carrier: str
    method: str
    tracking_code: str
    state: str
    created_at: str
    updated_at: str
    version: int
