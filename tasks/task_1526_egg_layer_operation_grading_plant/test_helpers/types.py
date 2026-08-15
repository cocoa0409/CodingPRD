"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FARM_MANAGER = "FarmManager"
    QUALITY_GRADER = "QualityGrader"
    QA_MANAGER = "QAManager"
    CONTRACT_MANAGER = "ContractManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class CertificationProgram(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    CAGE_FREE = "CAGE_FREE"
    PASTURE = "PASTURE"


class CompliancePosture(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class EnvironmentType(str, Enum):
    CAGED = "CAGED"
    AVIARY = "AVIARY"
    PASTURE_RANGE = "PASTURE_RANGE"


class HouseStatus(str, Enum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    DEPOPULATING = "DEPOPULATING"
    CLEANING = "CLEANING"
    RESTING = "RESTING"


class FlockStatus(str, Enum):
    PLACED = "PLACED"
    GROWING = "GROWING"
    LAYING = "LAYING"
    MOLT_REST = "MOLT_REST"
    DEPOPULATING = "DEPOPULATING"
    DEPLETED = "DEPLETED"


class QuarantineStatus(str, Enum):
    CLEAR = "CLEAR"
    QUARANTINED = "QUARANTINED"


class LayCycle(str, Enum):
    FIRST = "FIRST"
    SECOND = "SECOND"


class FeedDeliveryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"


class Grade(str, Enum):
    AA = "AA"
    A = "A"
    B = "B"


class SizeClass(str, Enum):
    PEEWEE = "PEEWEE"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    XLARGE = "XLARGE"
    JUMBO = "JUMBO"


class GradingRunStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class LotLifecycleStatus(str, Enum):
    FRESH = "FRESH"
    RELEASED = "RELEASED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    RECALLED = "RECALLED"


class HoldStatus(str, Enum):
    CLEAR = "CLEAR"
    HELD = "HELD"


class PricingModel(str, Enum):
    MARKET_INDEX = "MARKET_INDEX"
    COST_PLUS = "COST_PLUS"


class ClaimRequired(str, Enum):
    NONE = "NONE"
    CAGE_FREE = "CAGE_FREE"
    PASTURE = "PASTURE"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class TestType(str, Enum):
    ENVIRONMENTAL = "ENVIRONMENTAL"
    EGG_POOL = "EGG_POOL"


class SalmonellaTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COLLECTED = "COLLECTED"
    RESULTED = "RESULTED"
    CLEARED = "CLEARED"
    RESOLVED = "RESOLVED"


class TestResult(str, Enum):
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class AuditStandard(str, Enum):
    USDA_CAGE_FREE = "USDA_CAGE_FREE"
    PASTURE_RAISED = "PASTURE_RAISED"
    FDA_EGG_SAFETY = "FDA_EGG_SAFETY"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_RECORDED = "FINDINGS_RECORDED"
    CLOSED_PASSED = "CLOSED_PASSED"
    CLOSED_FAILED = "CLOSED_FAILED"


class AuditOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class RecallReason(str, Enum):
    SALMONELLA = "SALMONELLA"
    QUALITY = "QUALITY"
    LABELING = "LABELING"


class RecallStatus(str, Enum):
    INITIATED = "INITIATED"
    SCOPED = "SCOPED"
    CLOSED = "CLOSED"


class DispositionMethod(str, Enum):
    RENDERING = "RENDERING"
    COMPOST = "COMPOST"
    LIVE_SALE = "LIVE_SALE"
    EUTHANIZED = "EUTHANIZED"


class DispositionStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class Farm(TypedDict, total=False):
    id: str
    name: str
    certification_program: str
    daily_overhead_cents: int
    compliance_posture: str
    active_flock_count: int
    created_at: str
    updated_at: str
    version: int


class House(TypedDict, total=False):
    id: str
    farm_id: str
    house_code: str
    environment_type: str
    capacity_hens: int
    status: str
    status_changed_date: str
    current_flock_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Flock(TypedDict, total=False):
    id: str
    house_id: str
    breed_code: str
    breed_peak_rate_pct: float
    placement_date: str
    initial_hen_count: int
    pullet_cost_cents: int
    prior_flock_id: Optional[str]
    depleted_date: Optional[str]
    lay_cycle: str
    molt_count: int
    molt_started_date: Optional[str]
    status: str
    quarantine_status: str
    age_weeks: int
    current_lay_rate_pct: float
    current_hen_count: int
    cumulative_mortality: int
    cumulative_eggs: int
    ungraded_egg_pool: int
    loose_egg_pool: int
    created_at: str
    updated_at: str
    version: int


class FeedDelivery(TypedDict, total=False):
    id: str
    farm_id: str
    delivered_at: str
    quantity_kg: int
    cost_per_kg_cents: int
    remaining_kg: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionDay(TypedDict, total=False):
    # Immutable event log: carries id + created_at only — NO updated_at, NO version (PRD §2.5).
    id: str
    flock_id: str
    lay_date: str
    eggs_collected: int
    rejected_eggs: int
    feed_issued_kg: int
    mortality_count: int
    hens_at_start: int
    feed_cost_cents: int
    lay_rate_pct: float
    created_at: str


class GradingRun(TypedDict, total=False):
    id: str
    flock_id: str
    grade: str
    eggs_to_grade: int
    peewee_count: int
    small_count: int
    medium_count: int
    large_count: int
    xlarge_count: int
    jumbo_count: int
    cracked_count: int
    dirty_count: int
    blood_spot_count: int
    status: str
    submitted_by: str
    confirmed_by: Optional[str]
    pack_date: Optional[str]
    lot_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class EggLot(TypedDict, total=False):
    id: str
    grading_run_id: str
    flock_id: str
    farm_id: str
    contract_id: Optional[str]
    recall_id: Optional[str]
    size_class: str
    grade: str
    dozen_count: int
    claim_program: str
    pack_date: str
    sell_by_date: str
    ship_date: Optional[str]
    lifecycle_status: str
    hold_status: str
    created_at: str
    updated_at: str
    version: int


class SettlementLine(TypedDict, total=False):
    lot_id: str
    size_class: str
    grade: str
    dozen_count: int
    price_cents_per_dozen: int
    line_amount_cents: int


class RetailerContract(TypedDict, total=False):
    id: str
    farm_id: str
    retailer_name: str
    pricing_model: str
    spread_cents: int
    margin_pct: float
    claim_premium_pct: float
    claim_required: str
    effective_start: str
    effective_end: str
    weekly_min_dozen: int
    max_open_dozen: int
    status: str
    allocated_dozen: int
    shipped_dozen: int
    held_allocated_dozen: int
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    contract_id: str
    period_start: str
    period_end: str
    market_index_cents: Optional[int]
    expected_contract_version: int
    status: str
    pricing_model_used: str
    lines: List[SettlementLine]
    cost_per_dozen_cents: Optional[float]
    subtotal_cents: int
    rebate_pct: float
    rebate_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class SalmonellaTest(TypedDict, total=False):
    id: str
    flock_id: str
    test_type: str
    scheduled_date: str
    status: str
    collected_date: Optional[str]
    collected_by: Optional[str]
    result: Optional[str]
    resulted_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict, total=False):
    id: str
    farm_id: str
    standard: str
    audit_date: str
    status: str
    findings_count: int
    corrective_actions_open: int
    outcome: Optional[str]
    closed_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict, total=False):
    id: str
    farm_id: str
    salmonella_test_id: Optional[str]
    scope_flock_id: Optional[str]
    reason: str
    pack_window_start: str
    pack_window_end: str
    status: str
    scoped_lot_count: int
    created_at: str
    updated_at: str
    version: int


class SpentHenDisposition(TypedDict, total=False):
    id: str
    flock_id: str
    method: str
    hen_count: int
    revenue_cents: int
    status: str
    completed_date: Optional[str]
    created_at: str
    updated_at: str
    version: int
