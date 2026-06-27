"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Beekeeping Apiary PRD entity model. Entities that the PRD declares
immutable and append-only (Inspection, Feeding) carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ───────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    APIARY_MANAGER = "ApiaryManager"
    STATE_APIARIST = "StateApiarist"
    CONTRACT_COORDINATOR = "ContractCoordinator"


# ─── Status enums ────────────────────────────────────────────────────────
class RegistrationStatus(str, Enum):
    UNREGISTERED = "UNREGISTERED"
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class StateRegistrationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class HiveHealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    TREATMENT = "TREATMENT"
    QUARANTINE = "QUARANTINE"
    DEADOUT = "DEADOUT"


class HiveQueenStatus(str, Enum):
    QUEENRIGHT = "QUEENRIGHT"
    QUEENLESS = "QUEENLESS"
    REQUEENING = "REQUEENING"


class TreatmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class TreatmentProduct(str, Enum):
    APIVAR = "APIVAR"
    FORMIC_PRO = "FORMIC_PRO"
    OXALIC_ACID = "OXALIC_ACID"


class HoneyLotStatus(str, Enum):
    DRAFT = "DRAFT"
    BLOCKED = "BLOCKED"
    EXTRACTED = "EXTRACTED"
    SOLD = "SOLD"
    VOIDED = "VOIDED"


class FloralSource(str, Enum):
    WILDFLOWER = "WILDFLOWER"
    ALMOND = "ALMOND"
    CLOVER = "CLOVER"
    ORANGE_BLOSSOM = "ORANGE_BLOSSOM"


class HarvestStatus(str, Enum):
    RECORDED = "RECORDED"
    VOID = "VOID"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    PLACED = "PLACED"
    UNDERSTAFFED = "UNDERSTAFFED"
    FULFILLED = "FULFILLED"
    DISPUTED = "DISPUTED"
    CANCELLED = "CANCELLED"


class PlacementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    REMOVED = "REMOVED"
    CANCELLED = "CANCELLED"


class PlacementGrade(str, Enum):
    CONTRACT_GRADE = "CONTRACT_GRADE"
    SUB_GRADE = "SUB_GRADE"


class SaleProductType(str, Enum):
    QUEEN = "QUEEN"
    NUC = "NUC"


class SaleStatus(str, Enum):
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    VOIDED = "VOIDED"


class FeedType(str, Enum):
    SYRUP_1_1 = "SYRUP_1_1"
    SYRUP_2_1 = "SYRUP_2_1"
    FONDANT = "FONDANT"
    POLLEN_PATTY = "POLLEN_PATTY"


class RequeenReason(str, Enum):
    AGE = "AGE"
    FAILING = "FAILING"
    QUEENLESS = "QUEENLESS"
    GENETICS = "GENETICS"


class RequeenStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts (common_fields: true carry id+created_at+updated_at+version) ──
class Apiary(TypedDict):
    id: str
    name: str
    state_code: str
    latitude: float
    longitude: float
    registration_status: str
    active_colony_count: int
    max_yard_colonies: int
    created_at: str
    updated_at: str
    version: int


class StateRegistration(TypedDict):
    id: str
    apiary_id: str
    registration_number: str
    status: str
    effective_date: str
    expiry_date: str
    created_at: str
    updated_at: str
    version: int


class Hive(TypedDict):
    id: str
    apiary_id: str
    source_hive_id: Optional[str]
    tag: str
    health_status: str
    queen_status: str
    brood_frames: int
    honey_frames: int
    last_mite_count: Optional[float]
    harvest_blocked_until: Optional[str]
    inspection_strength: int
    created_at: str
    updated_at: str
    version: int


class Treatment(TypedDict):
    id: str
    hive_id: str
    product: str
    status: str
    applied_at: str
    duration_days: int
    withdrawal_days: int
    harvest_clear_at: str
    created_at: str
    updated_at: str
    version: int


class HoneyLot(TypedDict):
    id: str
    apiary_id: str
    lot_code: str
    floral_source: str
    status: str
    provisional_yield_kg: float
    final_yield_kg: Optional[float]
    gross_weight_kg: float
    price_per_kg_cents: int
    gross_revenue_cents: Optional[int]
    net_revenue_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Harvest(TypedDict):
    id: str
    lot_id: str
    hive_id: str
    frames_pulled: int
    weight_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PollinationContract(TypedDict):
    id: str
    grower_name: str
    orchard_state_code: str
    bloom_start: str
    bloom_end: str
    required_strong_hives: int
    max_hives_on_site: int
    base_rate_cents: int
    status: str
    placed_strong_hives: int
    projected_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class HivePlacement(TypedDict):
    id: str
    contract_id: str
    hive_id: str
    placement_start: str
    removal_due: str
    grade: Optional[str]
    status: str
    contract_rated_strength: Optional[int]
    created_at: str
    updated_at: str
    version: int


class QueenNucSale(TypedDict):
    id: str
    apiary_id: str
    source_hive_id: str
    product_type: str
    frames_drawn: int
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RequeenSchedule(TypedDict):
    id: str
    hive_id: str
    due_date: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entities (common_fields: false — id + created_at only) ───
class Inspection(TypedDict):
    id: str
    hive_id: str
    inspected_at: str
    mites_per_100_bees: float
    brood_frames_observed: int
    honey_frames_observed: int
    queen_seen: bool
    treatment_recommended: bool
    created_at: str


class Feeding(TypedDict):
    id: str
    hive_id: str
    fed_at: str
    feed_type: str
    quantity_kg: float
    created_at: str
