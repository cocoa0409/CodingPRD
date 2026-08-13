"""Domain types: entity TypedDicts, status enums, role enum for the Mattress Law Label API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    LINE_SUPERVISOR = "LineSupervisor"
    QC_INSPECTOR = "QcInspector"
    RETAILER = "Retailer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"


class ModelStatus(str, Enum):
    DRAFT = "DRAFT"
    CERT_REVIEW = "CERT_REVIEW"
    CERTIFIED = "CERTIFIED"
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class CertificateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class CertType(str, Enum):
    FLAMMABILITY = "FLAMMABILITY_16CFR1633"
    PROP65_CA = "PROP65_CA"
    TB117 = "TB117"


class SpecStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class LabelStatus(str, Enum):
    GENERATED = "GENERATED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class FoamBatchStatus(str, Enum):
    POURED = "POURED"
    CURING = "CURING"
    CURED = "CURED"
    QUARANTINED = "QUARANTINED"
    CONSUMED = "CONSUMED"
    SCRAPPED = "SCRAPPED"


class FoamDensityClass(str, Enum):
    STANDARD = "STANDARD"
    HIGH_DENSITY = "HIGH_DENSITY"
    MEMORY = "MEMORY"


class QuiltRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class MattressSize(str, Enum):
    TWIN = "TWIN"
    FULL = "FULL"
    QUEEN = "QUEEN"
    KING = "KING"
    CAL_KING = "CAL_KING"


class ProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    MATERIAL_ALLOCATED = "MATERIAL_ALLOCATED"
    IN_PRODUCTION = "IN_PRODUCTION"
    QC_PENDING = "QC_PENDING"
    QC_HOLD = "QC_HOLD"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class FulfillmentStatus(str, Enum):
    UNFULFILLED = "UNFULFILLED"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    FULLY_SHIPPED = "FULLY_SHIPPED"
    DELIVERED = "DELIVERED"


class UnitStatus(str, Enum):
    MANUFACTURED = "MANUFACTURED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    RECOVERED = "RECOVERED"
    SCRAPPED = "SCRAPPED"


class ShipmentStatus(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    INSPECTED = "INSPECTED"
    RESOLVED_EXCHANGE = "RESOLVED_EXCHANGE"
    RESOLVED_RECYCLED = "RESOLVED_RECYCLED"
    REJECTED = "REJECTED"


class ReturnReason(str, Enum):
    COMFORT_EXCHANGE = "COMFORT_EXCHANGE"
    DEFECT = "DEFECT"


class ReturnResolution(str, Enum):
    EXCHANGE = "EXCHANGE"
    RECYCLE = "RECYCLE"
    REJECT = "REJECT"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"


class ClaimType(str, Enum):
    SAG_DEFECT = "SAG_DEFECT"
    WORKMANSHIP = "WORKMANSHIP"


class CreditVariant(str, Enum):
    FULL_REPLACEMENT = "FULL_REPLACEMENT"
    PRORATED = "PRORATED"


class IntakeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    FINALIZED = "FINALIZED"


class CreditSource(str, Enum):
    MANUAL = "MANUAL"
    WARRANTY_PAYOUT = "WARRANTY_PAYOUT"
    RECYCLING_PROVISIONAL = "RECYCLING_PROVISIONAL"
    RECYCLING_FINAL_DELTA = "RECYCLING_FINAL_DELTA"
    EXCHANGE_RECOVERY = "EXCHANGE_RECOVERY"


class ComponentType(str, Enum):
    FOAM_CORE = "FOAM_CORE"
    MEMORY_LAYER = "MEMORY_LAYER"
    FIRE_BARRIER = "FIRE_BARRIER"
    TICKING = "TICKING"
    QUILT_PANEL = "QUILT_PANEL"
    FOUNDATION = "FOUNDATION"
    THREAD = "THREAD"


class ShipMethod(str, Enum):
    WAREHOUSE = "WAREHOUSE"
    DROP_SHIP = "DROP_SHIP"


class Retailer(TypedDict, total=False):
    id: str
    retailer_name: str
    drop_ship_enabled: bool
    recycling_enrolled: bool
    credit_limit_cents: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class CreditAdjustment(TypedDict, total=False):
    # Append-only ledger entry: id + created_at only, no updated_at / version
    id: str
    retailer_id: str
    amount_cents: int
    reason: str
    source: str
    source_id: Optional[str]
    created_at: str


class MattressModel(TypedDict, total=False):
    id: str
    model_code: str
    quilt_pattern: str
    bom_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BomLine(TypedDict, total=False):
    id: str
    model_id: str
    component_type: str
    material_code: str
    quantity_per_unit: float
    unit_cost_cents: int
    filling_content_code: Optional[str]
    line_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class ComplianceCertificate(TypedDict, total=False):
    id: str
    model_id: str
    cert_type: str
    jurisdiction_state_code: str
    issued_on: str
    expires_on: str
    submitted_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class StateLawLabelSpec(TypedDict, total=False):
    id: str
    state_code: str
    filling_content_codes: List[str]
    required_phrases: List[str]
    prop65_warning_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LawLabel(TypedDict, total=False):
    id: str
    model_id: str
    spec_id: str
    spec_version: int
    state_code: str
    content_text: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FoamBatch(TypedDict, total=False):
    id: str
    foam_density_class: str
    poured_mass_kg: float
    available_mass_kg: float
    reserved_mass_kg: float
    consumed_mass_kg: float
    scrapped_mass_kg: float
    chamber_id: str
    cure_started_at: Optional[str]
    cure_eligible_at: Optional[str]
    cure_cycles: int
    poured_by_user_id: str
    certified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QuiltRun(TypedDict, total=False):
    id: str
    order_id: str
    machine_id: str
    size: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionOrder(TypedDict, total=False):
    id: str
    model_id: str
    retailer_id: str
    destination_state_code: str
    quantity: int
    unit_price_cents: int
    foam_mass_required_kg: float
    ship_method: str
    foam_batch_id: Optional[str]
    subtotal_cents: int
    compliance_fee_cents: int
    total_cents: int
    production_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class MattressUnit(TypedDict, total=False):
    id: str
    serial_no: str
    order_id: str
    model_id: str
    retailer_id: str
    foam_batch_id: str
    law_label_id: str
    purchase_price_cents: int
    delivered_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    order_id: str
    retailer_id: str
    destination_state_code: str
    unit_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict, total=False):
    id: str
    unit_id: str
    retailer_id: str
    reason: str
    measured_sag_inches: Optional[float]
    resolution: Optional[str]
    replacement_unit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    unit_id: str
    retailer_id: str
    claim_type: str
    measured_sag_inches: float
    age_months: Optional[int]
    credit_variant: Optional[str]
    credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecyclingIntake(TypedDict, total=False):
    id: str
    retailer_id: str
    unit_id: Optional[str]
    declared_weight_kg: float
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
