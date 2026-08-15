"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity descriptions. Append-only event records
(CCP observations, cut records, humane-handling audits) carry only
``id`` and ``created_at`` per the PRD's common-resource rules.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    QA_MANAGER = "QAManager"
    QA_TECH = "QATech"
    LAB_ANALYST = "LabAnalyst"
    INSPECTOR = "Inspector"
    PRODUCTION_MANAGER = "ProductionManager"


class ProcessType(str, Enum):
    SLAUGHTER = "SLAUGHTER"
    RAW_GROUND = "RAW_GROUND"
    RAW_INTACT = "RAW_INTACT"
    COOKED_RTE = "COOKED_RTE"


class HazardCategory(str, Enum):
    BIOLOGICAL = "BIOLOGICAL"
    CHEMICAL = "CHEMICAL"
    PHYSICAL = "PHYSICAL"


class Species(str, Enum):
    BOVINE = "BOVINE"
    SWINE = "SWINE"
    OVINE = "OVINE"
    POULTRY = "POULTRY"


class PrimalType(str, Enum):
    CHUCK = "CHUCK"
    RIB = "RIB"
    LOIN = "LOIN"
    ROUND = "ROUND"
    BRISKET = "BRISKET"
    BELLY = "BELLY"
    HAM = "HAM"
    OTHER = "OTHER"


class Organism(str, Enum):
    ECOLI_O157H7 = "ECOLI_O157H7"
    SALMONELLA = "SALMONELLA"
    LISTERIA_MONOCYTOGENES = "LISTERIA_MONOCYTOGENES"
    GENERIC_ECOLI = "GENERIC_ECOLI"


class SampleType(str, Enum):
    CARCASS_SWAB = "CARCASS_SWAB"
    GROUND_PRODUCT = "GROUND_PRODUCT"
    ENVIRONMENTAL = "ENVIRONMENTAL"


class LabelClaim(str, Enum):
    ORGANIC = "ORGANIC"
    GRASS_FED = "GRASS_FED"
    NO_ANTIBIOTICS_EVER = "NO_ANTIBIOTICS_EVER"
    NATURAL = "NATURAL"


class RecallScope(str, Enum):
    ONE_STEP_BACK = "ONE_STEP_BACK"
    ONE_STEP_FORWARD = "ONE_STEP_FORWARD"
    FULL = "FULL"


class PlantOperatingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class HACCPPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class DeviationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class DeviationStatus(str, Enum):
    OPEN = "OPEN"
    ACTION_LOGGED = "ACTION_LOGGED"
    VERIFIED = "VERIFIED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_PREMISE = "ON_PREMISE"
    DEPARTED = "DEPARTED"
    NO_SHOW = "NO_SHOW"


class ProductionDayStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class DayPosture(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CLEARED = "CLEARED"
    HARVESTED = "HARVESTED"
    CHILLED = "CHILLED"
    FABRICATING = "FABRICATING"
    FABRICATED = "FABRICATED"
    HELD = "HELD"
    RELEASED = "RELEASED"
    CONDEMNED = "CONDEMNED"


class YieldGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class SampleResult(str, Enum):
    PENDING = "PENDING"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class LabelStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class FinishedLotStatus(str, Enum):
    PRODUCED = "PRODUCED"
    SHIPPED = "SHIPPED"
    QUARANTINED = "QUARANTINED"
    SPOILED = "SPOILED"


class AuditOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class NoncomplianceCategory(str, Enum):
    HUMANE_HANDLING = "HUMANE_HANDLING"
    TRACEABILITY = "TRACEABILITY"
    PATHOGEN_CONTROL = "PATHOGEN_CONTROL"
    SANITATION = "SANITATION"


class NoncomplianceSeverity(str, Enum):
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class NoncomplianceStatus(str, Enum):
    OPEN = "OPEN"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


class RecallStatus(str, Enum):
    INITIATED = "INITIATED"
    PASSED = "PASSED"
    FAILED = "FAILED"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version.
# Append-only event records (observation, cut record, humane audit) carry
# only id + created_at.


class Plant(TypedDict, total=False):
    id: str
    establishment_number: str
    name: str
    district_code: str
    cooler_capacity_lbs: float
    cooler_occupied_lbs: float
    provisional_compliance_score: int
    official_compliance_score: int
    operating_status: str
    created_at: str
    updated_at: str
    version: int


class HACCPPlan(TypedDict, total=False):
    id: str
    plant_id: str
    process_type: str
    status: str
    revision_number: int
    rejection_reason: Optional[str]
    approved_by: Optional[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CriticalControlPoint(TypedDict, total=False):
    id: str
    haccp_plan_id: str
    ccp_code: str
    hazard_category: str
    description: str
    critical_limit_min_f: Optional[float]
    critical_limit_max_f: Optional[float]
    monitoring_frequency_minutes: int
    deviation_severity: str
    created_at: str
    updated_at: str
    version: int


class CCPObservation(TypedDict, total=False):
    id: str
    ccp_id: str
    production_day_id: str
    monitor_user_id: str
    observed_value_f: float
    within_limit: bool
    deviation_id: Optional[str]
    created_at: str


class Deviation(TypedDict, total=False):
    id: str
    ccp_id: str
    production_day_id: str
    observation_id: str
    severity: str
    corrective_action_note: Optional[str]
    action_logged_by: Optional[str]
    verified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectorShift(TypedDict, total=False):
    id: str
    plant_id: str
    inspector_user_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionDay(TypedDict, total=False):
    id: str
    plant_id: str
    production_date: str
    process_type: str
    status: str
    posture: str
    total_cut_weight_lbs: float
    total_cold_weight_lbs: float
    day_yield_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CarcassLot(TypedDict, total=False):
    id: str
    production_day_id: str
    species: str
    supplier_name: str
    head_count: int
    live_weight_lbs: float
    hot_carcass_weight_lbs: Optional[float]
    cold_carcass_weight_lbs: Optional[float]
    drip_loss_pct: Optional[float]
    total_cut_weight_lbs: float
    trim_waste_lbs: Optional[float]
    fabrication_yield_pct: Optional[float]
    packer_yield_pct: Optional[float]
    yield_grade: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CutRecord(TypedDict, total=False):
    id: str
    lot_id: str
    primal_type: str
    weight_lbs: float
    pct_of_cold_weight: float
    created_at: str


class PathogenSample(TypedDict, total=False):
    id: str
    lot_id: str
    organism: str
    sample_type: str
    collected_by: str
    result: str
    is_confirmation: bool
    reported_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabelApproval(TypedDict, total=False):
    id: str
    plant_id: str
    product_name: str
    claims: List[str]
    substantiation_doc_refs: List[str]
    formulation_version: int
    approved_formulation_version: Optional[int]
    status: str
    rejection_reason: Optional[str]
    approved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TemperatureLogEntry(TypedDict, total=False):
    recorded_at: str
    temp_f: float


class FinishedLot(TypedDict, total=False):
    id: str
    production_day_id: str
    source_lot_id: str
    label_approval_id: str
    units_produced: int
    unit_weight_lbs: float
    total_weight_lbs: float
    production_date: str
    shelf_life_days: int
    base_use_by_at: str
    penalty_hours: float
    use_by_at: str
    temperature_logs: List[TemperatureLogEntry]
    status: str
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HumaneHandlingAudit(TypedDict, total=False):
    id: str
    plant_id: str
    production_day_id: str
    auditor_user_id: str
    stunning_efficacy_pct: float
    slips_falls_pct: float
    vocalization_pct: float
    outcome: str
    noncompliance_record_id: Optional[str]
    created_at: str


class NoncomplianceRecord(TypedDict, total=False):
    id: str
    plant_id: str
    production_day_id: Optional[str]
    category: str
    regulation_cite: str
    description: str
    severity: str
    created_by: str
    status: str
    appeal_note: Optional[str]
    resolved_by: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecallExercise(TypedDict, total=False):
    id: str
    plant_id: str
    target_finished_lot_id: str
    scope: str
    initiated_at: str
    deadline_at: str
    basis_weight_lbs: float
    recovery_pct: Optional[float]
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
