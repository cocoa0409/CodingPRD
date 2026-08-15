"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    CREW_LEAD = "CrewLead"
    WATER_QUALITY_OFFICER = "WaterQualityOfficer"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PUBLIC_WORKS_ENGINEER = "PublicWorksEngineer"
    SYSTEM = "System"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class ConditionStatus(str, Enum):
    NONE = "NONE"
    WATCH = "WATCH"
    CANDIDATE = "CANDIDATE"
    PROGRAMMED = "PROGRAMMED"
    REPLACED = "REPLACED"


class ValveStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AnomalyType(str, Enum):
    PRESSURE_DROP = "PRESSURE_DROP"
    FLOW_SPIKE = "FLOW_SPIKE"


class CorrelationStatus(str, Enum):
    UNCORRELATED = "UNCORRELATED"
    CORRELATED = "CORRELATED"


class BreakStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    ISOLATED = "ISOLATED"
    IN_REPAIR = "IN_REPAIR"
    REPAIRED = "REPAIRED"
    RESTORED = "RESTORED"
    CLOSED = "CLOSED"
    FALSE_ALARM = "FALSE_ALARM"


class BreakType(str, Enum):
    CIRCUMFERENTIAL = "CIRCUMFERENTIAL"
    SPLIT = "SPLIT"
    BLOWOUT = "BLOWOUT"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class BreakSource(str, Enum):
    CUSTOMER_CALL = "CUSTOMER_CALL"
    SENSOR_SCADA = "SENSOR_SCADA"
    CREW_OBSERVATION = "CREW_OBSERVATION"


class IsolationStatus(str, Enum):
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    RESTORED = "RESTORED"
    SUPERSEDED = "SUPERSEDED"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISPATCHED = "DISPATCHED"


class EquipmentClass(str, Enum):
    LIGHT = "LIGHT"
    HEAVY = "HEAVY"


class ClampKit(str, Enum):
    CLAMP_A = "CLAMP_A"
    CLAMP_B = "CLAMP_B"
    CLAMP_C = "CLAMP_C"


class WorkStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    REPAIR_COMPLETE = "REPAIR_COMPLETE"
    CANCELLED = "CANCELLED"


class IssueReason(str, Enum):
    MANUAL = "MANUAL"
    AUTO_OUTAGE_THRESHOLD = "AUTO_OUTAGE_THRESHOLD"


class AdvisoryStatus(str, Enum):
    ISSUED = "ISSUED"
    LIFTED = "LIFTED"


class ColiformResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class TestOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RestorationStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"


class ControlPlan(str, Enum):
    LANE_CLOSURE = "LANE_CLOSURE"
    FULL_CLOSURE = "FULL_CLOSURE"
    FLAGGING = "FLAGGING"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class Material(str, Enum):
    CAST_IRON = "CAST_IRON"
    DUCTILE_IRON = "DUCTILE_IRON"
    PVC = "PVC"
    AC = "AC"
    STEEL = "STEEL"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------

class PipeSegment(TypedDict, total=False):
    id: str
    segment_ref: str
    material: str
    diameter_inches: int
    install_year: int
    condition_status: str
    repeat_break_count_36mo: int
    provisional_break_count_36mo: int
    replaced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Valve(TypedDict, total=False):
    id: str
    valve_code: str
    pipe_segment_id: str
    coverage_zone: str
    customers_served: int
    valve_status: str
    created_at: str
    updated_at: str
    version: int


class PressureAnomaly(TypedDict, total=False):
    id: str
    pipe_segment_id: str
    anomaly_type: str
    observed_at: str
    magnitude_pct: int
    correlated_break_report_id: Optional[str]
    correlation_status: str
    created_at: str
    updated_at: str
    version: int


class BreakReport(TypedDict, total=False):
    id: str
    location_description: str
    source: str
    pipe_segment_id: Optional[str]
    break_type: Optional[str]
    severity: Optional[str]
    break_status: str
    confirmed_at: Optional[str]
    repaired_at: Optional[str]
    customers_out_of_service: int
    total_repair_cost_cents: int
    total_restoration_cost_cents: int
    claims_liability_cents: int
    total_claims_paid_cents: int
    total_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class IsolationEvent(TypedDict, total=False):
    id: str
    break_report_id: str
    valve_ids: List[str]
    outage_extent_customers: Optional[int]
    isolation_status: str
    executed_at: Optional[str]
    restored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict, total=False):
    id: str
    crew_name: str
    crew_size: int
    equipment_class: str
    hourly_rate_cents: int
    crew_status: str
    completed_job_count: int
    created_at: str
    updated_at: str
    version: int


class MaterialLine(TypedDict, total=False):
    item_code: str
    quantity: float
    unit_price_cents: int


class WorkOrder(TypedDict, total=False):
    id: str
    break_report_id: str
    est_pipe_length_ft: int
    crew_id: Optional[str]
    work_status: str
    required_equipment_class: str
    required_clamp_kit: str
    estimated_cost_cents: Optional[int]
    actual_cost_cents: Optional[int]
    cost_variance_cents: Optional[int]
    dispatch_window_start: Optional[str]
    dispatch_window_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoilWaterAdvisory(TypedDict, total=False):
    id: str
    break_report_id: str
    issue_reason: str
    advisory_status: str
    issued_by_user_id: str
    lifted_by_user_id: Optional[str]
    issued_at: str
    lifted_at: Optional[str]
    consecutive_pass_count: int
    last_sample_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaterQualityTest(TypedDict, total=False):
    id: str
    advisory_id: str
    sampled_at: str
    chlorine_residual_mg_l: float
    coliform_result: str
    test_outcome: str
    created_at: str
    updated_at: str
    version: int


class RestorationJob(TypedDict, total=False):
    id: str
    work_order_id: str
    restoration_status: str
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    traffic_permit_id: Optional[str]
    patch_cost_cents: Optional[int]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrafficPermit(TypedDict, total=False):
    id: str
    break_report_id: str
    street_block: str
    valid_from: str
    valid_to: str
    control_plan: str
    permit_status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    break_report_id: str
    claimant_name: str
    claimed_amount_cents: int
    claim_status: str
    approved_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
