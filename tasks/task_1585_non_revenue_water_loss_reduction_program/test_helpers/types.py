"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource narratives (§2.4 common fields, §3 entity
lifecycle vocabularies, §2.1 role list).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Role enum (PRD §2.1) ─────────────────────────────

class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    UTILITY_ANALYST = "UtilityAnalyst"
    FIELD_SUPERVISOR = "FieldSupervisor"
    METER_TECHNICIAN = "MeterTechnician"
    INVESTIGATOR = "Investigator"
    REGULATOR_LIAISON = "RegulatorLiaison"


# ─── Status / vocabulary enums (PRD §3) ───────────────

class DmaPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class WaterBalanceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class NightFlowStatus(str, Enum):
    RECORDED = "RECORDED"
    ANALYZED = "ANALYZED"
    VOID = "VOID"
    SUPERSEDED = "SUPERSEDED"


class LeakSignal(str, Enum):
    NONE = "NONE"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class LeakSurveyStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_FIELD = "IN_FIELD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SurveyMethod(str, Enum):
    ACOUSTIC = "ACOUSTIC"
    CORRELATOR = "CORRELATOR"
    SATELLITE = "SATELLITE"
    STEP_TEST = "STEP_TEST"
    NOISE_LOGGER = "NOISE_LOGGER"


class LeakStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    REPAIR_SCHEDULED = "REPAIR_SCHEDULED"
    REPAIRED = "REPAIRED"
    VERIFIED_REPAIR = "VERIFIED_REPAIR"
    REOPENED = "REOPENED"
    WITHDRAWN = "WITHDRAWN"


class PriorityBand(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class MeterStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    FLAGGED_FOR_REPLACEMENT = "FLAGGED_FOR_REPLACEMENT"
    REPLACED = "REPLACED"
    RETIRED = "RETIRED"


class ReplacementPolicy(str, Enum):
    AGE_BASED = "AGE_BASED"
    ACCURACY_BASED = "ACCURACY_BASED"
    HYBRID = "HYBRID"


class AccuracyTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AccuracyTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_GATHERING = "EVIDENCE_GATHERING"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNFOUNDED = "UNFOUNDED"
    CLOSED = "CLOSED"


class BillingAdjustmentStatus(str, Enum):
    NONE = "NONE"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    POSTED = "POSTED"


class PressureProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    COMMISSIONED = "COMMISSIONED"


class InterventionKind(str, Enum):
    LEAK_REPAIR_PROGRAM = "LEAK_REPAIR_PROGRAM"
    METER_REPLACEMENT_PROGRAM = "METER_REPLACEMENT_PROGRAM"
    PRESSURE_MANAGEMENT = "PRESSURE_MANAGEMENT"
    UNAUTHORIZED_USE_ENFORCEMENT = "UNAUTHORIZED_USE_ENFORCEMENT"


class InterventionProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class BenchmarkReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


# ─── Entity TypedDicts ────────────────────────────────
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).

class DistrictMeteredArea(TypedDict, total=False):
    id: str
    code: str
    name: str
    connection_count: int
    mains_length_km: float
    target_nrw_pct: float
    posture: str
    latest_nrw_pct: Optional[float]
    open_leak_count: int
    created_at: str
    updated_at: str
    version: int


class WaterBalancePeriod(TypedDict, total=False):
    id: str
    dma_id: str
    period_start: str
    period_end: str
    system_input_volume_m3: float
    billed_authorized_m3: float
    unbilled_authorized_m3: float
    unauthorized_consumption_m3: float
    metering_inaccuracy_m3: float
    status: str
    created_by_user_id: str
    nrw_volume_m3: float
    nrw_pct: float
    apparent_loss_m3: float
    real_loss_m3: float
    ili: Optional[float]
    created_at: str
    updated_at: str
    version: int


class NightFlowAssessment(TypedDict, total=False):
    id: str
    dma_id: str
    window_start: str
    window_end: str
    measured_mnf_lps: float
    expected_legitimate_night_use_lps: float
    status: str
    net_night_flow_lps: float
    net_night_flow_pct: Optional[float]
    leak_signal: str
    created_at: str
    updated_at: str
    version: int


class LeakSurvey(TypedDict, total=False):
    id: str
    dma_id: str
    planned_start: str
    planned_end: str
    method: str
    crew_lead_user_id: str
    status: str
    coverage_pct: Optional[float]
    leaks_found_count: int
    created_at: str
    updated_at: str
    version: int


class Leak(TypedDict, total=False):
    id: str
    survey_id: str
    location_description: str
    estimated_loss_lps: float
    detected_at: str
    repair_cost_estimate: float
    actual_repair_cost: Optional[float]
    status: str
    reported_by_user_id: str
    repair_priority_score: float
    priority_band: str
    annualized_loss_m3: float
    created_at: str
    updated_at: str
    version: int


class CustomerMeter(TypedDict, total=False):
    id: str
    dma_id: str
    serial_number: str
    size_mm: int
    installed_at: str
    replacement_policy: str
    status: str
    last_test_accuracy_pct: Optional[float]
    replacement_due: bool
    created_at: str
    updated_at: str
    version: int


class MeterAccuracyTest(TypedDict, total=False):
    id: str
    meter_id: str
    tested_at: str
    flow_rate_lps: float
    registered_volume_m3: float
    reference_volume_m3: float
    status: str
    accuracy_pct: float
    result: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnauthorizedConsumptionCase(TypedDict, total=False):
    id: str
    dma_id: str
    service_location_ref: str
    opened_at: str
    investigation_status: str
    billing_adjustment_status: str
    estimated_loss_m3: Optional[float]
    proposed_adjustment_amount: Optional[float]
    substantiated_by_user_id: Optional[str]
    posted_adjustment_amount: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PressureProject(TypedDict, total=False):
    id: str
    dma_id: str
    name: str
    planned_start: str
    planned_end: str
    baseline_pressure_m: float
    target_pressure_m: float
    status: str
    measured_pressure_m: Optional[float]
    pressure_reduction_pct: Optional[float]
    estimated_leak_reduction_m3_per_year: Optional[float]
    created_at: str
    updated_at: str
    version: int


class InterventionProposal(TypedDict, total=False):
    id: str
    dma_id: str
    kind: str
    capital_cost: float
    annual_om_cost: float
    expected_volume_saved_m3_per_year: float
    status: str
    benefit_cost_ratio: float
    payback_years: Optional[float]
    created_at: str
    updated_at: str
    version: int


class BenchmarkReport(TypedDict, total=False):
    id: str
    reporting_year: int
    reporting_period_start: str
    reporting_period_end: str
    dma_ids: List[str]
    status: str
    utility_nrw_pct: Optional[float]
    utility_ili: Optional[float]
    per_dma_breakdown: Optional[List[Dict[str, Any]]]
    created_at: str
    updated_at: str
    version: int


# Audit event is append-only (PRD §2.4): only id + created_at of the common
# fields; no updated_at, no version.
class AuditEvent(TypedDict, total=False):
    id: str
    entity_type: str
    entity_id: str
    action: str
    actor_user_id: str
    actor_role: str
    detail: Dict[str, Any]
    created_at: str
