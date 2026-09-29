"""Typed shapes for request payloads and response resources.

These describe the wire contract the tests assert against. `total=False` is used
throughout because optional inputs may be omitted and because the tests read
only the fields a given claim is about.
"""

from typing import Any, Dict, List, Optional, TypedDict


# --- Envelope --------------------------------------------------------------
class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    timestamp: str
    response_type: str
    total_count: int
    limit: int
    offset: int
    has_more: bool


class ApiEnvelope(TypedDict, total=False):
    meta: ResponseMeta
    data: Any


class ErrorPayload(TypedDict, total=False):
    error_id: str
    message: str


# --- Plant -----------------------------------------------------------------
class PlantCreate(TypedDict, total=False):
    name: str
    site_code: str
    licensed_chemistries: List[str]
    permit_status: str
    monthly_lead_emission_permit_g: float
    peak_tariff_cents_per_kwh: float
    offpeak_tariff_cents_per_kwh: float
    lead_initial_inventory_kg: float


class Plant(TypedDict, total=False):
    id: str
    name: str
    site_code: str
    licensed_chemistries: List[str]
    permit_status: str
    monthly_lead_emission_permit_g: float
    peak_tariff_cents_per_kwh: float
    offpeak_tariff_cents_per_kwh: float
    lead_initial_inventory_kg: float
    lead_inventory_kg: float
    lead_in_field_kg: float
    lead_recycled_kg: float
    lead_mass_variance_kg: float
    core_lead_variance_kg: float
    core_deposit_liability_cents: int
    core_credit_issued_cents: int
    emission_reserved_g: float
    emission_consumed_g: float
    emission_utilization_ratio: float
    formation_energy_charge_cents: int
    open_medical_removal_count: int
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


# --- Worker and exposure ---------------------------------------------------
class WorkerCreate(TypedDict, total=False):
    plant_id: str
    full_name: str
    job_class: str
    hire_date: str


class Worker(TypedDict, total=False):
    id: str
    plant_id: str
    full_name: str
    job_class: str
    hire_date: str
    removal_status: str
    removal_count: int
    exposure_index: Optional[float]
    exposure_index_variant: Optional[str]
    last_sample_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExposureSampleCreate(TypedDict, total=False):
    sample_type: str
    sampled_at: str
    air_lead_ug_per_m3: float
    sample_duration_minutes: int
    blood_lead_ug_per_dl: float


class ExposureSample(TypedDict, total=False):
    # This log carries only the identifier and the creation timestamp.
    id: str
    worker_id: str
    sample_type: str
    sampled_at: str
    air_lead_ug_per_m3: Optional[float]
    sample_duration_minutes: Optional[int]
    blood_lead_ug_per_dl: Optional[float]
    resulting_worker_index: float
    resulting_variant: str
    triggered_removal: bool
    created_at: str


class ExposureIndexRead(TypedDict, total=False):
    worker_id: str
    air_twa_index: Optional[float]
    blood_peak_index: Optional[float]
    governing_index: Optional[float]
    governing_variant: Optional[str]
    removal_required: bool


# --- Cell design -----------------------------------------------------------
class CellDesignCreate(TypedDict, total=False):
    code: str
    chemistry: str
    plate_type: str
    cells_per_battery: int
    cell_nominal_voltage_v: float
    nominal_capacity_ah: float
    rated_cycles: int
    warranty_months: int
    pack_weight_kg: float
    lead_content_kg: float
    formation_charge_factor: float
    retest_tightening_enabled: bool
    list_price_cents: int
    supersedes_design_id: str


class CellDesign(TypedDict, total=False):
    id: str
    code: str
    chemistry: str
    plate_type: str
    cells_per_battery: int
    cell_nominal_voltage_v: float
    nominal_pack_voltage_v: float
    nominal_capacity_ah: float
    rated_cycles: int
    warranty_months: int
    pack_weight_kg: float
    lead_content_kg: float
    formation_charge_factor: float
    retest_tightening_enabled: bool
    list_price_cents: int
    supersedes_design_id: Optional[str]
    approval_state: str
    revision: int
    approved_revision: Optional[int]
    submitted_by_worker_id: Optional[str]
    approved_by_worker_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Resources -------------------------------------------------------------
