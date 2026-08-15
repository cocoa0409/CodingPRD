"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    NURSERY_MANAGER = "NurseryManager"
    CONTRACT_OFFICER = "ContractOfficer"
    FIELD_AUDITOR = "FieldAuditor"
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    LANDOWNER = "Landowner"


class Species(str, Enum):
    DOUGLAS_FIR = "DOUGLAS_FIR"
    LOBLOLLY_PINE = "LOBLOLLY_PINE"
    WHITE_OAK = "WHITE_OAK"


class SeedLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"


class CropBatchStatus(str, Enum):
    PLANNED = "PLANNED"
    SOWN = "SOWN"
    LIFTED = "LIFTED"
    GRADED = "GRADED"
    DEPLETED = "DEPLETED"


class SeedlingOrderStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CONFIRMED = "CONFIRMED"
    ALLOCATED = "ALLOCATED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class StoragePlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"
    DISCARDED = "DISCARDED"


class PlantingContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SITE_PREP = "SITE_PREP"
    READY_TO_PLANT = "READY_TO_PLANT"
    BLOCKED = "BLOCKED"
    PLANTING = "PLANTING"
    PLANTED = "PLANTED"
    SURVEYED = "SURVEYED"
    REPLANT_REQUIRED = "REPLANT_REQUIRED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SitePrepStatus(str, Enum):
    NONE = "NONE"
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    STALE = "STALE"


class CrewAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class ShipmentStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    PLANTED = "PLANTED"
    SPOILED = "SPOILED"


class SpoilageReason(str, Enum):
    TEMP_EXCURSION = "TEMP_EXCURSION"
    WINDOW_EXPIRED = "WINDOW_EXPIRED"
    HANDLING_DAMAGE = "HANDLING_DAMAGE"


class ObligationStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    SCHEDULED = "SCHEDULED"
    FULFILLED = "FULFILLED"
    WAIVED = "WAIVED"


class CostShareStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    PAYMENT_HELD = "PAYMENT_HELD"
    PAID = "PAID"


class Landowner(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    tax_id: str
    cost_share_eligible: bool
    created_at: str
    updated_at: str
    version: int


class SeedZone(TypedDict, total=False):
    id: str
    zone_code: str
    min_elevation_ft: int
    max_elevation_ft: int
    band_midpoint_ft: float
    created_at: str
    updated_at: str
    version: int


class SeedLot(TypedDict, total=False):
    id: str
    source_zone_id: str
    species: str
    collected_on: str
    quantity_grams: int
    germination_pct: float
    remaining_grams: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CropBatch(TypedDict, total=False):
    id: str
    seed_lot_id: str
    planned_sow_date: str
    lift_window_start: str
    lift_window_end: str
    actual_sow_date: str
    sown_grams: int
    projected_plantable: int
    lifted_on: str
    lifted_count: int
    plantable_count: int
    cull_count: int
    reserved_plantable: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeedlingOrder(TypedDict, total=False):
    id: str
    landowner_id: str
    destination_zone_id: str
    species: str
    quantity: int
    requested_ship_date: str
    unit_price_cents: int
    total_price_cents: int
    allocated_quantity: int
    shipped_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    seedling_order_id: str
    crop_batch_id: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageUnit(TypedDict, total=False):
    id: str
    unit_code: str
    capacity_units: int
    temp_min_c: float
    temp_max_c: float
    current_load: int
    created_at: str
    updated_at: str
    version: int


class StoragePlacement(TypedDict, total=False):
    id: str
    crop_batch_id: str
    storage_unit_id: str
    quantity: int
    placed_on: str
    withdrawn_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlantingContract(TypedDict, total=False):
    id: str
    landowner_id: str
    seedling_order_id: str
    site_zone_id: str
    acres: float
    trees_per_acre: int
    contingency_pct: float
    required_seedlings: int
    planting_window_start: str
    planting_window_end: str
    herbicide_applied_on: str
    site_prep_status: str
    last_planted_on: str
    planted_quantity: int
    obligation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    crew_code: str
    capacity_per_day: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    crew_id: str
    planting_contract_id: str
    start_date: str
    end_date: str
    planned_seedlings: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    planting_contract_id: str
    crop_batch_id: str
    quantity: int
    dispatched_at: str
    handling_deadline: str
    delivered_at: str
    planted_confirmed_at: str
    spoilage_reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SurvivalSurvey(TypedDict, total=False):
    id: str
    planting_contract_id: str
    surveyed_on: str
    planted_count_snapshot: int
    alive_count: int
    survival_pct: float
    threshold_pct: float
    below_threshold: bool
    owed_quantity: int
    replant_date: str
    waiver_reason: str
    obligation_status: str
    created_at: str
    updated_at: str
    version: int


class CostShareEnrollment(TypedDict, total=False):
    id: str
    landowner_id: str
    program_code: str
    enrolled_acres: float
    rate_per_acre_cents: int
    cap_cents: int
    documented_acres: float
    documented_cost_cents: int
    provisional_award_cents: int
    final_award_cents: int
    paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
