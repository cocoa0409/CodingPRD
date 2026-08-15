"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §4)."""
from enum import Enum
from typing import TypedDict, Optional, List


class Variety(str, Enum):
    CASCADE = "CASCADE"
    CENTENNIAL = "CENTENNIAL"
    CTZ = "CTZ"
    CITRA = "CITRA"
    MOSAIC = "MOSAIC"


class PlantingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    GROWING = "GROWING"
    HARVESTING = "HARVESTING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    TERMINATED = "TERMINATED"


class HarvestLotStatus(str, Enum):
    HARVESTED = "HARVESTED"
    IN_KILN = "IN_KILN"
    MOISTURE_CHECK = "MOISTURE_CHECK"
    DRIED = "DRIED"
    CONSUMED = "CONSUMED"


class LabTestType(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class PelletInventoryStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    DELIVERED = "DELIVERED"


class PelletAgeClass(str, Enum):
    CURRENT = "CURRENT"
    CARRYOVER = "CARRYOVER"


class AllocationStatus(str, Enum):
    PROJECTED = "PROJECTED"
    CONFIRMED = "CONFIRMED"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class SpotSaleStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class SampleStatus(str, Enum):
    SENT = "SENT"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"


class InsuranceClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class UserRole(str, Enum):
    FARM_MANAGER = "FarmManager"
    LAB_TECHNICIAN = "LabTechnician"
    CONTRACT_MANAGER = "ContractManager"
    INSURANCE_ADJUSTER = "InsuranceAdjuster"


class Field(TypedDict, total=False):
    id: str
    name: str
    acreage: int
    created_at: str
    updated_at: str
    version: int


class Kiln(TypedDict, total=False):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class PlantingPlan(TypedDict, total=False):
    id: str
    field_id: str
    crop_year: int
    variety: str
    planned_acreage: int
    projected_yield_lbs: int
    actual_yield_lbs: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    brewery_name: str
    variety: str
    term_start_year: int
    term_end_year: int
    annual_volume_lbs: int
    base_price_cents_per_lb: int
    alpha_floor_pct: float
    alpha_premium_cents_per_point: int
    alpha_discount_cents_per_point: int
    consecutive_shortfall_years: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HarvestLot(TypedDict, total=False):
    id: str
    planting_plan_id: str
    kiln_id: Optional[str]
    variety: str
    crop_year: int
    wet_lbs: int
    dried_lbs: Optional[int]
    moisture_pct: Optional[float]
    alpha_pct_provisional: Optional[float]
    alpha_pct_final: Optional[float]
    kiln_window_start: Optional[str]
    kiln_window_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only record (PRD §2.4): carries only id + created_at from the common
# fields; both updated_at and version are absent.
class LabTest(TypedDict, total=False):
    id: str
    harvest_lot_id: str
    test_type: str
    alpha_pct: float
    created_at: str


class PelletLot(TypedDict, total=False):
    id: str
    source_lot_ids: List[str]
    variety: str
    crop_year: int
    qty_lbs: int
    blended_alpha_pct: float
    storage_room: str
    entered_storage_at: str
    inventory_status: str
    age_class: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict, total=False):
    id: str
    contract_id: str
    crop_year: int
    variety: str
    allocated_lbs: int
    shortfall_lbs: int
    reserved_lot_ids: List[str]
    delivered_lbs: int
    delivered_lot_ids: List[str]
    delivered_alpha_pct: Optional[float]
    estimated_unit_price_cents: Optional[int]
    delivery_shortfall_lbs: Optional[int]
    unit_price_cents: Optional[int]
    settlement_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpotSale(TypedDict, total=False):
    id: str
    pellet_lot_id: str
    buyer_name: str
    price_cents_per_lb: int
    buyer_credit_limit_cents: int
    qty_lbs: int
    sale_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BrewerySample(TypedDict, total=False):
    id: str
    pellet_lot_id: str
    brewery_name: str
    sample_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InsuranceClaim(TypedDict, total=False):
    id: str
    planting_plan_id: str
    price_election_cents_per_lb: int
    coverage_pct: float
    guarantee_lbs: int
    indemnity_estimate_cents: int
    filed_by_user_id: str
    indemnity_final_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
