"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as the PRD specifies. Append-only history records
(WeightRecord, TraceEvent) carry only id + created_at — no updated_at, no version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    HERD_MANAGER = "HerdManager"
    VETERINARIAN = "Veterinarian"
    SALE_CLERK = "SaleClerk"
    FEEDLOT_OPERATOR = "FeedlotOperator"
    AUDITOR = "Auditor"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class Species(str, Enum):
    CATTLE = "CATTLE"
    SHEEP = "SHEEP"
    GOAT = "GOAT"


class AnimalLifeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SOLD = "SOLD"
    DEAD = "DEAD"
    CULLED = "CULLED"


class MeatClearanceStatus(str, Enum):
    CLEAR = "CLEAR"
    WITHHELD = "WITHHELD"


class AnimalSex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    STEER = "STEER"


class PastureKind(str, Enum):
    PASTURE = "PASTURE"
    PEN = "PEN"


class DrugCategory(str, Enum):
    VACCINE = "VACCINE"
    ANTIBIOTIC = "ANTIBIOTIC"
    ANTIPARASITIC = "ANTIPARASITIC"
    HORMONE = "HORMONE"


class FeedRationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class BreedingStatus(str, Enum):
    OPEN = "OPEN"
    BRED = "BRED"
    CONFIRMED_PREGNANT = "CONFIRMED_PREGNANT"
    CALVED = "CALVED"
    FAILED = "FAILED"


class HealthTreatmentStatus(str, Enum):
    WITHDRAWAL_ACTIVE = "WITHDRAWAL_ACTIVE"
    CLEARED = "CLEARED"
    VOIDED = "VOIDED"


class MovementStatus(str, Enum):
    PLANNED = "PLANNED"
    APPLIED = "APPLIED"
    REVERTED = "REVERTED"


class SaleLotStatus(str, Enum):
    OPEN = "OPEN"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"


class MortalityStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class TraceEventType(str, Enum):
    BIRTH = "BIRTH"
    MOVEMENT = "MOVEMENT"
    TREATMENT = "TREATMENT"
    SALE = "SALE"
    MORTALITY = "MORTALITY"
    CULL = "CULL"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"


# --------------------------------------------------------------------------
# Entities carrying full common fields (id, created_at, updated_at, version)
# --------------------------------------------------------------------------
class Herd(TypedDict):
    id: str
    name: str
    species: str
    premises_id: str
    active_animal_count: int
    total_au_load: float
    mortality_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class Pasture(TypedDict):
    id: str
    name: str
    kind: str
    capacity_au: float
    rest_days: int
    current_au_load: float
    created_at: str
    updated_at: str
    version: int


class DrugProduct(TypedDict):
    id: str
    name: str
    category: str
    route_withdrawals: dict
    milk_withdrawal_hours: int
    created_at: str
    updated_at: str
    version: int


class FeedRation(TypedDict):
    id: str
    name: str
    target_dmi_kg: float
    ingredients: list
    status: str
    created_at: str
    updated_at: str
    version: int


class Animal(TypedDict):
    id: str
    herd_id: str
    ear_tag: str
    rfid: Optional[str]
    sex: str
    birth_date: str
    birth_weight_kg: float
    dam_animal_id: Optional[str]
    sire_animal_id: Optional[str]
    current_pasture_id: Optional[str]
    latest_weight_kg: float
    lifetime_adg_kg: float
    life_status: str
    meat_clearance_status: str
    meat_clear_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BreedingRecord(TypedDict):
    id: str
    dam_animal_id: str
    sire_animal_id: Optional[str]
    bred_on: str
    expected_calving_on: Optional[str]
    calved_on: Optional[str]
    calf_animal_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HealthTreatment(TypedDict):
    id: str
    animal_id: str
    drug_product_id: str
    route: str
    dose_count: int
    first_dose_on: str
    last_dose_on: str
    clearance_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MovementRecord(TypedDict):
    id: str
    animal_id: str
    to_pasture_id: str
    from_pasture_id: Optional[str]
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SaleLot(TypedDict):
    id: str
    herd_id: str
    channel: str
    pencil_shrink_pct: float
    commission_pct: float
    head_count: int
    gross_sale_amount: float
    commission_amount: float
    net_proceeds: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WeightTicket(TypedDict):
    id: str
    sale_lot_id: str
    animal_id: str
    gross_weight_kg: float
    price_per_100kg: float
    net_weight_kg: float
    gross_line_amount: float
    created_at: str
    updated_at: str
    version: int


class MortalityRecord(TypedDict):
    id: str
    animal_id: str
    died_on: str
    cause: str
    disposal_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only history records — id + created_at only (no updated_at, no version)
# --------------------------------------------------------------------------
class WeightRecord(TypedDict):
    id: str
    animal_id: str
    weighed_at: str
    weight_kg: float
    source: str
    interval_adg_kg: Optional[float]
    created_at: str


class TraceEvent(TypedDict):
    id: str
    animal_id: str
    event_type: str
    ref_entity: str
    ref_id: str
    occurred_on: str
    detail: dict
    created_at: str