class FormationBayCreate(TypedDict, total=False):
    plant_id: str
    bay_code: str
    rated_power_kw: float
    cooldown_minutes: int


class FormationBay(TypedDict, total=False):
    id: str
    plant_id: str
    bay_code: str
    rated_power_kw: float
    cooldown_minutes: int
    bay_status: str
    created_at: str
    updated_at: str
    version: int


class TestChamberCreate(TypedDict, total=False):
    plant_id: str
    chamber_code: str
    power_cap_kw: float


class TestChamber(TypedDict, total=False):
    id: str
    plant_id: str
    chamber_code: str
    power_cap_kw: float
    chamber_status: str
    created_at: str
    updated_at: str
    version: int


# --- Production lot --------------------------------------------------------
class ProductionLotCreate(TypedDict, total=False):
    plant_id: str
    cell_design_id: str
    lot_code: str
    quantity: int


class ProductionLot(TypedDict, total=False):
    id: str
    plant_id: str
    cell_design_id: str
    design_revision_pinned: int
    lot_code: str
    quantity: int
    chemistry: str
    process_state: str
    env_hold_status: str
    hold_reason: Optional[str]
    sample_size: Optional[int]
    acceptance_number: Optional[int]
    sampling_plan_revision: int
    completed_test_count: int
    failed_test_count: int
    passed_cycle_life_count: int
    failed_formation_count: int
    retest_count: int
    lot_capacity_yield_pct: Optional[float]
    last_test_recorded_by_worker_id: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotQualitySummary(TypedDict, total=False):
    lot_id: str
    process_state: str
    sample_size: Optional[int]
    acceptance_number: Optional[int]
    completed_test_count: int
    failed_test_count: int
    passed_cycle_life_count: int
    lot_capacity_yield_pct: Optional[float]
    release_blocked_by: str


# --- Assemblies ------------------------------------------------------------
class BatteryAssemblyCreate(TypedDict, total=False):
    lot_id: str
    serial_number: str
    module_count: int
    case_type: str
    torque_spec_nm: float
    ir_min_megaohm: float


class BatteryAssembly(TypedDict, total=False):
    id: str
    lot_id: str
    serial_number: str
    module_count: int
    case_type: str
    torque_spec_nm: float
    ir_min_megaohm: float
    torque_status: str
    insulation_status: str
    measured_torque_nm: Optional[float]
    measured_ir_megaohm: Optional[float]
    certification_status: str
    rework_count: int
    created_at: str
    updated_at: str
    version: int


class VerificationCreate(TypedDict, total=False):
    verification_type: str
    measured_torque_nm: float
    connection_count: int
    measured_ir_megaohm: float
    test_voltage_v: int


# --- Formation runs --------------------------------------------------------
class FormationRunCreate(TypedDict, total=False):
    lot_id: str
    bay_id: str
    scheduled_start_at: str
    scheduled_end_at: str


class FormationRun(TypedDict, total=False):
    id: str
    lot_id: str
    bay_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    actual_start_at: Optional[str]
    actual_end_at: Optional[str]
    run_state: str
    charge_factor_used: float
    estimated_energy_kwh: float
    metered_energy_kwh: Optional[float]
    scheduled_peak_hours: float
    scheduled_offpeak_hours: float
    actual_peak_hours: Optional[float]
    actual_offpeak_hours: Optional[float]
    provisional_charge_cents: int
    final_charge_cents: int
    reserved_emission_g: float
    consumed_emission_g: Optional[float]
    formation_capacity_pct: Optional[float]
    capacity_validation_result: Optional[str]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FormationRunComplete(TypedDict, total=False):
    metered_energy_kwh: float
    formation_capacity_pct: float
    actual_end_at: str


# --- Capacity tests --------------------------------------------------------
class CapacityTestCreate(TypedDict, total=False):
    assembly_id: str
    chamber_id: str
    test_type: str
    scheduled_start_at: str
    scheduled_end_at: str
    draw_kw: float


class CapacityTest(TypedDict, total=False):
    id: str
    assembly_id: str
    chamber_id: str
    test_type: str
    scheduled_start_at: str
    scheduled_end_at: str
    draw_kw: float
    test_state: str
    measured_capacity_ah: Optional[float]
    cycles_completed: Optional[int]
    result: Optional[str]
    yield_pct: Optional[float]
    recorded_by_worker_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecordResult(TypedDict, total=False):
    measured_capacity_ah: float
    cycles_completed: int


