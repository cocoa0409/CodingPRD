"""Domain types: entity TypedDicts, status enums, role enum.

All entities in the Printing Bureau are mutable and therefore carry
id + created_at + updated_at + version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    BUREAU_ADMIN = "BureauAdmin"
    CUSTOMER = "Customer"
    OPERATOR = "Operator"
    QA_REVIEWER = "QAReviewer"


# ─── Status enums ─────────────────────────────────────
class MaterialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MachineStatus(str, Enum):
    ONLINE = "ONLINE"
    MAINTENANCE = "MAINTENANCE"


class SpoolStatus(str, Enum):
    LOADED = "LOADED"
    DEPLETED = "DEPLETED"


class PrintFileStatus(str, Enum):
    UPLOADED = "UPLOADED"
    PRINTABLE = "PRINTABLE"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"


class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    POST_PROCESSING = "POST_PROCESSING"
    READY = "READY"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    ESCROWED = "ESCROWED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class OrderLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class FinishingTaskStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    DONE = "DONE"
    SKIPPED = "SKIPPED"


class PrintRunStatus(str, Enum):
    QUEUED = "QUEUED"
    PRINTING = "PRINTING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"


class Process(str, Enum):
    SLA = "SLA"
    FDM = "FDM"
    SLS = "SLS"


class LeadTier(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITE = "EXPEDITE"
    RUSH = "RUSH"


class FinishingKind(str, Enum):
    SUPPORT_REMOVAL = "SUPPORT_REMOVAL"
    SANDING = "SANDING"
    DYE_BLACK = "DYE_BLACK"
    UV_CURE = "UV_CURE"
    POLISH = "POLISH"


class Carrier(str, Enum):
    UPS = "UPS"
    FEDEX = "FEDEX"
    DHL = "DHL"


class ReprintCause(str, Enum):
    MACHINE_FAULT = "MACHINE_FAULT"
    OPERATOR_ERROR = "OPERATOR_ERROR"
    FILE_DEFECT = "FILE_DEFECT"
    CUSTOMER_CHANGE = "CUSTOMER_CHANGE"


# ─── Entity TypedDicts (all common_fields: true) ──────
class Bureau(TypedDict):
    id: str
    name: str
    cooldown_buffer_min: int
    shift_capacity_minutes: int
    clock_utc: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    bureau_id: str
    email: str
    display_name: str
    lifetime_deposits_cents: int
    wallet_balance_cents: int
    escrow_held_cents: int
    captured_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Material(TypedDict):
    id: str
    bureau_id: str
    process: str
    name: str
    density_g_per_cm3: float
    material_rate_cents_per_cm3: int
    machine_rate_cents_per_min: int
    setup_fee_cents: int
    min_wall_thickness_mm: float
    max_overhang_deg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict):
    id: str
    bureau_id: str
    process: str
    label: str
    build_x_mm: float
    build_y_mm: float
    build_z_mm: float
    scheduled_minutes: int
    active_minutes: int
    utilization_pct: int
    active_utilization_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Spool(TypedDict):
    id: str
    bureau_id: str
    material_id: str
    grams_total: int
    grams_committed: int
    grams_consumed: int
    grams_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrintFile(TypedDict):
    id: str
    bureau_id: str
    customer_id: str
    filename: str
    volume_cm3: float
    bbox_x_mm: float
    bbox_y_mm: float
    bbox_z_mm: float
    min_wall_mm: float
    max_overhang_deg: float
    is_manifold: bool
    printability_score: Optional[int]
    checked_against_material_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    bureau_id: str
    customer_id: str
    lead_tier: str
    parts_subtotal_cents: int
    finishing_subtotal_cents: int
    rush_surcharge_cents: int
    grand_total_cents: int
    fulfillment_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    bureau_id: str
    order_id: str
    print_file_id: str
    material_id: str
    layer_height_mm: float
    quantity: int
    print_minutes: int
    per_part_cents: int
    line_total_cents: int
    finishing_total_cents: int
    reprint_of_line_id: Optional[str]
    reprint_cause: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FinishingTask(TypedDict):
    id: str
    bureau_id: str
    order_line_id: str
    kind: str
    addon_cents: int
    station_start_min: int
    station_duration_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrintRun(TypedDict):
    id: str
    bureau_id: str
    order_line_id: str
    machine_id: str
    spool_id: str
    start_min: int
    duration_min: int
    run_grams: int
    fail_cause: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    bureau_id: str
    order_id: str
    carrier: str
    tracking_number: str
    status: str
    created_at: str
    updated_at: str
    version: int
