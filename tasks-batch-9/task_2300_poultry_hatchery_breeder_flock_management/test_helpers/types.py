"""Typed shapes and enumerations for the Poultry Hatchery & Breeder Flock API.

The TypedDicts document the field surface each entity exposes; they are used for
editor support and for the assertion helpers, never for runtime validation.

Note the deliberate asymmetry on ``EnvironmentReading``: per PRD 2.5 it is the
one record that carries only ``id`` and ``created_at`` — no ``updated_at`` and no
``version`` at all.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """The six recognised role names."""

    HATCHERY_MANAGER = "HatcheryManager"
    FLOCK_MANAGER = "FlockManager"
    INCUBATION_OPERATOR = "IncubationOperator"
    CHICK_PROCESSOR = "ChickProcessor"
    VETERINARIAN = "Veterinarian"
    GROWER_FARM = "GrowerFarm"

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.value


# ---------------------------------------------------------------------------
# Shared enumerations
# ---------------------------------------------------------------------------


class Breed(str, Enum):
    ROSS_308 = "ROSS_308"
    COBB_500 = "COBB_500"
    HUBBARD_JA87 = "HUBBARD_JA87"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class UnitType(str, Enum):
    SETTER = "SETTER"
    HATCHER = "HATCHER"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class SanitationStatus(str, Enum):
    DIRTY = "DIRTY"
    SANITIZED = "SANITIZED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class OccupancyStatus(str, Enum):
    FREE = "FREE"
    OCCUPIED = "OCCUPIED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class FlockStatus(str, Enum):
    PLACED = "PLACED"
    IN_LAY = "IN_LAY"
    EGG_HOLD = "EGG_HOLD"
    DEPLETED = "DEPLETED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class EggLotStatus(str, Enum):
    COLLECTED = "COLLECTED"
    GRADED = "GRADED"
    IN_STORAGE = "IN_STORAGE"
    SANITATION_HOLD = "SANITATION_HOLD"
    ALLOCATED = "ALLOCATED"
    SET = "SET"
    CONSUMED = "CONSUMED"
    CONDEMNED = "CONDEMNED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class CondemnedReason(str, Enum):
    FLOCK_EGG_HOLD = "FLOCK_EGG_HOLD"
    LOAD_ABORTED = "LOAD_ABORTED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class SetterLoadStatus(str, Enum):
    PLANNED = "PLANNED"
    INCUBATING = "INCUBATING"
    CANDLED = "CANDLED"
    TRANSFERRED = "TRANSFERRED"
    ABORTED = "ABORTED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class EnvironmentStatus(str, Enum):
    """The independent environment dimension of a setter load (PRD 3.5)."""

    NOMINAL = "NOMINAL"
    DEVIATION_OPEN = "DEVIATION_OPEN"
    DEVIATION_RESOLVED = "DEVIATION_RESOLVED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class ItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class HatcherLoadStatus(str, Enum):
    HATCHING = "HATCHING"
    EARLY_PULLED = "EARLY_PULLED"
    WINDOW_PULLED = "WINDOW_PULLED"
    LATE_PULLED = "LATE_PULLED"
    PROCESSED = "PROCESSED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class PullClass(str, Enum):
    EARLY = "EARLY"
    WINDOW = "WINDOW"
    LATE = "LATE"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class QualityFlag(str, Enum):
    NONE = "NONE"
    UNHEALED_NAVEL = "UNHEALED_NAVEL"
    DEHYDRATION = "DEHYDRATION"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class ChickBatchStatus(str, Enum):
    PULLED = "PULLED"
    SEXED = "SEXED"
    VACCINATED = "VACCINATED"
    BOXED = "BOXED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class BiosecurityStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    QUARANTINED = "QUARANTINED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class OrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    DELIVERED = "DELIVERED"
    REVERSED = "REVERSED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class LabSubjectType(str, Enum):
    BREEDER_FLOCK = "BREEDER_FLOCK"
    INCUBATION_UNIT = "INCUBATION_UNIT"
    GROWER_FARM = "GROWER_FARM"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class LabTestCode(str, Enum):
    SALMONELLA_PULLORUM = "SALMONELLA_PULLORUM"
    MYCOPLASMA_GALLISEPTICUM = "MYCOPLASMA_GALLISEPTICUM"
    AVIAN_INFLUENZA = "AVIAN_INFLUENZA"
    SHELL_HYGIENE = "SHELL_HYGIENE"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class LabTestStatus(str, Enum):
    PENDING = "PENDING"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    INVALID = "INVALID"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class LabResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    INVALID = "INVALID"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    IMPLEMENTED = "IMPLEMENTED"
    VERIFIED = "VERIFIED"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class TriggerReason(str, Enum):
    HATCHABILITY_BELOW_THRESHOLD = "HATCHABILITY_BELOW_THRESHOLD"
    REPEATED_LATE_PULL = "REPEATED_LATE_PULL"
    LAB_POSITIVE = "LAB_POSITIVE"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


class VerificationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"

    def __str__(self) -> str:  # pragma: no cover
        return self.value


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class _Common(TypedDict):
    """Fields every record but the environment reading carries (PRD 2.5)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class FlockProgram(_Common):
    code: str
    breed: str
    stimulation_week: int
    lighting_steps: List[Dict[str, Any]]
    feed_steps: List[Dict[str, Any]]
    retired: bool


