"""
Domain types: status enums and one TypedDict per resource.

PRD 2.4 splits the resources in two. Most carry the full audit set
(`id`, `created_at`, `updated_at`, `version`). Three are write-once and carry
only `id` and `created_at`, with both `updated_at` and `version` absent from
their representations entirely: a material specification, a critical
characteristic and an inspection record. The TypedDicts below mirror that split
exactly.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

Json = Dict[str, Any]
Headers = Dict[str, str]


class UserRole(str, Enum):
    DESIGN_ENGINEER = "DesignEngineer"
    ENGINEERING_MANAGER = "EngineeringManager"
    PROCESS_TECHNICIAN = "ProcessTechnician"
    QUALITY_INSPECTOR = "QualityInspector"
    PROGRAM_MANAGER = "ProgramManager"
    CUSTOMER_REPRESENTATIVE = "CustomerRepresentative"
    PLANT_ADMIN = "PlantAdmin"


class DeliveryPosture(str, Enum):
    BLOCKED = "BLOCKED"
    AT_RISK = "AT_RISK"
    ON_TRACK = "ON_TRACK"


class ReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    ENG_REVIEW = "ENG_REVIEW"
    PROTOTYPE_RELEASED = "PROTOTYPE_RELEASED"
    PRODUCTION_RELEASED = "PRODUCTION_RELEASED"
    REJECTED = "REJECTED"
    OBSOLETE = "OBSOLETE"


class AmortizationStatus(str, Enum):
    PENDING = "PENDING"
    AMORTIZING = "AMORTIZING"
    FULLY_AMORTIZED = "FULLY_AMORTIZED"
    WRITTEN_OFF = "WRITTEN_OFF"


class CertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class MachineState(str, Enum):
    IDLE = "IDLE"
    SETUP = "SETUP"
    PRODUCTION = "PRODUCTION"


class SetupStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"
    ABORTED = "ABORTED"


class ProcessStatus(str, Enum):
    FAI_PENDING = "FAI_PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class QualityStatus(str, Enum):
    OPEN = "OPEN"
    SPC_HOLD = "SPC_HOLD"
    DISPOSITIONED_ACCEPT = "DISPOSITIONED_ACCEPT"
    SCRAPPED = "SCRAPPED"


class FaiDisposition(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class HeatTreatState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROCESS = "IN_PROCESS"
    COMPLETE = "COMPLETE"


class RecordKind(str, Enum):
    FAI = "FAI"
    SPC = "SPC"


class ControlState(str, Enum):
    IN_CONTROL = "IN_CONTROL"
    OUT_OF_CONTROL = "OUT_OF_CONTROL"


class BatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INTERIM_APPROVED = "INTERIM_APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED_FINAL = "REJECTED_FINAL"


class LotStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    QUARANTINED = "QUARANTINED"
    RETURNED = "RETURNED"


# ── Resources carrying the full audit set (PRD 2.4) ──────────────────────────


class CustomerProgram(TypedDict):
    id: str
    program_code: str
    customer_name: str
    application_class: str
    ppap_level: int
    committed_pieces: int
    minimum_order_quantity: int
    required_salt_spray_hours: int
    biocompatibility_required: bool
    min_fatigue_margin: float
    required_ppk: float
    amortization_method: str
    open_commitment_pieces: int
    allocated_pieces: int
    shipped_pieces: int
    quarantined_lot_count: int
    delivery_posture: str
    quoted_qty: Optional[int]
    quoted_pre_discount_subtotal_cents: Optional[int]
    quoted_volume_discount_pct: Optional[float]
    quoted_tooling_amort_per_piece_cents: Optional[int]
    quoted_unit_price_cents: Optional[int]
    quoted_total_cents: Optional[int]
    quote_frozen: bool
    created_at: str
    updated_at: str
    version: int


class SpringDesign(TypedDict):
    id: str
    program_id: str
    material_spec_id: str
    part_number: str
    form_type: str
    end_type: str
    wire_diameter_mm: float
    outer_diameter_mm: float
    free_length_mm: float
    active_coils: float
    max_working_load_n: float
    min_working_load_n: float
    cycle_seconds_per_piece: float
    shot_peening_required: bool
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    current_revision_no: int
    superseded_revision_no: Optional[int]
    spring_rate_n_per_mm: float
    shear_stress_max_mpa: float
    shear_stress_min_mpa: float
    stress_amplitude_mpa: float
    mean_stress_mpa: float
    fatigue_criterion: str
    fatigue_margin_ratio: float
    predicted_fatigue_life_cycles: int
    wire_mass_per_piece_kg: float
    tangle_risk_index: float
    tangle_risk_class: str
    release_status: str
    created_at: str
    updated_at: str
    version: int


class ToolingAsset(TypedDict):
    id: str
    design_id: str
    tool_code: str
    original_cost_cents: int
    amortization_status: str
    amortization_basis_pieces: Optional[int]
    amort_per_piece_cents: Optional[int]
    recovered_cents: int
    unamortized_cents: int
    created_at: str
    updated_at: str
    version: int


class WireLot(TypedDict):
    id: str
    material_spec_id: str
    heat_number: str
    received_kg: float
    tensile_test_mpa: Optional[float]
    certified_by_user_id: Optional[str]
    certification_status: str
    on_hand_kg: float
    reserved_kg: float
    consumed_kg: float
    created_at: str
    updated_at: str
    version: int


class CoilingMachine(TypedDict):
    id: str
    machine_code: str
    max_wire_diameter_mm: float
    changeover_buffer_minutes: int
    machine_state: str
    active_setup_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MachineSetup(TypedDict):
    id: str
    machine_id: str
    design_id: str
    tooling_asset_id: str
    window_start: str
    window_end: str
    set_by_user_id: str
    setup_status: str
    superseded_by_setup_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    setup_id: str
    wire_lot_id: str
    design_id: str
    planned_pieces: int
    produced_pieces: int
    scrapped_pieces: int
    wire_reserved_kg: float
    wire_consumed_kg: float
    process_status: str
    quality_status: str
    fai_disposition: str
    min_cpk_observed: Optional[float]
    min_ppk_observed: Optional[float]
    heat_treat_state: str
    peening_verified: bool
    created_at: str
    updated_at: str
    version: int


class StressReliefOven(TypedDict):
    id: str
    oven_code: str
    capacity_kg: float
    max_temp_c: float
    scheduled_load_kg: float
    created_at: str
    updated_at: str
    version: int


class HeatTreatBatch(TypedDict):
    id: str
    oven_id: str
    run_id: str
    window_start: str
    window_end: str
    load_kg: float
    target_temp_c: float
    peening_requested: bool
    peening_performed: Optional[bool]
    batch_status: str
    created_at: str
    updated_at: str
    version: int


class QualificationSubmission(TypedDict):
    id: str
    program_id: str
    design_id: str
    ppap_level: int
    round_no: int
    submission_status: str
    interim_piece_cap: Optional[int]
    submitted_by_user_id: str
    reviewed_by_program_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShipmentLot(TypedDict):
    id: str
    run_id: str
    program_id: str
    piece_count: int
    packaging_method: Optional[str]
    lot_status: str
    unit_price_cents: int
    tooling_amort_per_piece_cents: int
    extended_price_cents: int
    tooling_recovery_cents: int
    shipped_at: Optional[str]
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ── Write-once resources: id + created_at only (PRD 2.4) ─────────────────────


class MaterialSpec(TypedDict):
    id: str
    spec_code: str
    wire_material: str
    tensile_grade_mpa: float
    shear_modulus_gpa: float
    elastic_modulus_gpa: float
    density_kg_per_m3: float
    coating: str
    salt_spray_hours: int
    biocompatible: bool
    cost_per_kg_cents: int
    created_at: str


class CriticalCharacteristic(TypedDict):
    id: str
    design_id: str
    char_code: str
    nominal_value: float
    lsl: float
    usl: float
    is_safety_critical: bool
    cpk_floor: float
    created_at: str


class InspectionRecord(TypedDict):
    id: str
    run_id: str
    characteristic_id: str
    record_kind: str
    measurements: List[float]
    subgroup_size: int
    mean_value: float
    sigma_value: float
    cpk_value: float
    ppk_value: Optional[float]
    control_state: str
    inspected_by_user_id: str
    created_at: str


WRITE_ONCE_RESOURCES = ("MaterialSpec", "CriticalCharacteristic", "InspectionRecord")
