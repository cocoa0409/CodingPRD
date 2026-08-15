"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource kind in this API
carries the four system-managed fields id + created_at + updated_at +
version (PRD common resource properties), so every TypedDict below carries
them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    QUARRY_ADMIN = "QuarryAdmin"
    SITE_MANAGER = "SiteManager"
    BLAST_FOREMAN = "BlastForeman"
    PLANT_OPERATOR = "PlantOperator"
    SCALE_HOUSE_OPERATOR = "ScaleHouseOperator"
    QC_TECHNICIAN = "QCTechnician"
    SALES_AGENT = "SalesAgent"
    FINANCE_CLERK = "FinanceClerk"
    SAFETY_OFFICER = "SafetyOfficer"


class SitePosture(str, Enum):
    OPERATING = "OPERATING"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class BondAdequacy(str, Enum):
    ADEQUATE = "ADEQUATE"
    DEFICIENT = "DEFICIENT"


class BenchStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    ON_HOLD = "ON_HOLD"
    MINED_OUT = "MINED_OUT"
    RECLAMATION_IN_PROGRESS = "RECLAMATION_IN_PROGRESS"
    RECLAIMED = "RECLAIMED"


class ShotPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DRILLING = "DRILLING"
    DRILLED = "DRILLED"
    LOADED = "LOADED"
    FIRED = "FIRED"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"


class MuckpileStatus(str, Enum):
    OPEN = "OPEN"
    DEPLETED = "DEPLETED"


class SpecCategory(str, Enum):
    COARSE = "COARSE"
    FINE = "FINE"
    RIPRAP = "RIPRAP"


class ProductSpecStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StockpileStatus(str, Enum):
    OPEN = "OPEN"
    QUARANTINED = "QUARANTINED"
    CLOSED = "CLOSED"


class GradationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class GradationTestStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class ScaleType(str, Enum):
    TRUCK = "TRUCK"
    BELT = "BELT"


class ScaleStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CalibrationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CalibrationStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class CircuitLine(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class ProductionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"
    CANCELLED = "CANCELLED"


class ReconciliationStatus(str, Enum):
    UNRECONCILED = "UNRECONCILED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class FreightZoneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SalesOrderStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    BACKORDERED = "BACKORDERED"
    IN_FULFILLMENT = "IN_FULFILLMENT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ScaleTicketStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class RoyaltyAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class RoyaltyStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class MshaInspectionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MshaCitationStatus(str, Enum):
    ISSUED = "ISSUED"
    ABATED = "ABATED"
    VACATED = "VACATED"


class CourseType(str, Enum):
    NEW_MINER = "NEW_MINER"
    ANNUAL_REFRESHER = "ANNUAL_REFRESHER"
    TASK_TRAINING = "TASK_TRAINING"


class ReclamationBondStatus(str, Enum):
    POSTED = "POSTED"
    PARTIALLY_RELEASED = "PARTIALLY_RELEASED"
    FULLY_RELEASED = "FULLY_RELEASED"


class PriorityClass(str, Enum):
    CONTRACT = "CONTRACT"
    SPOT = "SPOT"
    INTERNAL = "INTERNAL"


class QueueEntryStatus(str, Enum):
    QUEUED = "QUEUED"
    AT_SCALE_IN = "AT_SCALE_IN"
    LOADING = "LOADING"
    AT_SCALE_OUT = "AT_SCALE_OUT"
    EXITED = "EXITED"
    NO_SHOW = "NO_SHOW"


class QuarrySite(TypedDict, total=False):
    id: str
    name: str
    permitted_acres: float
    bond_rate_per_acre_usd: float
    disturbed_acres: float
    bond_required_usd: float
    bond_posted_usd: float
    bond_adequacy: str
    posture: str
    created_at: str
    updated_at: str
    version: int


class Bench(TypedDict, total=False):
    id: str
    site_id: str
    bench_label: str
    elevation_ft: float
    acreage: float
    status: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShotPlan(TypedDict, total=False):
    id: str
    bench_id: str
    hole_count: int
    burden_ft: float
    spacing_ft: float
    hole_depth_ft: float
    explosive_per_hole_lbs: float
    drilled_hole_count: int
    loaded_explosive_lbs: Optional[float]
    estimated_tons: float
    powder_factor: float
    status: str
    hold_return_state: Optional[str]
    submitted_by_user_id: str
    approved_by_user_id: Optional[str]
    fired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Muckpile(TypedDict, total=False):
    id: str
    shot_plan_id: str
    estimated_tons: float
    actual_fed_tons: float
    remaining_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class GradationBand(TypedDict):
    sieve: str
    min_pct: float
    max_pct: float


class ProductSpec(TypedDict, total=False):
    id: str
    spec_code: str
    category: str
    gradation_bands: List[GradationBand]
    base_price_per_ton: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Stockpile(TypedDict, total=False):
    id: str
    site_id: str
    product_spec_id: str
    capacity_tons: float
    on_hand_tons: float
    reserved_tons: float
    available_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SieveResult(TypedDict):
    sieve: str
    pct_passing: float


class GradationTest(TypedDict, total=False):
    id: str
    stockpile_id: str
    sampled_at: str
    sieve_results: List[SieveResult]
    result: str
    status: str
    reported_by_user_id: str
    confirmed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Scale(TypedDict, total=False):
    id: str
    site_id: str
    scale_code: str
    scale_type: str
    status: str
    certified_through: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScaleCalibration(TypedDict, total=False):
    id: str
    scale_id: str
    calibrated_on: str
    as_found_error_pct: float
    as_left_error_pct: float
    result: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlantRun(TypedDict, total=False):
    id: str
    site_id: str
    muckpile_id: str
    belt_scale_id: str
    circuit_line: str
    started_at: Optional[str]
    ended_at: Optional[str]
    run_hours: Optional[float]
    input_tons: Optional[float]
    reconciled_input_tons: Optional[float]
    outputs: list
    yield_summary: Optional[dict]
    production_status: str
    reconciliation_status: str
    created_at: str
    updated_at: str
    version: int


class FreightZone(TypedDict, total=False):
    id: str
    zone_code: str
    distance_miles: float
    base_freight_per_ton: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    site_id: str
    product_spec_id: str
    freight_zone_id: str
    customer_name: str
    quantity_tons: float
    stockpile_id: Optional[str]
    quoted_material_per_ton: float
    quoted_freight_per_ton: float
    quoted_surcharge_per_ton: float
    quoted_unit_delivered_per_ton: float
    quoted_total_usd: float
    prices_pinned: bool
    fulfilled_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ScaleTicket(TypedDict, total=False):
    id: str
    queue_entry_id: str
    sales_order_id: str
    scale_id: str
    site_id: str
    stockpile_id: str
    truck_id: str
    gross_lbs: float
    tare_lbs: Optional[float]
    net_tons: Optional[float]
    tare_variance_pct: Optional[float]
    royalty_provisional_usd: Optional[float]
    completed_at: Optional[str]
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyAgreement(TypedDict, total=False):
    id: str
    site_id: str
    landowner_name: str
    base_rate_per_ton: float
    tier_threshold_tons: float
    tier_rate_per_ton: float
    effective_from: str
    effective_to: Optional[str]
    supersedes_agreement_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict, total=False):
    id: str
    site_id: str
    period_start: str
    period_end: str
    royalty_agreement_id: str
    tons_sold: float
    ytd_tons_before: float
    ytd_tons_after: float
    royalty_due_usd: float
    status: str
    generated_by_user_id: str
    issued_by_user_id: Optional[str]
    issued_on: Optional[str]
    due_on: Optional[str]
    paid_on: Optional[str]
    penalty_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class MshaInspection(TypedDict, total=False):
    id: str
    site_id: str
    inspection_type: str
    opened_on: str
    closed_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MshaCitation(TypedDict, total=False):
    id: str
    msha_inspection_id: str
    citation_code: str
    s_and_s: bool
    abatement_due_on: str
    abated_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    miner_name: str
    miner_user_id: str
    course_type: str
    completed_on: str
    expires_on: str
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class ReclamationBond(TypedDict, total=False):
    id: str
    site_id: str
    surety_name: str
    amount_usd: float
    released_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TruckQueueEntry(TypedDict, total=False):
    id: str
    site_id: str
    truck_id: str
    priority_class: str
    certified_tare_lbs: float
    max_payload_lbs: float
    queued_at: str
    scale_ticket_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
