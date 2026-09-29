"""Domain types for the Manufactured Home Transport & Set API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  A marriage joint is an append-only measurement event: it
carries ``id`` and ``created_at`` only, with no ``updated_at`` and no
``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    PLANT_DISPATCHER = "PlantDispatcher"
    TRANSPORT_MANAGER = "TransportManager"
    PERMIT_DESK = "PermitDesk"
    SET_CREW_LEAD = "SetCrewLead"
    INSTALLATION_INSPECTOR = "InstallationInspector"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class PlantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"


class HaulerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EscortCrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OVERBOOKED = "OVERBOOKED"


class SetCrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LICENSE_EXPIRED = "LICENSE_EXPIRED"


class OrderPosture(str, Enum):
    OPEN = "OPEN"
    TRANSPORT_BLOCKED = "TRANSPORT_BLOCKED"
    SET_IN_PROGRESS = "SET_IN_PROGRESS"
    SITE_BLOCKED = "SITE_BLOCKED"
    CLOSED = "CLOSED"


class SectionTransitStatus(str, Enum):
    AT_PLANT = "AT_PLANT"
    MEASURED = "MEASURED"
    PERMIT_PENDING = "PERMIT_PENDING"
    DISPATCH_READY = "DISPATCH_READY"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    PERMIT_REVOKED_HOLD = "PERMIT_REVOKED_HOLD"
    DAMAGED_HOLD = "DAMAGED_HOLD"


class SiteReadinessStatus(str, Enum):
    READINESS_PENDING = "READINESS_PENDING"
    READINESS_FAILED = "READINESS_FAILED"
    READY = "READY"


class PadType(str, Enum):
    SLAB = "SLAB"
    RUNNER = "RUNNER"
    CROSSING_BEAM = "CROSSING_BEAM"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FEE_PAID = "FEE_PAID"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class PermitClass(str, Enum):
    STANDARD = "STANDARD"
    OVERSIZE = "OVERSIZE"
    SUPERLOAD = "SUPERLOAD"


class RouteLegStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_TRANSIT = "IN_TRANSIT"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"
    HAULER_HOLD = "HAULER_HOLD"


class EscortAssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class EscortRole(str, Enum):
    ESCORT = "ESCORT"
    PILOT_CAR = "PILOT_CAR"


class SetJobProgressStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    SET_COMPLETE = "SET_COMPLETE"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class SetJobScopeStatus(str, Enum):
    SCOPE_PENDING = "SCOPE_PENDING"
    SCOPE_SPLIT = "SCOPE_SPLIT"
    SCOPE_DELIVERED = "SCOPE_DELIVERED"


class ClosureStatus(str, Enum):
    NOT_ASSESSED = "NOT_ASSESSED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PASS = "PASS"
    FAIL = "FAIL"


class FinalResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    PUNCH_LIST = "PUNCH_LIST"


class ScopeOwner(str, Enum):
    DEALER = "DEALER"
    INSTALLER = "INSTALLER"


class AnchorCertificationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUIRED = "CHANGES_REQUIRED"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class AnchorReviewDecision(str, Enum):
    CERTIFY = "CERTIFY"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    FAIL = "FAIL"


class DamageClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DISPUTED = "DISPUTED"
    ADJUDICATED = "ADJUDICATED"
    REVERSED = "REVERSED"


class DiscoveredStage(str, Enum):
    PLANT_QC = "PLANT_QC"
    IN_TRANSIT = "IN_TRANSIT"
    AT_SET = "AT_SET"
    FINAL_INSPECTION = "FINAL_INSPECTION"
    UNKNOWN = "UNKNOWN"


class AllocationBasis(str, Enum):
    STAGE = "STAGE"
    EVIDENCE = "EVIDENCE"


class WindZone(str, Enum):
    ZONE_I = "I"
    ZONE_II = "II"
    ZONE_III = "III"


class EndorsementClass(str, Enum):
    STANDARD = "STANDARD"
    OVERSIZE = "OVERSIZE"
    SUPERLOAD = "SUPERLOAD"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class Plant(TypedDict):
    id: str
    name: str
    state_code: str
    hud_plant_code: str
    chargeback_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Hauler(TypedDict):
    id: str
    name: str
    dot_number: str
    insurance_expiry_date: str
    endorsed_states: List[str]
    chargeback_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EscortCrew(TypedDict):
    id: str
    vendor_name: str
    endorsed_states: List[str]
    certified_roles: List[str]
    endorsement_class: str
    buffer_minutes: int
    max_reserved_minutes: int
    reserved_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SetCrew(TypedDict):
    id: str
    company_name: str
    hud_installer_license_no: str
    license_state: str
    license_expiry_date: str
    daily_capacity: int
    chargeback_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallationOrder(TypedDict):
    id: str
    plant_id: str
    dealer_name: str
    home_model: str
    section_count: int
    destination_state: str
    wind_zone: str
    posture: str
    warranty_start_date: Optional[str]
    invoice_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class HomeSection(TypedDict):
    id: str
    order_id: str
    section_index: int
    declared_width_in: int
    declared_height_in: int
    declared_length_in: int
    declared_weight_lb: int
    measured_width_in: Optional[int]
    measured_height_in: Optional[int]
    mates_to_section_id: Optional[str]
    transit_status: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    order_id: str
    pad_type: str
    pier_plan_ref: str
    pier_count: int
    utility_water: bool
    utility_sewer: bool
    utility_electric: bool
    readiness_status: str
    inspection_round: int
    blocking_defect_count: int
    last_inspector_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransportPermit(TypedDict):
    id: str
    section_id: str
    state_code: str
    planned_leg_count: int
    night_move: bool
    permit_class: str
    escort_count_required: int
    pilot_car_required: bool
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    paid_amount_cents: int
    valid_until_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteLeg(TypedDict):
    id: str
    permit_id: str
    hauler_id: str
    sequence_no: int
    corridor_id: str
    state_code: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EscortAssignment(TypedDict):
    id: str
    route_leg_id: str
    escort_crew_id: str
    role: str
    window_start: str
    window_end: str
    reserved_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SetJob(TypedDict):
    id: str
    order_id: str
    set_crew_id: str
    scheduled_start_date: str
    scheduled_end_date: str
    labor_base_cents: int
    progress_status: str
    scope_status: str
    skirting_owner: Optional[str]
    steps_owner: Optional[str]
    skirting_linear_ft: Optional[float]
    steps_count: Optional[int]
    skirting_fee_cents: Optional[int]
    steps_fee_cents: Optional[int]
    crossover_count: Optional[int]
    crossover_fee_cents: Optional[int]
    crossover_recorded: bool
    closure_score: Optional[float]
    closure_status: str
    final_result: str
    final_inspector_user_id: Optional[str]
    invoice_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# A marriage joint carries id and created_at only — no updated_at, no version.
class MarriageJoint(TypedDict):
    id: str
    set_job_id: str
    joint_index: int
    gap_in: float
    vertical_offset_in: float
    ridge_beam_shim_in: float
    deviation_score: float
    created_at: str


class AnchorCertification(TypedDict):
    id: str
    set_job_id: str
    anchor_count: int
    avg_torque_ft_lb: float
    strap_count: int
    pier_count: int
    hud_pass: bool
    state_pass: bool
    revision_round: int
    status: str
    certifier_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    order_id: str
    section_id: str
    hauler_id: str
    set_crew_id: str
    discovered_stage: str
    claimed_amount_cents: int
    blocks_set: bool
    plant_evidence_points: int
    hauler_evidence_points: int
    installer_evidence_points: int
    allocation_basis: Optional[str]
    approved_amount_cents: Optional[int]
    plant_charge_cents: int
    hauler_charge_cents: int
    installer_charge_cents: int
    dispute_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderSummary(TypedDict):
    order_id: str
    posture: str
    section_count_declared: int
    section_count_actual: int
    sections_delivered_count: int
    sections_on_hold_count: int
    site_readiness_status: Optional[str]
    issued_permit_count: int
    open_claim_count: int
    network_chargeback_cents: int
    invoice_total_cents: Optional[int]
