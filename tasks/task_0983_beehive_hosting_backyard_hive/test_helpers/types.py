"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class SeasonStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class HostStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    LIMITED = "LIMITED"
    SUSPENDED = "SUSPENDED"


class SiteStatus(str, Enum):
    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"


class AgreementStatus(str, Enum):
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    ACTIVE = "ACTIVE"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class HiveLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    DEAD = "DEAD"
    REMOVED = "REMOVED"


class HivePosture(str, Enum):
    THRIVING = "THRIVING"
    STABLE = "STABLE"
    WATCH = "WATCH"
    TREATMENT_REQUIRED = "TREATMENT_REQUIRED"
    QUARANTINED = "QUARANTINED"


class InspectionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    VERIFIED = "VERIFIED"


class TreatmentProduct(str, Enum):
    OXALIC_ACID = "OXALIC_ACID"
    APIVAR = "APIVAR"
    FORMIC_ACID = "FORMIC_ACID"


class TreatmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class HarvestStatus(str, Enum):
    RECORDED = "RECORDED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"
    SETTLED = "SETTLED"


class AllocationStatus(str, Enum):
    PROJECTED = "PROJECTED"
    FINALIZED = "FINALIZED"
    DISTRIBUTED = "DISTRIBUTED"


class SwarmEventStatus(str, Enum):
    REPORTED = "REPORTED"
    DISPATCHED = "DISPATCHED"
    CAPTURED = "CAPTURED"
    LOST = "LOST"
    EXPIRED = "EXPIRED"


class RemovalReason(str, Enum):
    RELOCATION = "RELOCATION"
    NUISANCE = "NUISANCE"
    HEALTH = "HEALTH"
    EXIT = "EXIT"


class RemovalJobStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class SubscriptionPlan(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    PAID = "PAID"
    VOID = "VOID"


class CourseCode(str, Enum):
    HOST_101 = "HOST-101"
    ADV_201 = "ADV-201"
    QUEEN_301 = "QUEEN-301"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    SEVERE = "SEVERE"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    RESOLVED_AT_FAULT = "RESOLVED_AT_FAULT"
    RESOLVED_NO_FAULT = "RESOLVED_NO_FAULT"
    DISMISSED = "DISMISSED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    HOST = "Host"
    BEEKEEPER = "Beekeeper"
    APIARY_MANAGER = "ApiaryManager"
    PLATFORM_OPS = "PlatformOps"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Every resource carries id, created_at, updated_at, and
# version (PRD §2.4).
# ---------------------------------------------------------------------------


class Season(TypedDict, total=False):
    id: str
    name: str
    frost_date: str
    status: str
    opened_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Host(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    status: str
    waiver_signed_at: Optional[str]
    waiver_version: Optional[str]
    reputation_score: int
    honey_credit_kg: float
    balance_due_cents: int
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict, total=False):
    id: str
    host_id: str
    address: str
    base_capacity_hives: int
    effective_capacity_hives: int
    status: str
    water_source: bool
    setback_feet: int
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict, total=False):
    id: str
    host_id: str
    site_id: str
    term_start_date: str
    term_end_date: str
    host_share_base_bps: int
    pending_host_share_base_bps: Optional[int]
    liability_clause_version: Optional[str]
    status: str
    signed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hive(TypedDict, total=False):
    id: str
    site_id: str
    agreement_id: str
    parent_hive_id: Optional[str]
    source_swarm_event_id: Optional[str]
    installed_at: str
    lifecycle_status: str
    posture: str
    provisional_posture: str
    last_verified_inspection_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    hive_id: str
    recorded_by_id: str
    inspected_at: str
    mites_counted: int
    bees_sampled: int
    mite_load_per_100: float
    disease_flag: bool
    brood_score: int
    queen_seen: bool
    stores_kg: float
    status: str
    return_reason: Optional[str]
    verified_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Treatment(TypedDict, total=False):
    id: str
    hive_id: str
    product: str
    start_date: str
    end_date: str
    status: str
    withdrawal_end_date: str
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Harvest(TypedDict, total=False):
    id: str
    hive_id: str
    collected_on: str
    gross_kg: float
    moisture_pct: float
    net_kg: float
    status: str
    recorded_by_id: str
    approved_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HoneyAllocation(TypedDict, total=False):
    id: str
    season_id: str
    hive_id: str
    status: str
    projected_pool_net_kg: float
    projected_host_kg: float
    pool_net_kg: Optional[float]
    effective_bps: Optional[int]
    host_kg: Optional[float]
    reserve_kg: Optional[float]
    operator_kg: Optional[float]
    edu_bonus_kg: Optional[float]
    finalized_at: Optional[str]
    distributed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SwarmEvent(TypedDict, total=False):
    id: str
    site_id: str
    source_hive_id: Optional[str]
    reported_by_host_id: str
    reported_at: str
    status: str
    assigned_beekeeper_id: Optional[str]
    captured_hive_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemovalJob(TypedDict, total=False):
    id: str
    hive_id: str
    requested_by_host_id: str
    reason: str
    requested_at: str
    status: str
    decision_reason: Optional[str]
    scheduled_start: Optional[str]
    crew_id: Optional[str]
    cancellation_fee_cents: Optional[int]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    host_id: str
    plan: str
    monthly_fee_cents: int
    status: str
    pending_plan: Optional[str]
    projected_overwinter_credit_cents: int
    activated_at: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    subscription_id: str
    period_label: str
    fee_cents: int
    carried_balance_cents: int
    late_fee_cents: int
    overwinter_credit_cents: int
    total_cents: int
    status: str
    issued_at: str
    due_at: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    host_id: str
    course_code: str
    status: str
    quiz_score: Optional[int]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    site_id: str
    host_id: str
    reporter_id: str
    severity: str
    occurred_at: str
    description: str
    status: str
    liability_cents: int
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
