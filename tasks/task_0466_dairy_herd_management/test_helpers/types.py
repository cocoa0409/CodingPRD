"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    HERD_MANAGER = "HerdManager"
    PARLOR_TECH = "ParlorTech"
    VETERINARIAN = "Veterinarian"
    COOP_SETTLEMENT_AGENT = "CoopSettlementAgent"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class HerdMilkQualityStatus(str, Enum):
    GOOD = "GOOD"
    WARNING = "WARNING"
    PENALIZED = "PENALIZED"


class RationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AnimalStatus(str, Enum):
    HEIFER = "HEIFER"
    ACTIVE = "ACTIVE"
    DRY = "DRY"
    SOLD = "SOLD"
    CULLED = "CULLED"
    DIED = "DIED"


class LactationStatus(str, Enum):
    OPEN = "OPEN"
    DRY = "DRY"
    CLOSED = "CLOSED"


class MilkingShiftStatus(str, Enum):
    LOGGED = "LOGGED"
    VOIDED = "VOIDED"


class BreedingEventStatus(str, Enum):
    BRED = "BRED"
    CONFIRMED_PREGNANT = "CONFIRMED_PREGNANT"
    OPEN = "OPEN"
    SERVED_OUT = "SERVED_OUT"


class HealthTreatmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"
    VOIDED = "VOIDED"


class MilkCheckStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class CullReason(str, Enum):
    LOW_PRODUCTION = "LOW_PRODUCTION"
    REPRO_FAILURE = "REPRO_FAILURE"
    HIGH_SCC = "HIGH_SCC"
    INJURY = "INJURY"
    AGE = "AGE"


class CullDisposition(str, Enum):
    SLAUGHTER = "SLAUGHTER"
    DAIRY_SALE = "DAIRY_SALE"
    DIED = "DIED"


class CullDecisionStatus(str, Enum):
    EXECUTED = "EXECUTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Resources with standard system fields carry id, created_at, updated_at, version.
# A TestDayRecord is append-only: it carries ONLY id and created_at.
# ---------------------------------------------------------------------------
class Herd(TypedDict):
    id: str
    name: str
    federal_order_number: str
    milk_quality_status: str
    active_animal_count: int
    created_at: str
    updated_at: str
    version: int


class Parlor(TypedDict):
    id: str
    herd_id: str
    name: str
    stall_capacity: int
    turnaround_minutes: int
    created_at: str
    updated_at: str
    version: int


class Ration(TypedDict):
    id: str
    herd_id: str
    name: str
    ingredients: list
    daily_feed_cost_per_cow: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CoopPriceSheet(TypedDict):
    id: str
    herd_id: str
    settlement_month: str
    fat_price_per_lb: float
    protein_price_per_lb: float
    other_solids_price_per_lb: float
    ppd_per_cwt: float
    advance_rate_per_cwt: float
    hauling_rate_per_cwt: float
    created_at: str
    updated_at: str
    version: int


class Animal(TypedDict):
    id: str
    herd_id: str
    ear_tag: str
    birth_date: str
    dam_id: Optional[str]
    parity: int
    status: str
    milk_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Lactation(TypedDict):
    id: str
    animal_id: str
    herd_id: str
    parity: int
    calving_event_id: str
    start_date: str
    dry_off_date: Optional[str]
    cumulative_milk_lbs: float
    projected_305d_milk_lbs: float
    status: str
    created_at: str
    updated_at: str
    version: int


# append-only — id + created_at only
class TestDayRecord(TypedDict):
    id: str
    lactation_id: str
    animal_id: str
    herd_id: str
    test_date: str
    day_in_milk: int
    milk_weight_lbs: float
    fat_pct: float
    protein_pct: float
    scc_thousands: int
    included_in_milk_check_id: Optional[str]
    created_at: str


class MilkingShift(TypedDict):
    id: str
    parlor_id: str
    herd_id: str
    operator_user_id: str
    start_at: str
    end_at: str
    cows_milked: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BreedingEvent(TypedDict):
    id: str
    animal_id: str
    herd_id: str
    service_date: str
    sire_code: str
    confirm_due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CalvingEvent(TypedDict):
    id: str
    animal_id: str
    herd_id: str
    breeding_event_id: str
    calving_date: str
    opened_lactation_id: str
    closed_lactation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HealthTreatment(TypedDict):
    id: str
    animal_id: str
    herd_id: str
    drug_name: str
    administered_at: str
    milk_withhold_hours: int
    meat_withdrawal_hours: int
    milk_withhold_until: str
    meat_withdrawal_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MilkCheck(TypedDict):
    id: str
    herd_id: str
    price_sheet_id: str
    settlement_month: str
    pooled_milk_lbs: float
    pooled_fat_lbs: float
    pooled_protein_lbs: float
    pooled_other_solids_lbs: float
    weighted_scc_thousands: float
    advance_paid: float
    gross_settlement: float
    net_payable: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CullDecision(TypedDict):
    id: str
    animal_id: str
    herd_id: str
    reason: str
    disposition: str
    replacement_animal_id: Optional[str]
    decided_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
