"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PackingJobStatus(str, Enum):
    QUOTED = "QUOTED"
    DESIGN = "DESIGN"
    PACKING = "PACKING"
    READY_TO_LOAD = "READY_TO_LOAD"
    LOADED = "LOADED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class JobMode(str, Enum):
    SHOP = "SHOP"
    ONSITE = "ONSITE"


class Incoterm(str, Enum):
    EXW = "EXW"
    FOB = "FOB"
    DDP = "DDP"


class ItemStatus(str, Enum):
    CAPTURED = "CAPTURED"
    DESIGN_APPROVED = "DESIGN_APPROVED"
    PACKED = "PACKED"
    SEALED = "SEALED"


class FragileClass(str, Enum):
    STANDARD = "STANDARD"
    DELICATE = "DELICATE"
    HIGHLY_FRAGILE = "HIGHLY_FRAGILE"


class BatteryType(str, Enum):
    NONE = "NONE"
    LITHIUM_ION = "LITHIUM_ION"
    LITHIUM_METAL = "LITHIUM_METAL"
    WET_CELL = "WET_CELL"


class MoistureBarrier(str, Enum):
    NONE = "NONE"
    VCI = "VCI"
    VACUUM_SEALED = "VACUUM_SEALED"


class CrateDesignStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class WoodBatchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class CrateStatus(str, Enum):
    PLANNED = "PLANNED"
    BUILT = "BUILT"
    PACKED = "PACKED"
    SEALED = "SEALED"
    REOPENED = "REOPENED"
    LOADED = "LOADED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"


class StampStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class HazmatDeclarationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DocumentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    RELEASED = "RELEASED"
    AMENDING = "AMENDING"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class LaborBookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OnsitePermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ContainerStatus(str, Enum):
    PLANNING = "PLANNING"
    LOCKED = "LOCKED"
    GATED_OUT = "GATED_OUT"


class ContainerSize(str, Enum):
    FT20 = "20FT"
    FT40 = "40FT"
    HC40 = "40HC"


class ClaimType(str, Enum):
    IMPACT = "IMPACT"
    TILT = "TILT"
    MOISTURE = "MOISTURE"
    OTHER = "OTHER"


class DamageClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SALES_REP = "SalesRep"
    CRATING_DESIGNER = "CratingDesigner"
    SHOP_FOREMAN = "ShopForeman"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all entities carry id/created_at/updated_at/version
# (PRD §2.4).
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    name: str
    site_code: str
    credit_limit_cents: int
    open_exposure_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackingJob(TypedDict, total=False):
    id: str
    customer_id: str
    mode: str
    incoterm: str
    status: str
    total_board_feet: int
    total_chargeable_weight_kg: float
    estimated_labor_hours: int
    quoted_price_cents: int
    invoiced_total_cents: Optional[int]
    readiness_posture: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    packing_job_id: str
    description: str
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float
    fragile_class: str
    hazmat: bool
    battery_in_equipment: str
    declared_value_cents: int
    volume_m3: float
    dimensional_weight_kg: float
    chargeable_weight_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CrateDesign(TypedDict, total=False):
    id: str
    item_id: str
    revision: int
    clearance_cm: float
    internal_l_cm: float
    internal_w_cm: float
    internal_h_cm: float
    thickness_cm: float
    external_l_cm: float
    external_w_cm: float
    external_h_cm: float
    board_feet_required: int
    tare_weight_kg: float
    shock_indicator_g: int
    moisture_barrier_required: str
    wood_batch_id: Optional[str]
    reject_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WoodBatch(TypedDict, total=False):
    id: str
    ht_certificate_no: str
    treatment_type: str
    expires_at: str
    received_board_feet: int
    stamps_acquired: int
    reserved_board_feet: int
    consumed_board_feet: int
    scrapped_board_feet: int
    available_board_feet: int
    stamps_applied: int
    stamps_voided: int
    stamps_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Crate(TypedDict, total=False):
    id: str
    item_id: str
    packing_job_id: str
    design_id: str
    container_id: Optional[str]
    stamp_serial: Optional[str]
    stamp_status: Optional[str]
    tare_weight_kg: float
    gross_weight_kg: float
    external_volume_m3: float
    freight_density_kg_m3: float
    freight_class: str
    compliance_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class HazmatDeclaration(TypedDict, total=False):
    id: str
    item_id: str
    un_number: str
    dg_class: str
    packing_group: str
    battery_type: str
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackingList(TypedDict, total=False):
    id: str
    packing_job_id: str
    lines: List[dict]
    total_gross_weight_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CommercialInvoice(TypedDict, total=False):
    id: str
    packing_job_id: str
    lines: List[dict]
    invoice_total_cents: int
    duty_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    name: str
    capabilities: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LaborBooking(TypedDict, total=False):
    id: str
    packing_job_id: str
    crew_id: str
    mode: str
    start_at: str
    end_at: str
    hours: float
    rate_cents_per_hour: int
    travel_surcharge_cents: int
    total_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OnsitePermit(TypedDict, total=False):
    id: str
    packing_job_id: str
    site_code: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict, total=False):
    id: str
    container_no: str
    size: str
    max_payload_kg: int
    dunnage_weight_kg: float
    payload_used_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    packing_job_id: str
    crate_id: str
    claim_type: str
    description: str
    amount_claimed_cents: int
    amount_approved_cents: Optional[int]
    amount_settled_cents: int
    amount_waived_cents: int
    appeal_used: bool
    filed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
