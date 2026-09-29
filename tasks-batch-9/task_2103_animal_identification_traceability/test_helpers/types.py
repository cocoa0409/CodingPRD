"""Domain types for the Animal ID Traceability API: entity TypedDicts, status enums, roles."""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PRODUCER = "Producer"
    STATE_ANIMAL_HEALTH_OFFICIAL = "StateAnimalHealthOfficial"
    FEDERAL_TRACE_ANALYST = "FederalTraceAnalyst"
    DEVICE_SUPPLIER_REP = "DeviceSupplierRep"
    HARVEST_FACILITY_OPERATOR = "HarvestFacilityOperator"
    PROGRAM_ADMIN = "ProgramAdmin"


ALL_ROLE_NAMES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class PrivacyLevel(str, Enum):
    STANDARD = "STANDARD"
    RESTRICTED = "RESTRICTED"


class EnrollmentStatus(str, Enum):
    NOT_ENROLLED = "NOT_ENROLLED"
    ENROLLED = "ENROLLED"
    LAPSED = "LAPSED"


class IncentiveTier(str, Enum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class OperationType(str, Enum):
    COW_CALF = "COW_CALF"
    FEEDLOT = "FEEDLOT"
    MARKET = "MARKET"
    HARVEST_FACILITY = "HARVEST_FACILITY"


class RegistrationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class HealthStatus(str, Enum):
    CLEAR = "CLEAR"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    QUARANTINED = "QUARANTINED"


class SupplierStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class TagLotStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    RECALLED = "RECALLED"
    VOIDED = "VOIDED"


class DeviceStatus(str, Enum):
    APPLIED = "APPLIED"
    RETIRED = "RETIRED"
    REPLACED = "REPLACED"
    VOIDED = "VOIDED"


class Species(str, Enum):
    BOVINE = "BOVINE"
    OVINE = "OVINE"
    CAPRINE = "CAPRINE"
    CERVID = "CERVID"


class LifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IN_TRANSIT = "IN_TRANSIT"
    HARVESTED = "HARVESTED"
    VOIDED = "VOIDED"


class TraceStatus(str, Enum):
    NORMAL = "NORMAL"
    TRACE_HIT = "TRACE_HIT"
    CLEARED = "CLEARED"


class SightingType(str, Enum):
    TAG_APPLIED = "TAG_APPLIED"
    DEPARTURE = "DEPARTURE"
    ARRIVAL = "ARRIVAL"
    HARVEST = "HARVEST"


class MovementStatus(str, Enum):
    REPORTED = "REPORTED"
    RECEIVED = "RECEIVED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class PathogenClass(str, Enum):
    DIRECT_CONTACT = "DIRECT_CONTACT"
    ENVIRONMENTAL = "ENVIRONMENTAL"


class TraceDirection(str, Enum):
    BACKWARD = "BACKWARD"
    FORWARD = "FORWARD"
    BOTH = "BOTH"


class TraceRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ScopeVariant(str, Enum):
    STRICT_INTERVAL = "STRICT_INTERVAL"
    PREMISES_WINDOW = "PREMISES_WINDOW"


class HoldOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    UNDER_APPEAL = "UNDER_APPEAL"
    RELEASED = "RELEASED"


class ReconciliationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    VARIANCE_FLAGGED = "VARIANCE_FLAGGED"
    SUPERSEDED = "SUPERSEDED"


class ReconciliationBasis(str, Enum):
    AS_ISSUED = "AS_ISSUED"
    AS_SIGHTED = "AS_SIGHTED"


class AwardStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"


# --------------------------------------------------------------------------
# Entity shapes
#
# Every persisted record carries id + created_at. Records that are mutable
# additionally carry updated_at and version. A Sighting is an immutable
# observation and therefore carries neither.
# --------------------------------------------------------------------------
class Producer(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    state_code: str
    privacy_level: str
    enrollment_status: str
    enrolled_at: Optional[str]
    enrolled_head_count: int
    incentive_tier: str
    on_time_movement_pct: float
    incentive_balance_cents: int
    lifetime_clawback_cents: int
    created_at: str
    updated_at: str
    version: int


class Premises(TypedDict):
    id: str
    producer_id: str
    pin: str
    operation_type: str
    state_code: str
    capacity: int
    registration_status: str
    health_status: str
    animal_count: int
    pending_hold_count: int
    last_hold_released_at: Optional[str]
    last_reconciliation_run_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeviceSupplier(TypedDict):
    id: str
    company_name: str
    supplier_code: str
    aid_prefix: str
    status: str
    registered_by_user_id: str
    approved_by_user_id: Optional[str]
    defect_report_count: int
    issued_tag_count: int
    retired_tag_count: int
    retired_returned_count: int
    conformance_score: float
    probation: bool
    issuance_cap: int
    created_at: str
    updated_at: str
    version: int


class TagLot(TypedDict):
    id: str
    supplier_id: str
    premises_id: str
    serial_start: int
    serial_end: int
    quantity: int
    status: str
    applied_count: int
    retired_count: int
    replaced_count: int
    voided_count: int
    unapplied_count: int
    fee_cents: int
    discount_pct_applied: float
    surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class Tag(TypedDict):
    id: str
    tag_lot_id: str
    ain: str
    animal_id: Optional[str]
    replaces_tag_id: Optional[str]
    device_status: str
    applied_at: str
    retired_at: Optional[str]
    tag_returned: Optional[bool]
    carcass_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Animal(TypedDict):
    id: str
    ain: str
    species: str
    birth_date: str
    birth_premises_id: str
    current_premises_id: Optional[str]
    lifecycle_status: str
    trace_status: str
    sighting_count: int
    last_sequence_no: int
    created_at: str
    updated_at: str
    version: int


class Sighting(TypedDict):
    """Immutable observation: carries only id and created_at as common fields."""
    id: str
    animal_id: str
    premises_id: str
    source_movement_id: Optional[str]
    sighting_type: str
    observed_at: str
    sequence_no: int
    reversed: bool
    created_at: str


class MovementEvent(TypedDict):
    id: str
    animal_id: str
    origin_premises_id: str
    destination_premises_id: str
    departed_at: str
    arrived_at: Optional[str]
    reported_at: str
    icvi_number: Optional[str]
    interstate: bool
    status: str
    reporting_lag_hours: float
    on_time: bool
    correction_count: int
    created_at: str
    updated_at: str
    version: int


class TraceHit(TypedDict):
    animal_id: str
    premises_id: str
    hop_depth: int
    first_contact_at: str
    responded: bool
    resolved: bool


class TraceRequest(TypedDict):
    id: str
    index_animal_id: str
    pathogen_class: str
    direction: str
    lookback_days: int
    max_hops: int
    status: str
    opened_by_user_id: str
    closed_by_user_id: Optional[str]
    opened_at: str
    closed_at: Optional[str]
    variant_applied: Optional[str]
    hits: List[TraceHit]
    hit_count: int
    premises_touched_count: int
    hops_total: int
    hops_unreachable: int
    elapsed_hours: Optional[float]
    completeness_score: Optional[float]
    trace_goal_met: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class HoldOrder(TypedDict):
    id: str
    premises_id: str
    trace_request_id: Optional[str]
    effective_from: str
    effective_until: str
    status: str
    issued_by_user_id: str
    appeal_count: int
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReconciliationRun(TypedDict):
    id: str
    premises_id: str
    period_start: str
    period_end: str
    physical_unapplied_count: Optional[int]
    basis: Optional[str]
    book_unapplied_count: Optional[int]
    variance_count: Optional[int]
    variance_pct: Optional[float]
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AwardLineItem(TypedDict):
    premises_id: str
    animal_count: int
    line_cents: int


class IncentiveAward(TypedDict):
    id: str
    producer_id: str
    period_start: str
    period_end: str
    head_count_snapshot: int
    tier_factor: float
    compliance_multiplier: float
    line_items: List[AwardLineItem]
    awarded_cents: int
    clawback_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
