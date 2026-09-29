"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    TECHNICAL_DIRECTOR = "TechnicalDirector"
    FLAVORIST = "Flavorist"
    REGULATORY_AFFAIRS = "RegulatoryAffairs"
    LAB_TECH = "LabTech"
    PURCHASING_MANAGER = "PurchasingManager"


class MatrixType(str, Enum):
    BEVERAGE_STILL = "BEVERAGE_STILL"
    BEVERAGE_CARBONATED = "BEVERAGE_CARBONATED"
    DAIRY_YOGURT = "DAIRY_YOGURT"
    BAKERY_SWEET = "BAKERY_SWEET"
    SAVOURY_SNACK = "SAVOURY_SNACK"


class TargetProfile(str, Enum):
    CITRUS_TOP_NOTE = "CITRUS_TOP_NOTE"
    VANILLA_CREAM = "VANILLA_CREAM"
    RED_FRUIT = "RED_FRUIT"
    SAVOURY_UMAMI = "SAVOURY_UMAMI"
    MINT_COOL = "MINT_COOL"


class ConfidentialityTier(str, Enum):
    TIER_1_STANDARD = "TIER_1_STANDARD"
    TIER_2_RESTRICTED = "TIER_2_RESTRICTED"
    TIER_3_BLACK_BOX = "TIER_3_BLACK_BOX"


class AllergenCode(str, Enum):
    MILK = "MILK"
    EGG = "EGG"
    SOY = "SOY"
    WHEAT = "WHEAT"
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    FISH = "FISH"
    CELERY = "CELERY"
    MUSTARD = "MUSTARD"
    SESAME = "SESAME"
    SULPHITES = "SULPHITES"


class BriefStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CLOSED_WON = "CLOSED_WON"
    CLOSED_LOST = "CLOSED_LOST"


class BriefOutcome(str, Enum):
    WON = "WON"
    LOST = "LOST"


class LossReason(str, Enum):
    PRICE = "PRICE"
    PERFORMANCE = "PERFORMANCE"
    REGULATORY = "REGULATORY"
    TIMING = "TIMING"
    OTHER = "OTHER"


class NaturalStatus(str, Enum):
    NATURAL = "NATURAL"
    NATURAL_FLAVOR_WONF = "NATURAL_FLAVOR_WONF"
    NATURE_IDENTICAL = "NATURE_IDENTICAL"
    ARTIFICIAL = "ARTIFICIAL"


class PotencyClass(str, Enum):
    HIGH_IMPACT = "HIGH_IMPACT"
    STANDARD = "STANDARD"


