"""Domain enums and response shapes for the seed production and conditioning API."""

from __future__ import annotations

from enum import Enum
from typing import TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    FIELD_OFFICER = "FieldOfficer"
    CONDITIONING_MANAGER = "ConditioningManager"
    CERTIFICATION_AGENCY = "CertificationAgency"
    SETTLEMENT_ACCOUNTANT = "SettlementAccountant"
    GROWER = "Grower"


# ---------------------------------------------------------------------------
# Reference-data enums
# ---------------------------------------------------------------------------


class CropKind(str, Enum):
    WHEAT = "WHEAT"
    TRITICALE = "TRITICALE"
    SOYBEAN = "SOYBEAN"
    SUNFLOWER = "SUNFLOWER"
    ALFALFA = "ALFALFA"
    CANOLA = "CANOLA"


class SeedClass(str, Enum):
    FOUNDATION = "FOUNDATION"
    REGISTERED = "REGISTERED"
    CERTIFIED = "CERTIFIED"


class ContractSeedClass(str, Enum):
    FOUNDATION = "FOUNDATION"
    REGISTERED = "REGISTERED"
    CERTIFIED = "CERTIFIED"
    COMMERCIAL_INCREASE = "COMMERCIAL_INCREASE"


class SignalWord(str, Enum):
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    DANGER = "DANGER"


class EquipmentKind(str, Enum):
    COMBINE = "COMBINE"
    TRUCK = "TRUCK"
    AUGER = "AUGER"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class GrowerStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    PLANTED = "PLANTED"
    ROGUEING_REQUIRED = "ROGUEING_REQUIRED"
    INSPECTION_PASSED = "INSPECTION_PASSED"
    HARVESTED = "HARVESTED"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class EligibilityVariant(str, Enum):
    STRICT_HISTORY = "STRICT_HISTORY"
    DECAY_WEIGHTED = "DECAY_WEIGHTED"