# --- Chargers and fleet sizing ---------------------------------------------
class ChargerCreate(TypedDict, total=False):
    model_code: str
    chemistry_compatibility: str
    output_voltage_v: float
    output_amps: float
    charge_profile: str
    price_cents: int


class Charger(TypedDict, total=False):
    id: str
    model_code: str
    chemistry_compatibility: str
    output_voltage_v: float
    output_amps: float
    charge_profile: str
    price_cents: int
    charger_status: str
    created_at: str
    updated_at: str
    version: int


class FleetSizingRequestCreate(TypedDict, total=False):
    plant_id: str
    application_name: str
    forklift_class: str
    forklift_count: int
    shift_energy_kwh_per_shift: float
    shifts_per_day: int
    ambient_temp_c: float
    required_voltage_v: float
    compartment_max_kg: float
    charge_window_hours: float
    chemistry_preference: str


class FleetSizingRequest(TypedDict, total=False):
    id: str
    plant_id: str
    application_name: str
    forklift_class: str
    forklift_count: int
    shift_energy_kwh_per_shift: float
    shifts_per_day: int
    ambient_temp_c: float
    required_voltage_v: float
    compartment_max_kg: float
    charge_window_hours: float
    chemistry_preference: str
    daily_energy_kwh: float
    temp_derate_factor: float
    reserve_factor: float
    required_ah: int
    evaluated_design_count: int
    selected_cell_design_id: Optional[str]
    selected_charger_id: Optional[str]
    selected_charge_hours: Optional[float]
    recommended_battery_count: Optional[int]
    recommended_charger_count: Optional[int]
    fleet_capital_cents: Optional[int]
    request_state: str
    created_at: str
    updated_at: str
    version: int


# --- Battery units, service and warranty -----------------------------------
class BatteryUnitCreate(TypedDict, total=False):
    lot_id: str
    serial_number: str
    customer_name: str
    list_price_cents: int
    sizing_request_id: str
    shipped_at: str


class BatteryUnit(TypedDict, total=False):
    id: str
    lot_id: str
    serial_number: str
    customer_name: str
    list_price_cents: int
    sizing_request_id: Optional[str]
    shipped_at: str
    declared_lead_kg: float
    cycle_count: int
    watering_events_expected: int
    watering_events_ok: int
    watering_compliance_ratio: float
    months_in_service: int
    usage_fraction: float
    warranty_status: str
    claim_count: int
    last_claim_at: Optional[str]
    warranty_decision: Optional[str]
    warranty_credit_cents: Optional[int]
    core_status: str
    core_manifest_number: Optional[str]
    received_lead_kg: Optional[float]
    core_credit_issued_cents: int
    created_at: str
    updated_at: str
    version: int


class MaintenanceLogCreate(TypedDict, total=False):
    event_type: str
    performed_at: str
    electrolyte_level_ok: bool
    cycles_delta: int
    technician_note: str


class MaintenanceLog(TypedDict, total=False):
    # This log carries only the identifier and the creation timestamp.
    id: str
    battery_unit_id: str
    event_type: str
    performed_at: str
    electrolyte_level_ok: Optional[bool]
    cycles_delta: Optional[int]
    technician_note: Optional[str]
    resulting_cycle_count: int
    resulting_compliance_ratio: float
    created_at: str


class WarrantyClaimCreate(TypedDict, total=False):
    expected_battery_unit_version: int
    complaint_code: str
    reported_at: str


class WarrantyAdjudication(TypedDict, total=False):
    inspection_finding: str
    adjudication_note: str


class WarrantyEvaluation(TypedDict, total=False):
    usage_fraction: float
    watering_compliance_ratio: float
    months_in_service: int
    warranty_months: int
    would_decide: str
    would_credit_cents: int
    governing_gate: str


class CoreReturnCreate(TypedDict, total=False):
    core_manifest_number: str


class CoreTransition(TypedDict, total=False):
    action: str
    received_lead_kg: float
    transition_note: str


EmissionLedger = Dict[str, Any]
LeadMassBalance = Dict[str, Any]
FleetAnalysis = Dict[str, Any]
