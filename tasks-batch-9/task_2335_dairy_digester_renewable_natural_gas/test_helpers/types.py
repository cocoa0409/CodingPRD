"""Domain types: entity TypedDicts, status enums and the role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROJECT_OPERATOR = "ProjectOperator"
    DAIRY_PARTNER = "DairyPartner"
    PIPELINE_SCHEDULER = "PipelineScheduler"
    CREDIT_VERIFIER = "CreditVerifier"
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    FINANCE_CONTROLLER = "FinanceController"


class DairyStatus(str, Enum):
    PROSPECT = "PROSPECT"
    CONTRACTED = "CONTRACTED"
    SUSPENDED = "SUSPENDED"


class ManureManagementBaseline(str, Enum):
    LAGOON = "LAGOON"
    SOLID_STORAGE = "SOLID_STORAGE"
    DAILY_SPREAD = "DAILY_SPREAD"


class ThermalRegime(str, Enum):
    MESOPHILIC = "MESOPHILIC"
    THERMOPHILIC = "THERMOPHILIC"


class OpsPosture(str, Enum):
    STABLE = "STABLE"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"
    UPSET = "UPSET"


class DistributionPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    LOCKED = "LOCKED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_DAIRY_SIGNATURE = "PENDING_DAIRY_SIGNATURE"
    COUNTERED = "COUNTERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RevenueShareBasis(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class DeliveryStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class OpsDayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class GasState(str, Enum):
    NOT_PRODUCED = "NOT_PRODUCED"
    RAW = "RAW"
    PIPELINE_SPEC = "PIPELINE_SPEC"
    OFFSPEC = "OFFSPEC"
    FLARED = "FLARED"
    INJECTED = "INJECTED"


class ThermalStatus(str, Enum):
    IN_BAND = "IN_BAND"
    EXCURSION = "EXCURSION"
    CRITICAL = "CRITICAL"


class StabilityStatus(str, Enum):
    STABLE = "STABLE"
    STRESSED = "STRESSED"
    INHIBITED = "INHIBITED"


class InterconnectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class NominationStatus(str, Enum):
    NOMINATED = "NOMINATED"
    CONFIRMED = "CONFIRMED"
    CURTAILED = "CURTAILED"
    DELIVERED = "DELIVERED"
    REJECTED_OFFSPEC = "REJECTED_OFFSPEC"


class CreditProgram(str, Enum):
    LCFS = "LCFS"
    RFS_D3 = "RFS_D3"


class PathwayStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class BatchStatus(str, Enum):
    DRAFT = "DRAFT"
    CLAIMED = "CLAIMED"
    VERIFIED = "VERIFIED"
    ISSUED = "ISSUED"
    REVERSED = "REVERSED"
    SUPERSEDED = "SUPERSEDED"


class ReversalReason(str, Enum):
    MATERIAL_FINDING = "MATERIAL_FINDING"
    REGULATOR_ORDER = "REGULATOR_ORDER"
    OPERATOR_WITHDRAWAL = "OPERATOR_WITHDRAWAL"


class AuditStatus(str, Enum):
    PLANNED = "PLANNED"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    REMEDIATION = "REMEDIATION"
    CLOSED = "CLOSED"


class FindingSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"


class PanBasis(str, Enum):
    LAB = "LAB"
    AGRONOMIC = "AGRONOMIC"


class ApplicationStatus(str, Enum):
    PLANNED = "PLANNED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"
    SUPERSEDED = "SUPERSEDED"


class PostureDimension(str, Enum):
    OPS = "OPS"
    DISTRIBUTION = "DISTRIBUTION"


# ---------------------------------------------------------------------------
# Entity shapes. Every one of the twelve resource types carries id, created_at,
# updated_at and version (PRD §2.4).
# ---------------------------------------------------------------------------


class Dairy(TypedDict):
    id: str
    name: str
    county: str
    herd_size: int
    manure_management_baseline: str
    haul_distance_km: float
    annual_nitrogen_budget_kg: float
    status: str
    active_agreement_count: int
    contracted_agreement_count: int
    pan_applied_ytd_kg: float
    created_at: str
    updated_at: str
    version: int


class DigesterFacility(TypedDict):
    id: str
    name: str
    digester_volume_m3: float
    hydraulic_capacity_tonnes_per_day: float
    thermal_regime: str
    target_temperature_c: float
    design_max_olr: float
    ops_posture: str
    distribution_posture: str
    posture_override_active: bool
    reserve_target_cents: int
    reserve_balance_cents: int
    annual_debt_service_cents: int
    dscr_minimum: float
    dscr_current: float
    total_manure_received_tonnes: float
    unseparated_manure_tonnes: float
    digestate_solids_produced_tonnes: float
    digestate_liquid_produced_tonnes: float
    digestate_solids_applied_tonnes: float
    digestate_liquid_applied_tonnes: float
    digestate_solids_on_hand_tonnes: float
    digestate_liquid_on_hand_tonnes: float
    mass_control_residual_tonnes: float
    gross_revenue_to_date_cents: int
    dairy_share_paid_cents: int
    retained_to_date_cents: int
    created_at: str
    updated_at: str
    version: int


class FeedstockAgreement(TypedDict):
    id: str
    dairy_id: str
    facility_id: str
    committed_tonnes_per_day: float
    minimum_total_solids_pct: float
    term_start_date: str
    term_end_date: str
    revenue_share_pct: float
    revenue_share_basis: str
    curtailable: bool
    status: str
    negotiation_round: int
    countered_tonnes_per_day: Optional[float]
    countered_revenue_share_pct: Optional[float]
    suspension_reason: Optional[str]
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeedstockDelivery(TypedDict):
    id: str
    agreement_id: str
    ops_day_id: str
    gross_tonnes: float
    tare_tonnes: float
    total_solids_pct: float
    volatile_solids_pct_of_ts: float
    net_tonnes: float
    vs_tonnes: float
    haul_tonne_km: float
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OperationsDay(TypedDict):
    id: str
    facility_id: str
    ops_date: str
    status: str
    gas_state: str
    avg_digester_temp_c: Optional[float]
    temp_excursion_minutes: Optional[int]
    vfa_mg_per_l: Optional[float]
    alkalinity_mg_per_l: Optional[float]
    organic_loading_rate: float
    vfa_alkalinity_ratio: Optional[float]
    thermal_status: Optional[str]
    stress_points: Optional[int]
    stability_status: Optional[str]
    raw_biogas_scf: Optional[float]
    raw_ch4_pct: Optional[float]
    raw_co2_pct: Optional[float]
    raw_h2s_ppm: Optional[float]
    raw_moisture_lb_per_mmscf: Optional[float]
    raw_gas_mmbtu: Optional[float]
    raw_hhv_btu_per_scf: Optional[float]
    conditioning_attempts: int
    treated_ch4_pct: Optional[float]
    treated_co2_pct: Optional[float]
    treated_h2s_ppm: Optional[float]
    treated_moisture_lb_per_mmscf: Optional[float]
    pipeline_hhv_btu_per_scf: Optional[float]
    pipeline_gas_scf: Optional[float]
    pipeline_gas_mmbtu: Optional[float]
    offspec_reason: Optional[str]
    separation_recorded: bool
    solids_capture_pct: Optional[float]
    bedding_recovery_pct: Optional[float]
    digestate_solids_tonnes: Optional[float]
    digestate_liquid_tonnes: Optional[float]
    bedding_recovered_tonnes: Optional[float]
    lab_total_nitrogen_mg_per_l: Optional[float]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class InterconnectAgreement(TypedDict):
    id: str
    facility_id: str
    pipeline_operator_name: str
    max_h2s_ppm: float
    max_moisture_lb_per_mmscf: float
    max_co2_pct: float
    min_hhv_btu_per_scf: float
    max_hourly_injection_mmbtu: float
    ramp_buffer_minutes: int
    nomination_lead_hours: int
    status: str
    curtailment_count: int
    created_at: str
    updated_at: str
    version: int


class InjectionNomination(TypedDict):
    id: str
    interconnect_id: str
    ops_day_id: str
    window_start_utc: str
    window_end_utc: str
    nominated_mmbtu: float
    window_minutes: int
    hourly_rate_mmbtu: float
    status: str
    confirmed_mmbtu: Optional[float]
    delivered_mmbtu: Optional[float]
    created_at: str
    updated_at: str
    version: int


class CreditPathway(TypedDict):
    id: str
    facility_id: str
    program: str
    pathway_code: str
    reference_start_date: Optional[str]
    reference_end_date: Optional[str]
    status: str
    certified_ci_score: Optional[float]
    verified_ci_score: Optional[float]
    ci_adjustment: Optional[float]
    credits_issued_total: float
    credits_reversed_total: float
    credits_outstanding: float
    credit_control_residual: float
    created_at: str
    updated_at: str
    version: int


class CreditBatch(TypedDict):
    id: str
    pathway_id: str
    facility_id: str
    period_start_date: str
    period_end_date: str
    superseded_by_batch_id: Optional[str]
    status: str
    delivered_mmbtu: float
    ci_score_used: Optional[float]
    credit_quantity_provisional: Optional[float]
    credit_quantity_final: Optional[float]
    credit_value_cents: Optional[int]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VerificationAudit(TypedDict):
    id: str
    pathway_id: str
    audit_year: int
    verifier_body_name: str
    status: str
    actual_pipeline_mmbtu: Optional[float]
    actual_vs_tonnes_lagoon: Optional[float]
    actual_vs_tonnes_solid_storage: Optional[float]
    actual_vs_tonnes_daily_spread: Optional[float]
    actual_haul_tonne_km: Optional[float]
    actual_process_g_per_mj: Optional[float]
    reported_ci_score: Optional[float]
    ci_delta: Optional[float]
    finding_severity: Optional[str]
    remediation_round: int
    created_at: str
    updated_at: str
    version: int


class NutrientApplication(TypedDict):
    id: str
    dairy_id: str
    facility_id: str
    ops_day_id: str
    land_unit_code: str
    application_start_date: str
    application_end_date: str
    solids_tonnes_applied: float
    liquid_tonnes_applied: float
    pan_basis: str
    liquid_total_nitrogen_kg: float
    solids_total_nitrogen_kg: float
    plant_available_nitrogen_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RevenueStatement(TypedDict):
    id: str
    facility_id: str
    period_start_date: str
    period_end_date: str
    gas_revenue_cents: int
    superseded_by_statement_id: Optional[str]
    credit_revenue_cents: int
    gross_revenue_cents: int
    management_fee_rate: float
    management_fee_cents: int
    after_fee_cents: int
    reserve_sweep_cents: int
    net_distributable_cents: int
    share_lines: List[Dict[str, Any]]
    total_dairy_share_cents: int
    retained_cents: int
    dscr_at_close: float
    status: str
    approved_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
