"""Domain types for the Sterilization Services & Lot Release API.

Entity shapes, status enums and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------- roles ----
class UserRole(str, Enum):
    REGULATORY_ADMIN = "RegulatoryAdmin"
    CUSTOMER_REP = "CustomerRep"
    CYCLE_OPERATOR = "CycleOperator"
    DOSIMETRY_ANALYST = "DosimetryAnalyst"
    QUALITY_RELEASE_OFFICER = "QualityReleaseOfficer"


# ------------------------------------------------------------- enums -----
class Modality(str, Enum):
    ETO = "ETO"
    GAMMA = "GAMMA"
    EBEAM = "EBEAM"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class ChamberStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class DoseBasis(str, Enum):
    ROUTINE_MEAN = "ROUTINE_MEAN"
    MIN_ZONE = "MIN_ZONE"


class QualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    CONDITIONAL = "CONDITIONAL"
    AUDIT_DUE = "AUDIT_DUE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class QualificationMethod(str, Enum):
    VDMAX_15 = "VDMAX_15"
    VDMAX_25 = "VDMAX_25"
    METHOD_1 = "METHOD_1"


class AuditOutcome(str, Enum):
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    STAGED = "STAGED"
    IN_PROCESS = "IN_PROCESS"
    PROCESSED = "PROCESSED"
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    SCRAPPED = "SCRAPPED"
    RECALLED = "RECALLED"


class ResidualStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING_AERATION = "PENDING_AERATION"
    AERATING = "AERATING"
    RESIDUAL_PASS = "RESIDUAL_PASS"
    RESIDUAL_FAIL = "RESIDUAL_FAIL"


class QuarantineReason(str, Enum):
    NONE = "NONE"
    ROUTINE = "ROUTINE"
    DOSE_DEVIATION = "DOSE_DEVIATION"
    BI_POSITIVE = "BI_POSITIVE"
    RESIDUAL_FAIL = "RESIDUAL_FAIL"
    ADVERSE_EVENT = "ADVERSE_EVENT"


class ReleaseMode(str, Enum):
    NONE = "NONE"
    PARAMETRIC = "PARAMETRIC"
    DOSIMETRIC = "DOSIMETRIC"


class CycleStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    READY = "READY"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    DOSIMETRY_REVIEW = "DOSIMETRY_REVIEW"
    DOSE_CONFORMING = "DOSE_CONFORMING"
    DOSE_DEVIATION = "DOSE_DEVIATION"
    CANCELLED = "CANCELLED"


class DeviationCode(str, Enum):
    NONE = "NONE"
    BI_POSITIVE = "BI_POSITIVE"
    UNDERDOSE = "UNDERDOSE"
    OVERDOSE = "OVERDOSE"


class PositionZone(str, Enum):
    MIN_DOSE = "MIN_DOSE"
    MAX_DOSE = "MAX_DOSE"
    INTERIOR = "INTERIOR"
    EDGE = "EDGE"


class IndicatorType(str, Enum):
    DOSIMETER = "DOSIMETER"
    BIOLOGICAL = "BIOLOGICAL"


class PlacementZone(str, Enum):
    MIN_DOSE = "MIN_DOSE"
    MAX_DOSE = "MAX_DOSE"
    ROUTINE = "ROUTINE"


class BiResult(str, Enum):
    PENDING = "PENDING"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class ReadingStatus(str, Enum):
    UNREAD = "UNREAD"
    READ = "READ"


class AerationStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    RETEST_REQUIRED = "RETEST_REQUIRED"
    PASSED = "PASSED"
    EXHAUSTED = "EXHAUSTED"


class AerationVariant(str, Enum):
    STANDARD = "STANDARD"
    EXTENDED_RETEST = "EXTENDED_RETEST"


class AdverseEventType(str, Enum):
    STERILITY_COMPLAINT = "STERILITY_COMPLAINT"
    RESIDUAL_EXCEEDANCE = "RESIDUAL_EXCEEDANCE"
    FIELD_DOSE_DEVIATION = "FIELD_DOSE_DEVIATION"
    PACKAGING_BREACH = "PACKAGING_BREACH"


class AdverseEventSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AdverseEventStatus(str, Enum):
    REPORTED = "REPORTED"
    RESTERILIZE_APPROVED = "RESTERILIZE_APPROVED"
    SCRAP_APPROVED = "SCRAP_APPROVED"
    DISMISSED = "DISMISSED"


class Disposition(str, Enum):
    RESTERILIZE = "RESTERILIZE"
    SCRAP = "SCRAP"
    DISMISS = "DISMISS"


# ------------------------------------------------------- entity shapes ---
# Every resource carries id + created_at. All of them except DoseAudit also
# carry updated_at and version.


class Customer(TypedDict):
    id: str
    name: str
    account_code: str
    contracted_modalities: List[str]
    status: str
    open_lot_count: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    customer_id: str
    product_code: str
    pallet_mass_kg: float
    pallet_volume_m3: float
    max_allowed_dose_kgy: float
    max_cumulative_dose_kgy: float
    eto_residual_limit_ppm: float
    ech_residual_limit_ppm: float
    requires_aeration: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EmissionPermit(TypedDict):
    id: str
    permit_code: str
    permit_year: int
    annual_allowance_kg: float
    consumed_kg_ytd: float
    total_emission_fee_usd: float
    max_concurrent_eto_cycles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Chamber(TypedDict):
    id: str
    permit_id: str
    chamber_code: str
    modality: str
    pallet_capacity: int
    turnaround_minutes: int
    abatement_efficiency_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CycleRecipe(TypedDict):
    id: str
    recipe_code: str
    modality: str
    density_min_g_per_cm3: float
    density_max_g_per_cm3: float
    target_dose_kgy: float
    min_dose_kgy: float
    max_dose_kgy: float
    dose_basis: str
    aeration_base_hours: int
    required_min_zone_dosimeters: int
    required_routine_dosimeters: int
    required_biological_indicators: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductQualification(TypedDict):
    id: str
    product_id: str
    recipe_id: str
    method: str
    verification_dose_kgy: float
    sal_exponent: int
    audit_interval_days: int
    last_audit_at: Optional[str]
    next_audit_due_at: Optional[str]
    consecutive_conditional_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DoseAudit(TypedDict):
    """A dose audit is an immutable laboratory record: id + created_at only."""

    id: str
    qualification_id: str
    performed_at: str
    samples_tested: int
    positives: int
    verification_dose_kgy_applied: float
    outcome: str
    next_audit_due_at: Optional[str]
    qualification_status_after: str
    created_at: str


class Lot(TypedDict):
    id: str
    customer_id: str
    product_id: str
    parent_lot_id: Optional[str]
    lot_code: str
    total_pallet_count: int
    staged_pallet_count: int
    available_pallet_count: int
    status: str
    residual_status: str
    quarantine_reason: str
    cumulative_dose_kgy: float
    resterilization_count: int
    schedulable: bool
    release_mode: str
    released_at: Optional[str]
    released_by_user_id: Optional[str]
    release_dose_kgy: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Cycle(TypedDict):
    id: str
    chamber_id: str
    recipe_id: str
    cycle_code: str
    scheduled_start_at: str
    scheduled_end_at: str
    occupancy_end_at: str
    raw_eto_charge_kg: float
    abated_eto_kg: float
    emission_fee_usd: float
    loaded_pallet_count: int
    load_density_g_per_cm3: float
    delivered_dose_kgy: Optional[float]
    max_observed_dose_kgy: Optional[float]
    deviation_code: str
    operator_user_id: Optional[str]
    dosimetry_closed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadPosition(TypedDict):
    id: str
    cycle_id: str
    lot_id: str
    position_index: int
    zone: str
    pallet_count: int
    cycle_version_after: int
    created_at: str
    updated_at: str
    version: int


class Indicator(TypedDict):
    id: str
    load_position_id: str
    indicator_type: str
    placement_zone: str
    serial_code: str
    spore_population: Optional[int]
    measured_dose_kgy: Optional[float]
    bi_result: str
    reading_status: str
    read_at: Optional[str]
    read_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AerationRecord(TypedDict):
    id: str
    lot_id: str
    aeration_start_at: str
    base_hours: int
    density_factor: float
    required_hours: int
    target_end_at: str
    retest_count: int
    last_failed_sample_at: Optional[str]
    last_eto_ppm: Optional[float]
    last_ech_ppm: Optional[float]
    variant_applied: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict):
    id: str
    lot_id: str
    lot_version_after: int
    event_type: str
    severity: str
    description: str
    reported_by_user_id: str
    disposition: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