class EligibilityDecision(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class InspectionOutcome(str, Enum):
    PASSED = "PASSED"
    ROGUEING_ORDERED = "ROGUEING_ORDERED"
    FAILED = "FAILED"


class InspectionStatus(str, Enum):
    RECORDED = "RECORDED"
    ROGUEING_DECLARED = "ROGUEING_DECLARED"
    ROGUEING_VERIFIED = "ROGUEING_VERIFIED"
    CLOSED = "CLOSED"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DIRTY = "DIRTY"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class LineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ConditioningStatus(str, Enum):
    RAW = "RAW"
    CLEANED = "CLEANED"
    SIZED = "SIZED"
    TREATED = "TREATED"
    BAGGED = "BAGGED"


class CertificationStatus(str, Enum):
    UNSAMPLED = "UNSAMPLED"
    SAMPLED = "SAMPLED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    TAGGED = "TAGGED"
    RETEST_DUE = "RETEST_DUE"


class Disposition(str, Enum):
    NONE = "NONE"
    DOWNGRADE_TO_COMMERCIAL = "DOWNGRADE_TO_COMMERCIAL"


class ConditioningStage(str, Enum):
    CLEANING = "CLEANING"
    SIZING = "SIZING"
    TREATING = "TREATING"
    BAGGING = "BAGGING"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    REVERSED = "REVERSED"


class SampleKind(str, Enum):
    INITIAL = "INITIAL"
    RETEST = "RETEST"


class SampleResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class TagStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    COMPUTED = "COMPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Entity response shapes
#
# Variety, TreatmentProduct, FieldHistoryRecord and HarvestEvent carry only
# ``id`` and ``created_at``; they have no ``updated_at`` and no ``version``.
# Every other entity carries the full common-field set.
# ---------------------------------------------------------------------------


class Variety(TypedDict):
    id: str
    created_at: str
    crop_kind: str
    variety_name: str
    max_seed_class: str
    isolation_min_m: float
    restricted_prior_crop_kinds: list[str]
    restricted_prior_crop_years: int
    germination_min_pct: float
    purity_min_pct: float
    max_off_type_per_10000: float
    max_restricted_weed_per_10000: float
    max_disease_incidence_pct: float
    max_rogueing_rounds: int
    estimated_conditioning_shrink_pct: float
    germ_validity_days: int
    max_carryover_generations: int
    treatment_required: bool


class TreatmentProduct(TypedDict):
    id: str
    created_at: str
    product_code: str
    epa_registration_number: str
    allowed_crop_kinds: list[str]
    max_rate_g_per_100kg: float
    requires_dye: bool
    restricted_use: bool
    label_signal_word: str | None


class Grower(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    grower_name: str
    region_code: str
    contact_email: str
    status: str
    compliance_flag_count: int


class ProductionField(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    grower_id: str
    field_code: str
    acres: float
    isolation_distance_m: float
    last_assessed_risk_score: float | None
    history_record_count: int


class FieldHistoryRecord(TypedDict):
    id: str
    created_at: str
    production_field_id: str
    crop_kind: str
    crop_year: int
    source_note: str


class ProductionContract(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    grower_id: str
    variety_id: str
    production_field_id: str
    season_year: int
    seed_class: str
    contracted_acres: float
    base_price_per_unit_cents: int
    conditioning_charge_per_unit_cents: int
    advance_total_cents: int
    advance_outstanding_cents: int
    status: str
    planted_on: str | None
    inspection_round: int
    rogueing_rounds_used: int
    eligibility_variant_applied: str | None
    eligibility_risk_score: float | None
    provisional_clean_units_total: float
    certified_units_total: float
    requires_field_officer_review: bool
    cancel_reason: str | None


class FieldInspection(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    production_contract_id: str
    inspector_user_id: str
    inspection_round: int
    inspected_on: str
    sampled_plants: int
    off_type_plants: int
    restricted_weed_plants: int
    diseased_plants: int
    isolation_verified_m: float
    off_type_rate_per_10000: float
    weed_rate_per_10000: float
    disease_incidence_pct: float
    outcome: str
    status: str
    rogueing_plants_removed: int | None
    rogueing_declared_on: str | None
    rogueing_verified_by_user_id: str | None
    verified_remaining_off_type_plants: int | None


class HarvestEquipment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    equipment_code: str
    equipment_kind: str
    cleanout_minutes_required: int
    status: str
    last_cleanout_at: str | None
    last_cleanout_variety_id: str | None
    cleanout_certified: bool


class HarvestEvent(TypedDict):
    id: str
    created_at: str
    production_contract_id: str
    harvest_equipment_id: str
    seed_lot_id: str
    window_start: str
    window_end: str
    gross_weight_kg: float
    moisture_pct: float
    bag_size_kg: float
    moisture_dockage_pct: float
    provisional_clean_kg: float
    provisional_clean_units: float


class ConditioningLine(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    line_code: str
    cleanout_minutes_required: int
    capacity_kg_per_hour: float
    status: str
    last_cleanout_variety_id: str | None
    last_run_end_utc: str | None


class SeedLot(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    lot_code: str
    variety_id: str
    production_contract_id: str
    parent_seed_lot_id: str | None
    season_year: int
    carryover_generation: int
    gross_kg: float
    current_kg: float
    cumulative_shrink_kg: float
    dockage_pct: float
    bag_size_kg: float
    bag_count: int
    tagged_bag_count: int
    intake_moisture_pct: float
    provisional_clean_units: float
    final_clean_units: float | None
    conditioning_status: str
    certification_status: str
    germination_pct: float | None
    purity_pct: float | None
    weed_seed_count_per_kg: int | None
    germination_valid_until: str | None
    adjusted_price_per_unit_cents: int | None
    disposition: str


class ConditioningRun(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    seed_lot_id: str
    conditioning_line_id: str
    stage: str
    window_start: str
    window_end: str
    input_kg: float
    output_kg: float | None
    shrink_kg: float | None
    bag_count: int | None
    status: str
    treatment_product_id: str | None
    treatment_rate_g_per_100kg: float | None
    label_text: str | None
    cleanout_buffer_applied_minutes: int
    reversal_reason: str | None


class LotSample(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    seed_lot_id: str
    sample_kind: str
    sampled_on: str
    sampler_user_id: str
    germination_pct: float | None
    purity_pct: float | None
    inert_pct: float | None
    weed_seed_count_per_kg: int | None
    tested_at: str | None
    result: str
    germination_valid_until: str | None


class CertificationTag(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    seed_lot_id: str
    lot_sample_id: str
    tag_serial: str
    tag_class: str
    bag_count: int
    issued_at: str
    status: str
    void_reason: str | None


class GrowerSettlement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    production_contract_id: str
    computed_by_user_id: str
    approved_by_user_id: str | None
    line_count: int
    settled_units_total: float
    gross_payable_cents: int
    conditioning_charges_cents: int
    provisional_net_cents: int
    recovery_cap_pct: float
    advance_recovery_cents: int
    net_payable_cents: int
    status: str
    dispute_reason: str | None
    payment_reference: str | None
    quality_hold: bool


class EligibilityAssessment(TypedDict, total=False):
    """Computed eligibility read; both variants are returned side by side."""

    strict_history_result: str
    decay_weighted_result: str
    restricted_record_count: int
    history_component: float
    isolation_component: float
    contamination_risk_score: float
    isolation_shortfall_m: float
    applied_variant: str
    applied_result: str
    blocking_error_id: str | None
