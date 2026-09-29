"""Domain types for the Carbon Sequestration Project Permitting API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    PROJECT_DEVELOPER = "ProjectDeveloper"
    REGULATORY_REVIEWER = "RegulatoryReviewer"
    INDEPENDENT_VERIFIER = "IndependentVerifier"
    LANDOWNER = "Landowner"


# ---------------------------------------------------------------------------
# Storage project state dimensions (PRD §3.1, §2.9, §3.5, §3.8, §3.9)
# ---------------------------------------------------------------------------


class StorageProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SITE_CHARACTERIZATION = "SITE_CHARACTERIZATION"
    PERMITTING = "PERMITTING"
    INJECTION_AUTHORIZED = "INJECTION_AUTHORIZED"
    INJECTION_ACTIVE = "INJECTION_ACTIVE"
    PISC = "PISC"
    CLOSED = "CLOSED"


class OperationalPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class UnitizationStatus(str, Enum):
    NOT_FILED = "NOT_FILED"
    FILED = "FILED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class ClosureStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    CERTIFIED = "CERTIFIED"


class AssuranceCoverageStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    FUNDED = "FUNDED"
    UNDERFUNDED = "UNDERFUNDED"


# ---------------------------------------------------------------------------
# Geologic model state dimensions (PRD §3.2, §3.3)
# ---------------------------------------------------------------------------


class GeologicModelStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PlumeStatus(str, Enum):
    NOT_RUN = "NOT_RUN"
    SIMULATED = "SIMULATED"
    AOR_FINALIZED = "AOR_FINALIZED"


class SealClassification(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class AssessmentVariant(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    PROBABILISTIC_P10 = "PROBABILISTIC_P10"


# ---------------------------------------------------------------------------
# Legacy wellbore (PRD §3.4)
# ---------------------------------------------------------------------------


class CorrectiveActionStatus(str, Enum):
    OUT_OF_AOR = "OUT_OF_AOR"
    IDENTIFIED = "IDENTIFIED"
    CA_REQUIRED = "CA_REQUIRED"
    CA_SCHEDULED = "CA_SCHEDULED"
    CA_COMPLETE = "CA_COMPLETE"
    CA_WAIVED = "CA_WAIVED"


class PlugCondition(str, Enum):
    CEMENTED = "CEMENTED"
    PARTIALLY_PLUGGED = "PARTIALLY_PLUGGED"
    OPEN_HOLE = "OPEN_HOLE"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Pore space tract (PRD §3.5)
# ---------------------------------------------------------------------------


class LeaseStatus(str, Enum):
    UNLEASED = "UNLEASED"
    OFFER_SENT = "OFFER_SENT"
    COUNTERED = "COUNTERED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    UNITIZED = "UNITIZED"
    TERMINATED = "TERMINATED"


# ---------------------------------------------------------------------------
# Injection well permit (PRD §3.6)
# ---------------------------------------------------------------------------


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    TECHNICAL_REVIEW = "TECHNICAL_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ConstructionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    DRILLING = "DRILLING"
    CASING_SET = "CASING_SET"
    CEMENT_LOGGED = "CEMENT_LOGGED"
    MIT_PENDING = "MIT_PENDING"
    COMPLETED = "COMPLETED"


class CasingProgram(str, Enum):
    LONG_STRING_CEMENTED_TO_SURFACE = "LONG_STRING_CEMENTED_TO_SURFACE"
    LINER = "LINER"
    SINGLE_STRING = "SINGLE_STRING"


class MitTestType(str, Enum):
    ANNULUS_PRESSURE = "ANNULUS_PRESSURE"
    TEMPERATURE_LOG = "TEMPERATURE_LOG"
    CASING_INSPECTION_LOG = "CASING_INSPECTION_LOG"


class MitResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# Monitoring plan and method (PRD §3.7)
# ---------------------------------------------------------------------------


class MonitoringPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVIEW_COMPLETE = "REVIEW_COMPLETE"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    REJECTED = "REJECTED"


class MonitoringMethodStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MonitoringDomain(str, Enum):
    SUBSURFACE = "SUBSURFACE"
    SURFACE = "SURFACE"
    ATMOSPHERIC = "ATMOSPHERIC"


# ---------------------------------------------------------------------------
# Financial instrument (PRD §3.8)
# ---------------------------------------------------------------------------


class InstrumentStatus(str, Enum):
    POSTED = "POSTED"
    ALLOCATED = "ALLOCATED"
    DRAWN = "DRAWN"
    RELEASED = "RELEASED"


class InstrumentType(str, Enum):
    TRUST_FUND = "TRUST_FUND"
    SURETY_BOND = "SURETY_BOND"
    LETTER_OF_CREDIT = "LETTER_OF_CREDIT"
    INSURANCE = "INSURANCE"


# ---------------------------------------------------------------------------
# Injection period record, claim, remediation order (PRD §3.9, §3.8)
# ---------------------------------------------------------------------------


class InjectionPeriodStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    VOIDED = "VOIDED"


class TaxCreditClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ALLOWED = "ALLOWED"
    DISALLOWED = "DISALLOWED"


class ClaimVariant(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"


class RemediationOrderStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class RemediationTriggerType(str, Enum):
    SEAL_BREACH_INDICATION = "SEAL_BREACH_INDICATION"
    WELL_INTEGRITY_LOSS = "WELL_INTEGRITY_LOSS"
    PLUME_EXCURSION = "PLUME_EXCURSION"
    GROUNDWATER_IMPACT = "GROUNDWATER_IMPACT"


class RemediationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Entity payload shapes
#
# Every entity below carries id, created_at, updated_at and version, with the
# single exception of InjectionPeriodRecord, which the PRD declares carries only
# id and created_at.
# ---------------------------------------------------------------------------


class StorageProject(TypedDict):
    id: str
    name: str
    operator_name: str
    basin_code: str
    total_project_acreage: float
    requested_annual_injection_rate_tpy: float
    annual_monitoring_cost_usd: float
    required_consent_pct: float
    ca_rig_slots: int
    status: str
    operational_posture: str
    governing_geologic_model_id: Optional[str]
    aor_radius_km: float
    secured_acreage: float
    outstanding_acreage: float
    pore_space_consent_pct: float
    pore_space_bonus_total_usd: float
    unitization_status: str
    unitization_consent_pct_at_filing: Optional[float]
    statutory_bonus_per_acre_usd: Optional[float]
    corrective_action_completion_pct: float
    cumulative_stored_tonnes: float
    pending_credit_usd: float
    required_financial_assurance_usd: float
    allocated_assurance_usd: float
    assurance_coverage_status: str
    effective_annual_monitoring_cost_usd: float
    pisc_duration_years: int
    alternative_timeframe_years: Optional[int]
    pisc_start_at: Optional[str]
    pisc_elapsed_years: float
    non_endangerment_demonstrated: bool
    closure_status: str
    closure_certified_by_user_id: Optional[str]
    closure_certified_at: Optional[str]
    open_remediation_count: int
    created_at: str
    updated_at: str
    version: int


class GeologicModel(TypedDict):
    id: str
    project_id: str
    supersedes_model_id: Optional[str]
    model_label: str
    injection_zone_top_depth_m: float
    injection_zone_thickness_m: float
    seal_thickness_m: float
    capillary_entry_pressure_psi: float
    p10_seal_thickness_m: float
    p10_capillary_entry_pressure_psi: float
    reservoir_pressure_psi: float
    fracture_pressure_psi: float
    permeability_md: float
    porosity_fraction: float
    assessment_variant: str
    seal_integrity_index: float
    seal_integrity_index_p10: float
    seal_classification: str
    max_injection_rate_tpy: float
    effective_injection_rate_tpy: float
    injection_years: Optional[int]
    plume_radius_km: float
    pressure_front_radius_km: float
    aor_radius_km: float
    plume_status: str
    status: str
    reviewer_user_id: Optional[str]
    revision_round_count: int
    created_at: str
    updated_at: str
    version: int


class LegacyWellbore(TypedDict):
    id: str
    project_id: str
    api_number: str
    distance_from_injector_km: float
    total_depth_m: float
    penetrates_seal: bool
    plug_condition: str
    plug_record_available: bool
    risk_score: float
    ca_cost_estimate_usd: float
    corrective_action_status: str
    ca_window_start: Optional[str]
    ca_window_end: Optional[str]
    waiver_reviewer_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PoreSpaceTract(TypedDict):
    id: str
    project_id: str
    tract_label: str
    acreage: float
    ownership_pct: float
    landowner_user_id: str
    lease_status: str
    current_offer_bonus_per_acre_usd: Optional[float]
    current_offer_royalty_rate_pct: Optional[float]
    counter_bonus_per_acre_usd: Optional[float]
    executed_bonus_per_acre_usd: Optional[float]
    executed_royalty_rate_pct: Optional[float]
    lease_term_start: Optional[str]
    lease_term_end: Optional[str]
    negotiation_round_count: int
    bonus_settlement_usd: float
    net_acreage: float
    created_at: str
    updated_at: str
    version: int


class InjectionWellPermit(TypedDict):
    id: str
    project_id: str
    geologic_model_id: str
    well_name: str
    casing_program: str
    corrosion_resistant_material: bool
    tubing_packer_installed: bool
    requested_injection_pressure_psi: float
    max_injection_pressure_psi: float
    authorized_injection_rate_tpy: float
    permit_status: str
    construction_status: str
    last_mit_type: Optional[str]
    last_mit_result: Optional[str]
    last_mit_at: Optional[str]
    mit_pass_count: int
    technical_reviewer_user_id: Optional[str]
    revision_round_count: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringPlan(TypedDict):
    id: str
    project_id: str
    plan_label: str
    status: str
    technical_review_complete: bool
    public_comment_complete: bool
    subsurface_subscore: float
    surface_subscore: float
    atmospheric_subscore: float
    coverage_score: float
    condition_count: int
    approved_by_user_id: Optional[str]
    revision_round_count: int
    created_at: str
    updated_at: str
    version: int


class MonitoringMethod(TypedDict):
    id: str
    monitoring_plan_id: str
    domain: str
    technique: str
    detection_threshold_tpy: float
    frequency_per_year: int
    spatial_coverage_pct: float
    method_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancialInstrument(TypedDict):
    id: str
    project_id: str
    instrument_type: str
    face_amount_usd: float
    allocated_ca_usd: float
    allocated_plugging_usd: float
    allocated_pisc_usd: float
    allocated_emergency_usd: float
    unallocated_usd: float
    drawn_usd: float
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InjectionPeriodRecord(TypedDict):
    """An injection period record carries only id and created_at.

    The PRD states it has neither updated_at nor version, and that neither
    field appears in its response payload.
    """

    id: str
    permit_id: str
    period_start: str
    period_end: str
    mass_injected_tonnes: float
    measured_leakage_tonnes: float
    net_stored_tonnes: float
    status: str
    voided_at: Optional[str]
    created_at: str


class TaxCreditClaim(TypedDict):
    id: str
    project_id: str
    monitoring_plan_id: str
    tax_year: int
    claim_variant: str
    lca_upstream_emissions_factor: float
    reported_tonnes: float
    verified_tonnes: float
    credit_rate_usd_per_tonne: float
    credit_amount_usd: float
    status: str
    submitted_by_user_id: Optional[str]
    verifier_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationOrder(TypedDict):
    id: str
    project_id: str
    trigger_type: str
    severity: str
    narrative: str
    reserve_draw_usd: float
    status: str
    opened_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
