"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this API carries the four system-managed properties
``id``, ``created_at``, ``updated_at`` and ``version`` (PRD §2.4), so every
TypedDict below includes them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    QUALITY_MANAGER = "QualityManager"
    BATCH_SCHEDULER = "BatchScheduler"
    TANK_OPERATOR = "TankOperator"
    QA_VALIDATOR = "QAValidator"
    SDS_AUTHOR = "SDSAuthor"
    SHIPPING_CLERK = "ShippingClerk"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PricingMode(str, Enum):
    TOLLING_FEE = "TOLLING_FEE"
    FORMULATED_PRICE = "FORMULATED_PRICE"


class PricingAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class GHSClass(str, Enum):
    FLAMMABLE = "FLAMMABLE"
    OXIDIZER = "OXIDIZER"
    ACID = "ACID"
    BASE = "BASE"
    TOXIN = "TOXIN"
    NON_HAZ = "NON_HAZ"


class StorageZone(str, Enum):
    Z_FLAM = "Z_FLAM"
    Z_OXID = "Z_OXID"
    Z_ACID = "Z_ACID"
    Z_BASE = "Z_BASE"
    Z_TOXIC = "Z_TOXIC"
    Z_GENERAL = "Z_GENERAL"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class CleaningState(str, Enum):
    DIRTY = "DIRTY"
    CLEANING_IN_PROGRESS = "CLEANING_IN_PROGRESS"
    CLEAN_PENDING_VALIDATION = "CLEAN_PENDING_VALIDATION"
    CLEAN_VALIDATED = "CLEAN_VALIDATED"


class OperationalState(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CleaningMethod(str, Enum):
    SOLVENT_FLUSH = "SOLVENT_FLUSH"
    CAUSTIC_CIP = "CAUSTIC_CIP"
    STEAM = "STEAM"
    DRY_PURGE = "DRY_PURGE"


class ValidationOutcome(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class BatchJobStatus(str, Enum):
    INTAKE = "INTAKE"
    RELEASED = "RELEASED"
    CHARGING = "CHARGING"
    MIXING = "MIXING"
    HOLD_QA = "HOLD_QA"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED_QA = "REJECTED_QA"


class BatchChargeStatus(str, Enum):
    COMMITTED = "COMMITTED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class SDSStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"


class SignalWord(str, Enum):
    DANGER = "DANGER"
    WARNING = "WARNING"
    NONE = "NONE"


class PackageType(str, Enum):
    DRUM_205L = "DRUM_205L"
    IBC_1000L = "IBC_1000L"
    TOTE_500L = "TOTE_500L"
    PAIL_20L = "PAIL_20L"


class PlacardClass(str, Enum):
    CLASS_3_FLAMMABLE = "CLASS_3_FLAMMABLE"
    CLASS_5_1_OXIDIZER = "CLASS_5_1_OXIDIZER"
    CLASS_8_CORROSIVE = "CLASS_8_CORROSIVE"
    CLASS_6_1_TOXIC = "CLASS_6_1_TOXIC"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    DISPATCHED = "DISPATCHED"
    CANCELLED = "CANCELLED"


class DisposalMethod(str, Enum):
    INCINERATION = "INCINERATION"
    FUEL_BLENDING = "FUEL_BLENDING"
    HAZARDOUS_LANDFILL = "HAZARDOUS_LANDFILL"


class HeelDisposalStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all resources carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------

class Customer(TypedDict):
    id: str
    legal_name: str
    credit_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PricingAgreement(TypedDict):
    id: str
    customer_id: str
    pricing_mode: str
    tolling_base_fee_cents: int
    tolling_per_kg_cents: int
    formulated_price_per_kg_cents: int
    over_yield_split_pct: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RawMaterialLot(TypedDict):
    id: str
    customer_id: str
    material_code: str
    ghS_class: str
    quantity_kg_received: float
    quantity_kg_on_hand: float
    quantity_kg_committed: float
    quantity_kg_available: float
    storage_zone: str
    received_at: str
    created_at: str
    updated_at: str
    version: int


class RecipeComponent(TypedDict):
    material_code: str
    mass_fraction_pct: float
    charge_order: int


class Recipe(TypedDict):
    id: str
    name: str
    revision: int
    customer_id: str
    target_density_kg_per_l: float
    theoretical_yield_pct: float
    components: List[RecipeComponent]
    highest_component_ghs: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Tank(TypedDict):
    id: str
    tank_code: str
    capacity_l: int
    working_capacity_l: int
    current_zone: str
    occupied_by_batch_id: Optional[str]
    last_product_ghs: Optional[str]
    cleaning_state: str
    operational_state: str
    created_at: str
    updated_at: str
    version: int


class CleaningRecord(TypedDict):
    id: str
    tank_id: str
    method: str
    started_at: str
    completed_at: str
    residue_ppm: int
    validated_by: Optional[str]
    validation_outcome: str
    created_at: str
    updated_at: str
    version: int


class BatchJob(TypedDict):
    id: str
    customer_id: str
    recipe_id: str
    pricing_agreement_id: str
    tank_id: str
    batch_size_l: int
    scheduled_start: str
    scheduled_end: str
    theoretical_output_kg: float
    actual_output_kg: Optional[float]
    density_corrected_output_l: Optional[float]
    yield_variance_pct: Optional[float]
    quoted_price_cents: Optional[int]
    invoiced_price_cents: Optional[int]
    highest_component_ghs_snapshot: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BatchCharge(TypedDict):
    id: str
    batch_job_id: str
    raw_material_lot_id: str
    charge_order: int
    charged_qty_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SDSDocument(TypedDict):
    id: str
    batch_job_id: str
    authoring_revision: int
    ghs_classification: str
    signal_word: str
    hazard_statements: List[str]
    authoring_consistency_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PackageConfig(TypedDict):
    id: str
    batch_job_id: str
    package_type: str
    un_rated: bool
    package_count: int
    total_volume_l: int
    placard_required: bool
    placard_class: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    batch_job_id: str
    carrier_name: str
    vehicle_placards: List[str]
    departure_at: str
    shipped_volume_l: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class HeelDisposalRecord(TypedDict):
    id: str
    batch_job_id: str
    raw_material_lot_id: str
    heel_returned_kg: float
    heel_disposed_kg: float
    disposal_method: Optional[str]
    waste_manifest_number: Optional[str]
    disposed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