class ClaimStatus(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"


class ClaimType(str, Enum):
    ALLERGEN_FREE_STATEMENT = "ALLERGEN_FREE_STATEMENT"
    KOSHER = "KOSHER"
    HALAL = "HALAL"
    NATURAL = "NATURAL"


class SubstantiationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REVOKED = "REVOKED"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    COSTED = "COSTED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class ReworkReason(str, Enum):
    DIRECTOR_REJECTION = "DIRECTOR_REJECTION"
    APPLICATION_TEST_FAILURE = "APPLICATION_TEST_FAILURE"
    SUBSTANTIATION_REVOKED = "SUBSTANTIATION_REVOKED"
    RAW_MATERIAL_REPRICED = "RAW_MATERIAL_REPRICED"


class ComponentType(str, Enum):
    RAW_MATERIAL = "RAW_MATERIAL"
    SUB_FORMULA = "SUB_FORMULA"


class LotQcStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class LotDispositionStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"
    SCRAPPED = "SCRAPPED"


class RetentionStatus(str, Enum):
    STORED = "STORED"
    WITHDRAWN = "WITHDRAWN"


class TestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PACKET_ASSEMBLED = "PACKET_ASSEMBLED"
    BLOCKED = "BLOCKED"
    DISPATCHED = "DISPATCHED"
    CANCELLED = "CANCELLED"


class BlockReason(str, Enum):
    LOT_HELD = "LOT_HELD"
    SUBSTANTIATION_REVOKED = "SUBSTANTIATION_REVOKED"


class ShipmentCancellationReason(str, Enum):
    BRIEF_CLOSED_LOST = "BRIEF_CLOSED_LOST"


class DocType(str, Enum):
    SDS = "SDS"
    ALLERGEN_STATEMENT = "ALLERGEN_STATEMENT"
    NATURAL_DECLARATION = "NATURAL_DECLARATION"
    KOSHER_CERT = "KOSHER_CERT"
    HALAL_CERT = "HALAL_CERT"
    EXPORT_DECLARATION = "EXPORT_DECLARATION"
    IP_NDA_ADDENDUM = "IP_NDA_ADDENDUM"


class DocumentStatus(str, Enum):
    PINNED = "PINNED"
    STALE = "STALE"


class BatchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    TOLERANCE_SET = "TOLERANCE_SET"
    PILOT_RUN = "PILOT_RUN"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class BatchCancellationReason(str, Enum):
    FORMULA_REWORK = "FORMULA_REWORK"
    PARENT_SUPERSEDED = "PARENT_SUPERSEDED"
    BATCH_SUPERSEDED = "BATCH_SUPERSEDED"


class ForecastStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    SUPERSEDED = "SUPERSEDED"
    REALIZED = "REALIZED"
    LAPSED = "LAPSED"


class ForecastVariant(str, Enum):
    RISK_WEIGHTED = "RISK_WEIGHTED"
    COMMITTED = "COMMITTED"


class RedactionLevel(str, Enum):
    REDACTED = "REDACTED"
    FULL = "FULL"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


# --- Entity shapes.  Every entity in this API carries id, created_at,
# --- updated_at and version.


class CustomerBrief(TypedDict):
    id: str
    brief_code: str
    customer_name: str
    matrix_type: str
    target_profile: str
    dosage_pct: float
    annual_volume_kg: int
    cost_in_use_cap_cents_per_tonne: int
    confidentiality_tier: str
    natural_claim_required: bool
    kosher_required: bool
    halal_required: bool
    allergen_exclusions: List[str]
    status: str
    clarification_round_count: int
    clarification_note: Optional[str]
    decision_note: Optional[str]
    outcome: Optional[str]
    loss_reason: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RawMaterial(TypedDict):
    id: str
    material_code: str
    name: str
    cost_per_kg_cents: int
    natural_status: str
    potency_class: str
    max_use_ppm: int
    allergen_codes: List[str]
    claim_status: str
    verified_claim_types: List[str]
    created_at: str
    updated_at: str
    version: int


class SubstantiationRecord(TypedDict):
    id: str
    raw_material_id: str
    claim_type: str
    issuing_body: str
    document_ref: str
    valid_until: str
    status: str
    verified_at: Optional[str]
    revocation_reason: Optional[str]
    is_expired: bool
    created_at: str
    updated_at: str
    version: int


class Formula(TypedDict):
    id: str
    brief_id: str
    name: str
    parent_formula_id: Optional[str]
    confidentiality_tier: str
    iteration_no: int
    status: str
    component_count: int
    total_weight_pct: float
    bench_cost_per_kg_cents: Optional[int]
    bench_cost_in_use_cents_per_tonne: Optional[int]
    firm_cost_in_use_cents_per_tonne: Optional[int]
    cost_stale: bool
    allergen_codes: List[str]
    natural_claim_eligible: Optional[bool]
    kosher_eligible: Optional[bool]
    halal_eligible: Optional[bool]
    superseded_by_formula_id: Optional[str]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rework_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FormulaComponent(TypedDict):
    id: str
    formula_id: str
    component_type: str
    raw_material_id: Optional[str]
    sub_formula_id: Optional[str]
    weight_pct: float
    sequence_no: int
    contribution_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SampleLot(TypedDict):
    id: str
    formula_id: str
    lot_number: str
    formula_iteration_no: int
    batch_size_g: int
    allocated_g: int
    available_g: int
    qc_status: str
    disposition_status: str
    qc_note: Optional[str]
    compounded_by_user_id: str
    qc_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetentionCabinet(TypedDict):
    id: str
    cabinet_code: str
    capacity_slots: int
    storage_temp_c: float
    slots_available: int
    created_at: str
    updated_at: str
    version: int


class RetentionSample(TypedDict):
    id: str
    sample_lot_id: str
    cabinet_id: str
    quantity_g: int
    slot_count: int
    stored_from: str
    stored_until: str
    status: str
    withdrawal_reason: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApplicationRig(TypedDict):
    id: str
    rig_code: str
    matrix_type: str
    cleanout_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class ApplicationTest(TypedDict):
    id: str
    sample_lot_id: str
    rig_id: str
    window_start: str
    window_end: str
    dosage_pct: float
    consumed_g: int
    status: str
    aroma_score: Optional[float]
    taste_score: Optional[float]
    stability_score: Optional[float]
    panel_score: Optional[float]
    verdict_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SampleShipment(TypedDict):
    id: str
    sample_lot_id: str
    brief_id: str
    destination_country: str
    shipped_g: int
    carrier: Optional[str]
    status: str
    required_document_types: List[str]
    packet_valid_until: Optional[str]
    tracking_reference: Optional[str]
    dispatched_at: Optional[str]
    block_reason: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegulatoryDocument(TypedDict):
    id: str
    shipment_id: str
    doc_type: str
    status: str
    substantiation_id: Optional[str]
    pinned_substantiation_version: Optional[int]
    pinned_valid_until: Optional[str]
    generated_at: str
    created_at: str
    updated_at: str
    version: int


class ScaleUpBatch(TypedDict):
    id: str
    formula_id: str
    target_kg: int
    pinned_formula_version: int
    status: str
    material_cost_cents: Optional[int]
    compounding_fee_pct: Optional[float]
    compounding_fee_cents: Optional[int]
    batch_total_cents: Optional[int]
    production_cost_per_kg_cents: Optional[int]
    tolerance_spec: List[dict]
    measured_yield_kg: Optional[float]
    yield_variance_pct: Optional[float]
    decision_note: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommercializationForecast(TypedDict):
    id: str
    brief_id: str
    annual_volume_kg: int
    unit_price_cents_per_kg: int
    pinned_brief_version: int
    base_annual_value_cents: int
    stage_probability: float
    technical_factor: float
    weighted_annual_value_cents: int
    variant_applied: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DisclosureGrant(TypedDict):
    id: str
    brief_id: str
    formula_id: str
    disclosed_tier: str
    redaction_level: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
