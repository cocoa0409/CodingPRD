"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD section: User and Role-Based Access Control)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    IMPORT_COORDINATOR = "ImportCoordinator"
    RECEIVING_INSPECTOR = "ReceivingInspector"
    QUALITY_ASSURANCE_TECH = "QualityAssuranceTech"
    PROCESSING_SUPERVISOR = "ProcessingSupervisor"
    COMPLIANCE_MANAGER = "ComplianceManager"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class SupplierStatus(str, Enum):
    PENDING_EVALUATION = "PENDING_EVALUATION"
    APPROVED = "APPROVED"
    REEVALUATION_DUE = "REEVALUATION_DUE"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class EvaluationOutcome(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    REJECTED = "REJECTED"


class EntryStatus(str, Enum):
    DRAFT = "DRAFT"
    PRIOR_NOTICE_FILED = "PRIOR_NOTICE_FILED"
    ENTRY_FILED = "ENTRY_FILED"
    RELEASED = "RELEASED"
    DETAINED = "DETAINED"
    REFUSED = "REFUSED"


class TransportMode(str, Enum):
    VESSEL = "VESSEL"
    AIR = "AIR"
    ROAD = "ROAD"


class DispositionOutcome(str, Enum):
    RELEASED = "RELEASED"
    DETAINED = "DETAINED"
    REFUSED = "REFUSED"


class LotStatus(str, Enum):
    UNDER_INSPECTION = "UNDER_INSPECTION"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"


class ProductionMethod(str, Enum):
    WILD = "WILD"
    FARMED = "FARMED"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class FreezeProtocol(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    BLAST = "BLAST"
    COMBO = "COMBO"


class TestMethod(str, Enum):
    DNA_BARCODING = "DNA_BARCODING"
    SENSORY = "SENSORY"


class VerificationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    MISMATCH = "MISMATCH"
    RESOLVED_RELABELED = "RESOLVED_RELABELED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"


class Resolution(str, Enum):
    RELABEL_AS_VERIFIED = "RELABEL_AS_VERIFIED"
    REJECT_LOT = "REJECT_LOT"


class BatchStatus(str, Enum):
    IN_PROCESS = "IN_PROCESS"
    COMPLETED = "COMPLETED"
    RECONCILED = "RECONCILED"


class ProductForm(str, Enum):
    FILLET = "FILLET"
    LOIN = "LOIN"
    PORTION = "PORTION"


class TempSource(str, Enum):
    CONTINUOUS_MONITOR = "CONTINUOUS_MONITOR"
    MANUAL_PROBE = "MANUAL_PROBE"


class HazardType(str, Enum):
    HISTAMINE = "HISTAMINE"
    PARASITE = "PARASITE"


class Phase(str, Enum):
    SCREENING = "SCREENING"
    CONFIRMATORY = "CONFIRMATORY"


class Verdict(str, Enum):
    PASS = "PASS"
    DEVIATION = "DEVIATION"


class CaSourceType(str, Enum):
    SPECIES_MISMATCH = "SPECIES_MISMATCH"
    HISTAMINE_DEVIATION = "HISTAMINE_DEVIATION"
    TEMPERATURE_ABUSE = "TEMPERATURE_ABUSE"
    YIELD_VARIANCE = "YIELD_VARIANCE"
    MANUAL = "MANUAL"


class CaStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class LabelStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class FinishedLotStatus(str, Enum):
    UNLABELED = "UNLABELED"
    LABELED = "LABELED"
    RELEASED = "RELEASED"
    RECALLED = "RECALLED"


class RecallStatus(str, Enum):
    INITIATED = "INITIATED"
    NOTIFIED = "NOTIFIED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields entities carry id + created_at + updated_at + version.
# Append-only entities (TemperatureLog, HaccpMonitoringRecord) carry ONLY
# id + created_at — no updated_at, no version.
# ---------------------------------------------------------------------------
class ForeignSupplier(TypedDict, total=False):
    id: str
    legal_name: str
    country_code: str
    facility_registration_number: str
    handles_histamine_susceptible_species: bool
    fsvp_status: str
    risk_score: Optional[float]
    risk_tier: Optional[str]
    open_corrective_action_count: int
    total_species_mismatches: int
    total_haccp_deviations: int
    last_evaluation_period_end: Optional[str]
    next_evaluation_due: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplierEvaluation(TypedDict, total=False):
    id: str
    supplier_id: str
    period_start: str
    period_end: str
    hazard_analysis_score: float
    record_review_score: float
    performance_score: float
    overall_score: float
    outcome: str
    evaluated_by: str
    created_at: str
    updated_at: str
    version: int


class ImportEntry(TypedDict, total=False):
    id: str
    supplier_id: str
    entry_number: str
    species_declared: str
    transport_mode: str
    scheduled_arrival: str
    port_code: str
    goods_value_cents: int
    freight_cost_cents: int
    duty_rate_pct: float
    total_weight_kg: float
    prior_notice_filed_at: Optional[str]
    prior_notice_confirmation: Optional[str]
    entry_filed_at: Optional[str]
    duty_cents: Optional[int]
    allocatable_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReceiptLot(TypedDict, total=False):
    id: str
    import_entry_id: str
    vessel_name: str
    harvest_date: str
    catch_area_code: str
    harvest_country_code: str
    production_method: str
    species_declared: str
    species_verified: Optional[str]
    grade: str
    quantity_received_kg: float
    ice_deduction_pct: float
    quantity_accepted_kg: float
    consumed_kg: float
    remaining_kg: float
    receiving_temp_c: float
    freeze_protocol: str
    freeze_compliant: bool
    cumulative_abuse_minutes: int
    mislabel_flag: bool
    allocated_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpeciesVerification(TypedDict, total=False):
    id: str
    receipt_lot_id: str
    test_method: str
    sample_size: int
    verified_species: str
    is_match: bool
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcessingBatch(TypedDict, total=False):
    id: str
    target_species: str
    product_form: str
    status: str
    input_total_kg: float
    provisional_output_kg: float
    actual_output_kg: Optional[float]
    trim_waste_kg: Optional[float]
    other_waste_kg: Optional[float]
    yield_pct_provisional: Optional[float]
    yield_pct_final: Optional[float]
    yield_variance_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class BatchInputLot(TypedDict, total=False):
    id: str
    processing_batch_id: str
    receipt_lot_id: str
    quantity_kg: float
    provisional_yield_kg: float
    created_at: str
    updated_at: str
    version: int


class TemperatureLog(TypedDict, total=False):
    # Append-only: id + created_at only, NO updated_at / version.
    id: str
    receipt_lot_id: Optional[str]
    processing_batch_id: Optional[str]
    interval_start: str
    interval_end: str
    core_temp_c: float
    avg_temp_c: float
    source: str
    created_at: str


class HaccpMonitoringRecord(TypedDict, total=False):
    # Append-only: id + created_at only, NO updated_at / version.
    id: str
    hazard_type: str
    receipt_lot_id: Optional[str]
    processing_batch_id: Optional[str]
    phase: str
    measured_value: Optional[float]
    subsample_values: Optional[List[float]]
    measured_at: str
    verdict: str
    corrective_action_id: Optional[str]
    created_at: str


class CorrectiveAction(TypedDict, total=False):
    id: str
    source_type: str
    supplier_id: Optional[str]
    receipt_lot_id: Optional[str]
    processing_batch_id: Optional[str]
    monitoring_record_id: Optional[str]
    opened_by: str
    status: str
    resolution_note: Optional[str]
    closed_by: Optional[str]
    recall_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductLabel(TypedDict, total=False):
    id: str
    market_name: str
    scientific_name: str
    species: str
    production_method: str
    country_of_origin: str
    keep_frozen_statement: bool
    allergen_statement: str
    supersedes_label_id: Optional[str]
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinishedProductLot(TypedDict, total=False):
    id: str
    processing_batch_id: str
    net_weight_kg: float
    product_label_id: Optional[str]
    label_version_pinned: Optional[int]
    label_stale: bool
    allergen_statement: Optional[str]
    country_of_origin: Optional[str]
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict, total=False):
    id: str
    corrective_action_id: str
    reason: str
    scope_lot_ids: List[str]
    status: str
    notified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
