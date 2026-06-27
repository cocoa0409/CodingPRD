"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    ESTIMATOR = "Estimator"
    ADJUSTER = "Adjuster"


# ---------------------------------------------------------------------------
# Status / enum vocabularies (PRD §2.9)
# ---------------------------------------------------------------------------
class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class Peril(str, Enum):
    WATER = "WATER"
    FIRE = "FIRE"
    MOLD = "MOLD"


class LossType(str, Enum):
    WATER = "WATER"
    FIRE = "FIRE"
    SMOKE = "SMOKE"


class JobStatus(str, Enum):
    FNOL = "FNOL"
    DISPATCHED = "DISPATCHED"
    MITIGATION = "MITIGATION"
    MONITORING = "MONITORING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DryingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    DRYING = "DRYING"
    DRY_STANDARD_MET = "DRY_STANDARD_MET"


class Certification(str, Enum):
    WRT = "WRT"
    ASD = "ASD"
    AMRT = "AMRT"


class ChamberStatus(str, Enum):
    OPEN = "OPEN"
    DRIED = "DRIED"
    DECOMMISSIONED = "DECOMMISSIONED"


class EquipmentKind(str, Enum):
    AIR_MOVER = "AIR_MOVER"
    DEHUMIDIFIER = "DEHUMIDIFIER"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLOYED = "DEPLOYED"


class PlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ContentsStatus(str, Enum):
    PACKED_OUT = "PACKED_OUT"
    STORED = "STORED"
    RETURNED = "RETURNED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Versioned entities (id + created_at + updated_at + version):
#   InsuranceClaim, LossJob, DryingChamber, EquipmentUnit,
#   EquipmentPlacement, ScopeEstimate, ContentsItem  (PRD §2.4)
# Append-only / pool entities (ONLY id + created_at):
#   Technician, MoistureReading  (PRD §2.4)
# ---------------------------------------------------------------------------
class InsuranceClaim(TypedDict):
    id: str
    carrier_name: str
    policy_number: str
    adjuster_user_id: str
    peril: str
    coverage_limit_cents: int
    deductible_cents: int
    depreciation_pct: float
    tax_pct: float
    status: str
    settled_estimate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LossJob(TypedDict):
    id: str
    claim_id: str
    property_address: str
    loss_type: str
    water_category: Optional[int]
    water_class: Optional[int]
    assigned_technician_id: Optional[str]
    antimicrobial_required: bool
    monitoring_day: int
    drying_status: str
    status: str
    completed_at: Optional[str]
    warranty_expires_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Technician: common_fields false -> only id + created_at
class Technician(TypedDict):
    id: str
    full_name: str
    certification: str
    active: bool
    created_at: str


class DryingChamber(TypedDict):
    id: str
    job_id: str
    room_label: str
    floor_area_sqft: int
    wet_wall_linear_ft: int
    dehu_ppd_rating: int
    dry_standard_pct: float
    latest_moisture_content_pct: Optional[float]
    is_dry: bool
    air_movers_required: int
    dehumidifiers_required: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict):
    id: str
    asset_tag: str
    kind: str
    status: str
    active_placement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentPlacement(TypedDict):
    id: str
    job_id: str
    chamber_id: str
    equipment_unit_id: str
    kind: str
    placed_on_day: int
    removed_on_day: Optional[int]
    billable_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


# MoistureReading: common_fields false -> only id + created_at
class MoistureReading(TypedDict):
    id: str
    job_id: str
    chamber_id: str
    monitoring_day: int
    temp_f: float
    relative_humidity_pct: float
    moisture_content_pct: float
    gpp: float
    created_at: str


class ScopeEstimate(TypedDict):
    id: str
    job_id: str
    estimated_drying_days: int
    line_items: List[dict]
    scope_lines_total_cents: int
    equipment_estimate_cents: int
    estimate_total_cents: int
    acv_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContentsItem(TypedDict):
    id: str
    job_id: str
    description: str
    declared_value_cents: int
    allocated_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