class IncubationProfile(_Common):
    code: str
    breed: str
    transfer_hours: int
    total_hours: int
    stages: List[Dict[str, Any]]
    retired: bool


class IncubationUnit(_Common):
    code: str
    unit_type: str
    capacity_eggs: int
    sanitation_status: str
    occupancy_status: str
    sanitized_at: Optional[str]


class BreederFlock(_Common):
    code: str
    program_id: str
    breed: str
    house_code: str
    hatch_date: str
    placed_at: str
    hen_count: int
    source_flock_id: Optional[str]
    status: str
    age_weeks: int
    photoperiod_hours: float
    feed_grams_per_hen_day: float
    production_rate_pct: float
    lighting_factor: float
    nutrition_factor: float
    settable_forecast: int
    corrective_action_count: int
    late_pull_count: int
    hatchability_rolling_pct: Optional[float]
    hatchability_fertile_pct: Optional[float]
    egg_hold_opened_at: Optional[str]
    egg_hold_opened_by_user_id: Optional[str]


class EggLot(_Common):
    flock_id: str
    collected_at: str
    collected_count: int
    grade_a_count: Optional[int]
    cracked_count: Optional[int]
    dirty_count: Optional[int]
    small_count: Optional[int]
    settable_count: int
    eggs_remaining: int
    storage_temp_c: Optional[float]
    stored_at: Optional[str]
    sanitation_cycle_count: int
    effective_age_days: float
    status: str
    condemned_reason: Optional[str]


class SetterLoad(_Common):
    unit_id: str
    profile_id: str
    planned_set_at: str
    set_at: Optional[str]
    status: str
    environment_status: str
    total_eggs_set: int
    weighted_age_days: Optional[float]
    storage_delay_hours: Optional[int]
    planned_transfer_at: Optional[str]
    planned_pull_at: Optional[str]
    pull_window_start_at: Optional[str]
    pull_window_end_at: Optional[str]
    fertile_count: Optional[int]
    fertility_pct: Optional[float]
    deviation_degree_hours: float
    deviation_opened_at: Optional[str]
    abort_reason: Optional[str]


class SetterLoadItem(_Common):
    setter_load_id: str
    egg_lot_id: str
    eggs_taken: int
    effective_age_days_at_set: float
    item_status: str


class EnvironmentReading(TypedDict):
    """Append-only probe sample: only ``id`` and ``created_at`` (PRD 2.5)."""

    id: str
    created_at: str
    setter_load_id: str
    recorded_at: str
    temp_c: float
    humidity_pct: float
    elapsed_hours: float
    target_temp_c: float
    abs_deviation_c: float
    segment_degree_hours: float


class HatcherLoad(_Common):
    setter_load_id: str
    unit_id: str
    status: str
    transferred_at: str
    eggs_transferred: int
    planned_pull_at: str
    pull_window_start_at: str
    pull_window_end_at: str
    inherited_degree_hours: float
    actual_pull_at: Optional[str]
    pull_offset_hours: Optional[float]
    pull_class: Optional[str]
    quality_flag: str
    hold_release_at: Optional[str]


class ChickBatch(_Common):
    hatcher_load_id: str
    primary_flock_id: str
    breed: str
    hatched_count: int
    male_count: Optional[int]
    female_count: Optional[int]
    unsexed_count: Optional[int]
    sexing_cull_count: Optional[int]
    preliminary_yield_pct: Optional[float]
    vaccine_code: Optional[str]
    vaccine_reject_rate: Optional[float]
    vaccine_cull_count: Optional[int]
    cull_count: Optional[int]
    saleable_count: Optional[int]
    final_yield_pct: Optional[float]
    box_count: Optional[int]
    unassigned_chicks: Optional[int]
    quality_score_provisional: float
    quality_score_final: Optional[float]
    status: str


class GrowerFarm(_Common):
    code: str
    operator_user_id: str
    capacity_chicks: int
    biosecurity_status: str
    cleared_at: Optional[str]


class GrowerPlacementOrder(_Common):
    farm_id: str
    requested_breed: str
    requested_placement_date: str
    requested_chicks: int
    allocated_chicks: int
    remaining_need: int
    status: str


class DeliveryAssignment(_Common):
    chick_batch_id: str
    placement_order_id: str
    chicks_assigned: int
    boxes_assigned: int
    scheduled_delivery_date: str
    delivered_at: Optional[str]
    reversal_reason: Optional[str]
    status: str


class LabTest(_Common):
    subject_type: str
    subject_id: str
    test_code: str
    collected_at: str
    status: str
    result: Optional[str]
    released_at: Optional[str]


class CorrectiveAction(_Common):
    flock_id: str
    trigger_reason: str
    observed_hatchability_pct: Optional[float]
    status: str
    verification_round: int
    implementation_note: Optional[str]
    opened_at: str
    opened_by_user_id: str


#: Entities that carry the full common-field set (PRD 2.5).
VERSIONED_ENTITIES = (
    "FlockProgram",
    "IncubationProfile",
    "IncubationUnit",
    "BreederFlock",
    "EggLot",
    "SetterLoad",
    "SetterLoadItem",
    "HatcherLoad",
    "ChickBatch",
    "GrowerFarm",
    "GrowerPlacementOrder",
    "DeliveryAssignment",
    "LabTest",
    "CorrectiveAction",
)
