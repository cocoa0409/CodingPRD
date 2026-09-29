"""Domain types for the Conveyor Integration Delivery API.

Entity TypedDicts, status/enum vocabularies and the role enum, all named exactly
as the PRD names them. Envelope types are supplied by the test framework.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROJECT_DIRECTOR = "ProjectDirector"
    DESIGN_ENGINEER = "DesignEngineer"
    SHOP_SUPERVISOR = "ShopSupervisor"
    SITE_MANAGER = "SiteManager"
    CUSTOMER_REP = "CustomerRep"


# ---------------------------------------------------------------------------
# Enumerated vocabularies
# ---------------------------------------------------------------------------
class DeliveryStatus(str, Enum):
    """Project.delivery_status (PRD §2.5)."""

    DESIGN = "DESIGN"
    DESIGN_FROZEN = "DESIGN_FROZEN"
    IN_FABRICATION = "IN_FABRICATION"
    REBASELINE_REQUIRED = "REBASELINE_REQUIRED"
    CUTOVER = "CUTOVER"
    COMMISSIONING = "COMMISSIONING"
    ACCEPTED = "ACCEPTED"


class CommercialStatus(str, Enum):
    """Project.commercial_status (PRD §2.5)."""

    CLEAN = "CLEAN"
    CHANGE_PENDING = "CHANGE_PENDING"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class ServiceTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"
    CRITICAL = "CRITICAL"


class EquipmentClass(str, Enum):
    BELT = "BELT"
    ROLLER = "ROLLER"
    SORTATION = "SORTATION"
    MERGE = "MERGE"


class SimulationMethod(str, Enum):
    DETERMINISTIC_STEADY_STATE = "DETERMINISTIC_STEADY_STATE"
    DEGRADED_AVAILABILITY = "DEGRADED_AVAILABILITY"


class SimulationRunStatus(str, Enum):
    COMPLETE = "COMPLETE"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class FabricationLotStatus(str, Enum):
    PLANNED = "PLANNED"
    FABRICATING = "FABRICATING"
    STAGED = "STAGED"
    FAT_PASSED = "FAT_PASSED"
    FAT_FAILED = "FAT_FAILED"
    HOLD = "HOLD"
    INSTALLED = "INSTALLED"
    SCRAPPED = "SCRAPPED"


class FatResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ZoneOpsStatus(str, Enum):
    LIVE_LEGACY = "LIVE_LEGACY"
    CUTOVER_IN_PROGRESS = "CUTOVER_IN_PROGRESS"
    CUTOVER_COMPLETE = "CUTOVER_COMPLETE"


class CutoverWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BLOCKED_STALE_DESIGN = "BLOCKED_STALE_DESIGN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    CANCELLED_LOT_SCRAPPED = "CANCELLED_LOT_SCRAPPED"


class RampVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    UPHELD = "UPHELD"
    REVISED = "REVISED"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ChangeOrderDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"


class SpareCriticality(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class SparePartLineStatus(str, Enum):
    DRAFT = "DRAFT"
    ALLOCATED = "ALLOCATED"
    PARTIAL = "PARTIAL"
    UNFUNDED = "UNFUNDED"


class DamagesBasis(str, Enum):
    NAMEPLATE = "NAMEPLATE"
    OBSERVED_AVAILABILITY = "OBSERVED_AVAILABILITY"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_CREDITED = "RESOLVED_CREDITED"


# ---------------------------------------------------------------------------
# Entities that carry the full common field set:
# id + created_at + updated_at + version (PRD §2.4)
# ---------------------------------------------------------------------------
class Project(TypedDict):
    id: str
    customer_name: str
    facility_code: str
    customer_rep_user_id: str
    required_throughput_cph: int
    contract_base_cents: int
    authorized_ceiling_cents: int
    escalation_fee_cents: int
    contract_value_cents: int
    spares_budget_cents: int
    spares_allocated_cents: int
    spares_unallocated_cents: int
    service_tier: str
    response_sla_minutes: int
    design_version: int
    delivery_status: str
    commercial_status: str
    legacy_share_bps: int
    in_transition_share_bps: int
    cutover_share_bps: int
    design_frozen_at: Optional[str]
    acceptance_ready: bool
    created_at: str
    updated_at: str
    version: int


class ConveyorSegment(TypedDict):
    id: str
    project_id: str
    segment_code: str
    equipment_class: str
    rated_capacity_cph: int
    availability_pct: int
    source_share_bps: Optional[int]
    inbound_link_count: int
    outbound_link_count: int
    flow_share_bps: int
    derated_capacity_cph: int
    created_at: str
    updated_at: str
    version: int


class SimulationRun(TypedDict):
    id: str
    project_id: str
    method: str
    design_version_at_run: int
    effective_throughput_cph: int
    bottleneck_segment_code: str
    bottleneck_availability_pct: int
    shortfall_cph: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StagingBay(TypedDict):
    id: str
    bay_code: str
    concurrent_capacity: int
    created_at: str
    updated_at: str
    version: int


class FabricationLot(TypedDict):
    id: str
    project_id: str
    staging_bay_id: str
    lot_code: str
    segment_codes: List[str]
    occupancy_start_utc: str
    occupancy_end_utc: str
    fat_target_cph: int
    fat_attempt_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SiteZone(TypedDict):
    id: str
    project_id: str
    zone_code: str
    throughput_share_bps: int
    protected_shift_start_minute: int
    protected_shift_end_minute: int
    buffer_minutes: int
    ops_status: str
    created_at: str
    updated_at: str
    version: int


class CutoverWindow(TypedDict):
    id: str
    project_id: str
    site_zone_id: str
    fabrication_lot_id: str
    start_utc: str
    end_utc: str
    status: str
    abort_reason: Optional[str]
    started_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AcceptanceCertificate(TypedDict):
    id: str
    project_id: str
    accepted_throughput_cph: int
    bottleneck_availability_pct: int
    retention_amount_cents: int
    retention_release_cents: int
    issued_by_user_id: str
    dispute_deadline_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict):
    id: str
    project_id: str
    title: str
    scope_delta_cph: int
    price_delta_cents: int
    schedule_delta_days: int
    round_no: int
    decision_comment: Optional[str]
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SparePartLine(TypedDict):
    id: str
    project_id: str
    part_no: str
    criticality: str
    unit_cost_cents: int
    min_stock_qty: int
    lead_time_days: int
    requested_cents: int
    weighted_target_cents: int
    allocated_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceDispute(TypedDict):
    id: str
    acceptance_certificate_id: str
    claimed_cph: int
    damages_basis: str
    provisional_nameplate_cents: int
    provisional_observed_cents: int
    bound_provisional_cents: int
    retest_measured_cph: Optional[int]
    final_damages_cents: Optional[int]
    sla_credit_cents: Optional[int]
    filed_by_user_id: str
    retest_by_user_id: Optional[str]
    retest_recorded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only record types: only id + created_at, never updated_at/version
# (PRD §2.4 — flow links, factory acceptance tests, commissioning ramp steps)
# ---------------------------------------------------------------------------
class FlowLink(TypedDict):
    id: str
    project_id: str
    from_segment_id: str
    to_segment_id: str
    split_share_bps: int
    created_at: str


class FatTest(TypedDict):
    id: str
    fabrication_lot_id: str
    attempt_no: int
    measured_cph: int
    defect_count: int
    target_cph_at_test: int
    result: str
    created_at: str


class CommissioningRamp(TypedDict):
    id: str
    project_id: str
    step_pct: int
    measured_cph: int
    sustained_minutes: int
    target_cph: int
    min_sustained_minutes: int
    verdict: str
    recorded_by_user_id: str
    created_at: str


APPEND_ONLY_ENTITIES = ("FlowLink", "FatTest", "CommissioningRamp")
