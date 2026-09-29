"""Domain types for the hydrogen production and fuelling station API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Two entities — PurityTest and InventoryLedgerEntry — carry
only ``id`` and ``created_at``; the PRD states that for both of these
``updated_at`` and ``version`` are absent from the resource entirely, so their
TypedDicts deliberately omit those two keys.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    STATION_OPERATOR = "StationOperator"
    PRODUCTION_ENGINEER = "ProductionEngineer"
    QUALITY_ANALYST = "QualityAnalyst"
    SAFETY_OFFICER = "SafetyOfficer"
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    LOGISTICS_DISPATCHER = "LogisticsDispatcher"
    PROGRAM_AUDITOR = "ProgramAuditor"


# ─── Enumerations ─────────────────────────────────────────────────────────


class UptimeMethod(str, Enum):
    NOZZLE_WEIGHTED = "NOZZLE_WEIGHTED"
    STATION_LEVEL = "STATION_LEVEL"


class SafetyPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class VentilationStatus(str, Enum):
    NORMAL = "NORMAL"
    FAULT = "FAULT"


class LeakDetectionStatus(str, Enum):
    NORMAL = "NORMAL"
    ALARM = "ALARM"


class CompressorStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class MeteringAccuracyFlag(str, Enum):
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    OUT_OF_TOLERANCE = "OUT_OF_TOLERANCE"


class PressureClass(str, Enum):
    H35 = "H35"
    H70 = "H70"


class BankTier(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class InspectionStatus(str, Enum):
    CURRENT = "CURRENT"
    DUE = "DUE"
    OVERDUE = "OVERDUE"
    CONDEMNED = "CONDEMNED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    CONDEMN = "CONDEMN"


class ProductionPathway(str, Enum):
    PEM_ELECTROLYSIS = "PEM_ELECTROLYSIS"
    ALKALINE_ELECTROLYSIS = "ALKALINE_ELECTROLYSIS"
    SMR = "SMR"
    SMR_CCS = "SMR_CCS"


class CiVariant(str, Enum):
    ANNUAL_AVERAGE = "ANNUAL_AVERAGE"
    HOURLY_MATCHED = "HOURLY_MATCHED"


class QaStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class CiStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"


class ProductionLotStatus(str, Enum):
    PRODUCED = "PRODUCED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"


class PurityVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INDETERMINATE = "INDETERMINATE"


class LedgerReason(str, Enum):
    OPENING_BALANCE = "OPENING_BALANCE"
    DELIVERY_RECEIPT = "DELIVERY_RECEIPT"
    HEEL_RETURNED = "HEEL_RETURNED"
    BOILOFF_LOSS = "BOILOFF_LOSS"
    DISPENSE_DRAW = "DISPENSE_DRAW"
    METER_CORRECTION = "METER_CORRECTION"
    METER_VOID_REVERSAL = "METER_VOID_REVERSAL"
    INSPECTION_VENT = "INSPECTION_VENT"


class LedgerSourceRefType(str, Enum):
    PRESSURE_VESSEL = "PRESSURE_VESSEL"
    DELIVERY = "DELIVERY"
    DISPENSE_SESSION = "DISPENSE_SESSION"


class TransportMode(str, Enum):
    TUBE_TRAILER = "TUBE_TRAILER"
    LIQUID_TANKER = "LIQUID_TANKER"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"


class DeliveryRejectReason(str, Enum):
    PURITY_FAIL = "PURITY_FAIL"
    LOT_NOT_RELEASED = "LOT_NOT_RELEASED"
    DOCUMENTATION = "DOCUMENTATION"
    SEAL_BROKEN = "SEAL_BROKEN"


class VehicleClass(str, Enum):
    LIGHT_DUTY = "LIGHT_DUTY"
    TRANSIT_BUS = "TRANSIT_BUS"
    HEAVY_TRUCK = "HEAVY_TRUCK"
    FORKLIFT = "FORKLIFT"


class FillProtocol(str, Enum):
    SAE_J2601_TABLE = "SAE_J2601_TABLE"
    MC_FORMULA = "MC_FORMULA"


class FillStatus(str, Enum):
    PRECOOLING = "PRECOOLING"
    FUELING = "FUELING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class BillingStatus(str, Enum):
    PENDING = "PENDING"
    METERED = "METERED"
    VOIDED = "VOIDED"


class AbortReason(str, Enum):
    OPERATOR_ABORT = "OPERATOR_ABORT"
    STATION_FROZEN = "STATION_FROZEN"


class VoidReason(str, Enum):
    METER_FAULT = "METER_FAULT"
    BILLING_DISPUTE = "BILLING_DISPUTE"
    AUDIT_ADJUSTMENT = "AUDIT_ADJUSTMENT"


class SafetyEventKind(str, Enum):
    LEAK_DETECTED = "LEAK_DETECTED"
    VENTILATION_FAULT = "VENTILATION_FAULT"
    COMPRESSOR_FAULT = "COMPRESSOR_FAULT"
    OVERPRESSURE = "OVERPRESSURE"
    SETBACK_BREACH = "SETBACK_BREACH"


class SafetySeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DetectedBy(str, Enum):
    SENSOR = "SENSOR"
    OPERATOR_ROUND = "OPERATOR_ROUND"
    THIRD_PARTY = "THIRD_PARTY"


class SafetyEventStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLEARED = "CLEARED"


class CertType(str, Enum):
    EMERGENCY_RESPONSE = "EMERGENCY_RESPONSE"
    HAZMAT_AWARENESS = "HAZMAT_AWARENESS"
    CONFINED_SPACE = "CONFINED_SPACE"


class IncentiveProgram(str, Enum):
    LCFS = "LCFS"
    CFP_OREGON = "CFP_OREGON"
    CFS_CANADA = "CFS_CANADA"


class IncentiveClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CERTIFIED = "CERTIFIED"
    CREDITS_ISSUED = "CREDITS_ISSUED"
    DENIED = "DENIED"


class UptimeReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    AMENDED = "AMENDED"


# ─── Entity TypedDicts ────────────────────────────────────────────────────


class FundingAgreement(TypedDict):
    id: str
    agreement_code: str
    funder_name: str
    min_uptime_pct: float
    penalty_per_point_cents: int
    initial_holdback_cents: int
    holdback_balance_cents: int
    uptime_method: str
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    funding_agreement_id: str
    code: str
    name: str
    nozzle_count: int
    offload_bay_count: int
    storage_capacity_kg: float
    reserve_floor_kg: float
    max_pressure_class: str
    setback_compliant: bool
    ventilation_status: str
    leak_detection_status: str
    compressor_status: str
    safety_posture: str
    onsite_inventory_kg: float
    reserved_kg: float
    available_kg: float
    total_deliverable_kg: float
    high_bank_deliverable_kg: float
    inbound_planned_kg: float
    projected_available_kg: float
    supply_alert: bool
    metered_kg_mtd: float
    corrected_kg_mtd: float
    metering_error_pct_mtd: float
    metering_accuracy_flag: str
    credits_issued_total_mt: float
    created_at: str
    updated_at: str
    version: int


class PressureVessel(TypedDict):
    id: str
    station_id: str
    bank_tier: str
    water_volume_l: float
    mawp_bar: float
    min_residual_bar: float
    initial_pressure_bar: float
    current_pressure_bar: float
    stored_mass_kg: float
    last_inspection_date: Optional[str]
    next_inspection_due_date: str
    inspection_status: str
    inspection_count: int
    created_at: str
    updated_at: str
    version: int


class ProductionAsset(TypedDict):
    id: str
    asset_code: str
    pathway: str
    nameplate_kg_per_day: float
    ccs_capture_rate: float
    operator_org: str
    created_at: str
    updated_at: str
    version: int


class PowerSupplyContract(TypedDict):
    id: str
    production_asset_id: str
    contract_code: str
    grid_ci_gco2e_per_mwh: float
    annual_renewable_pct: float
    hourly_matched_renewable_pct: float
    hourly_matching_enabled: bool
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class ProductionLot(TypedDict):
    id: str
    production_asset_id: str
    predecessor_lot_id: Optional[str]
    lot_code: str
    mass_kg: float
    energy_consumed_kwh: float
    feedstock_consumed_mmbtu: float
    carryover_kg: float
    production_start_at: str
    production_end_at: str
    selected_power_contract_id: Optional[str]
    ci_provisional_gco2e_per_mj: float
    ci_certified_gco2e_per_mj: Optional[float]
    ci_variant_applied: Optional[str]
    qa_status: str
    ci_status: str
    status: str
    released_by_user_id: Optional[str]
    accepted_delivered_kg: float
    created_at: str
    updated_at: str
    version: int


class PurityTest(TypedDict):
    """Append-only quality record: carries only id and created_at."""

    id: str
    production_lot_id: str
    performed_by_user_id: str
    sampled_at: str
    total_hydrocarbons_ppm: float
    water_ppm: float
    oxygen_ppm: float
    nitrogen_ppm: float
    carbon_monoxide_ppm: float
    carbon_dioxide_ppm: float
    total_sulfur_ppm: float
    ammonia_ppm: Optional[float]
    helium_ppm: Optional[float]
    verdict: str
    failing_analytes: List[str]
    purity_margin_pct: float
    created_at: str


class InventoryLedgerEntry(TypedDict):
    """Append-only inventory movement: carries only id and created_at."""

    id: str
    station_id: str
    sequence_no: int
    reason: str
    delta_kg: float
    resulting_onsite_kg: float
    source_ref_type: Optional[str]
    source_ref_id: Optional[str]
    occurred_at: str
    created_at: str


class Delivery(TypedDict):
    id: str
    station_id: str
    production_lot_id: str
    receiving_vessel_id: str
    mode: str
    planned_kg: float
    window_start: str
    window_end: str
    trailer_water_volume_l: Optional[float]
    trailer_final_pressure_bar: Optional[float]
    departed_at: str
    arrived_at: Optional[str]
    accepted_at: Optional[str]
    transit_hours: Optional[float]
    boiloff_kg: Optional[float]
    heel_kg: Optional[float]
    net_receipt_kg: Optional[float]
    status: str
    reject_reason: Optional[str]
    reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class CascadeAllocation(TypedDict):
    bank_tier: str
    vessel_id: str
    kg: float
    pressure_after_bar: float


class DispenseSession(TypedDict):
    id: str
    station_id: str
    vehicle_class: str
    target_pressure_class: str
    fill_protocol: str
    planned_kg: float
    ambient_temp_c: float
    required_precool_c: float
    precool_temp_achieved_c: Optional[float]
    metered_kg: Optional[float]
    avg_dispense_pressure_bar: Optional[float]
    final_pressure_bar: Optional[float]
    density_correction_factor: Optional[float]
    corrected_kg: Optional[float]
    metering_error_pct: Optional[float]
    metering_within_tolerance: Optional[bool]
    direct_cascade_kg: Optional[float]
    compressor_makeup_kg: Optional[float]
    cascade_plan: List[CascadeAllocation]
    fill_status: str
    billing_status: str
    abort_reason: Optional[str]
    void_reason: Optional[str]
    started_at: str
    created_at: str
    updated_at: str
    version: int


class SafetyEvent(TypedDict):
    id: str
    station_id: str
    kind: str
    severity: str
    affected_nozzle_count: int
    detected_by: str
    opened_by_user_id: str
    cleared_by_user_id: Optional[str]
    opened_at: str
    acknowledged_at: Optional[str]
    cleared_at: Optional[str]
    status: str
    corrective_action: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResponderCertification(TypedDict):
    id: str
    station_id: str
    responder_ref: str
    cert_type: str
    valid_from: str
    expires_on: str
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class IncentiveClaim(TypedDict):
    id: str
    station_id: str
    program: str
    period_start: str
    period_end: str
    production_lot_ids: List[str]
    dispensed_kg: float
    energy_mj: float
    pathway_ci_gco2e_per_mj: float
    gross_credits_mt: float
    admin_fee_rate: float
    admin_fee_mt: float
    net_credits_mt: float
    revision_round: int
    submitted_by_user_id: str
    certified_by_user_id: Optional[str]
    revision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UptimeReport(TypedDict):
    id: str
    station_id: str
    funding_agreement_id: str
    amended_from_report_id: Optional[str]
    period_start: str
    period_end: str
    nozzle_count_snapshot: int
    downtime_nozzle_minutes: float
    full_outage_minutes: float
    uptime_pct_nozzle_weighted: float
    uptime_pct_station_level: float
    uptime_pct: float
    shortfall_points: float
    penalty_cents: int
    status: str
    amend_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClockState(TypedDict):
    current_utc: str
    vessels_recomputed: int
    stations_recomputed: int


JsonDict = Dict[str, Any]
