"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    RAIL_SAFETY_OFFICER = "RailSafetyOfficer"
    LOCAL_AUTHORITY = "LocalAuthority"
    RAILROAD_MAINTAINER = "RailroadMaintainer"


class CrossingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSURE_PENDING = "CLOSURE_PENDING"
    CLOSED = "CLOSED"


class HighwayFunctionalClass(str, Enum):
    ARTERIAL = "ARTERIAL"
    COLLECTOR = "COLLECTOR"
    LOCAL = "LOCAL"


class WarningDeviceClass(str, Enum):
    PASSIVE_CROSSBUCK = "PASSIVE_CROSSBUCK"
    FLASHING_LIGHTS = "FLASHING_LIGHTS"
    GATES = "GATES"
    FOUR_QUADRANT_GATES = "FOUR_QUADRANT_GATES"


class DiagnosticReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    RECOMMENDATIONS_ISSUED = "RECOMMENDATIONS_ISSUED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class RecommendationCode(str, Enum):
    UPGRADE_DEVICES = "UPGRADE_DEVICES"
    CLOSE_CROSSING = "CLOSE_CROSSING"
    CONSOLIDATE = "CONSOLIDATE"
    INSTALL_PREEMPTION = "INSTALL_PREEMPTION"
    NO_ACTION = "NO_ACTION"


class IncidentSeverity(str, Enum):
    CASUALTY = "CASUALTY"
    INJURY = "INJURY"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    NEAR_MISS = "NEAR_MISS"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    SCREENED = "SCREENED"
    FIELD_INVESTIGATION = "FIELD_INVESTIGATION"
    DESK_REVIEW = "DESK_REVIEW"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    FRA_SUBMITTED = "FRA_SUBMITTED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"


class InvestigationTrack(str, Enum):
    FIELD_INVESTIGATION = "FIELD_INVESTIGATION"
    DESK_REVIEW = "DESK_REVIEW"


class FundingProgramStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATION_LOCKED = "ALLOCATION_LOCKED"
    CLOSED = "CLOSED"


class AllocationMethod(str, Enum):
    WATERFALL_BY_RANK = "WATERFALL_BY_RANK"
    PROPORTIONAL_SHARE = "PROPORTIONAL_SHARE"


class UpgradeProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ELIGIBLE = "ELIGIBLE"
    SELECTED = "SELECTED"
    AWARDED = "AWARDED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class ClosureAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    DOT_ACCEPTED = "DOT_ACCEPTED"
    LOCALITY_RATIFIED = "LOCALITY_RATIFIED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ClosureType(str, Enum):
    CLOSURE = "CLOSURE"
    CONSOLIDATION = "CONSOLIDATION"


class NegotiatingParty(str, Enum):
    DOT = "DOT"
    LOCALITY = "LOCALITY"


class QuietZoneStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    SUPPLEMENT_REQUIRED = "SUPPLEMENT_REQUIRED"
    REJECTED = "REJECTED"
    EFFECTIVE = "EFFECTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class SsmCode(str, Enum):
    FOUR_QUADRANT_GATES = "FOUR_QUADRANT_GATES"
    MEDIANS = "MEDIANS"
    CHANNELIZATION = "CHANNELIZATION"
    ONE_WAY_STREET = "ONE_WAY_STREET"
    WAYSIDE_HORN = "WAYSIDE_HORN"


class MembershipStatus(str, Enum):
    MEMBER = "MEMBER"
    REMOVED = "REMOVED"


class MaintenanceCategory(str, Enum):
    SIGNAL = "SIGNAL"
    SURFACE = "SURFACE"
    VEGETATION = "VEGETATION"
    STRIPING = "STRIPING"


class ResponsibleParty(str, Enum):
    RAILROAD = "RAILROAD"
    ROAD_AUTHORITY = "ROAD_AUTHORITY"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class WorkOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    FLAGGING_CONFIRMED = "FLAGGING_CONFIRMED"
    IN_WORK = "IN_WORK"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InterconnectionStatus(str, Enum):
    DRAFT = "DRAFT"
    TIMING_VERIFIED = "TIMING_VERIFIED"
    COMMISSIONED = "COMMISSIONED"
    DECOMMISSIONED = "DECOMMISSIONED"


# --- Entity TypedDicts (PRD §2.4: common system-managed fields) ---
# Primary resources carry id + created_at + updated_at + version.
# Locality and QuietZoneCrossing carry ONLY id + created_at (PRD §2.4 exception).

class Crossing(TypedDict, total=False):
    id: str
    dot_crossing_number: str
    railroad_code: str
    road_authority_locality_id: str
    highway_functional_class: str
    annual_train_count: int
    train_speed_max_mph: int
    aadt: int
    school_bus_count: int
    sight_distance_rating: int
    warning_device_class: str
    status: str
    exposure_index: float
    projected_exposure_index: float
    incident_count_5yr: int
    hazard_score: float
    diagnostic_review_due: bool
    created_at: str
    updated_at: str
    version: int


class Locality(TypedDict, total=False):
    id: str
    locality_name: str
    state_code: str
    contact_email: str
    created_at: str
    # PRD §2.4: no updated_at, no version on this resource


class DiagnosticTeam(TypedDict, total=False):
    id: str
    team_name: str
    lead_agency: str
    created_at: str
    updated_at: str
    version: int


class DiagnosticReview(TypedDict, total=False):
    id: str
    crossing_id: str
    team_id: str
    scheduled_date: str
    status: str
    recommendations: List[str]
    accepted_at: Optional[str]
    superseded_by_review_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    crossing_id: str
    occurred_at: str
    severity: str
    fatalities: int
    injuries: int
    property_damage_cents: int
    train_speed_at_impact_mph: Optional[int]
    narrative: Optional[str]
    fra_reportable: bool
    investigation_track: Optional[str]
    findings_summary: Optional[str]
    warning_devices_functioning: Optional[bool]
    fra_submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingProgram(TypedDict, total=False):
    id: str
    fiscal_year: int
    apportionment_cents: int
    allocation_method: str
    status: str
    available_cents: int
    encumbered_cents: int
    eligible_demand_cents: int
    created_at: str
    updated_at: str
    version: int


class UpgradeProject(TypedDict, total=False):
    id: str
    crossing_id: str
    program_id: str
    target_device_class: str
    estimated_cost_cents: int
    priority_score: Optional[float]
    score_stale: bool
    tentative_award_cents: Optional[int]
    awarded_cents: Optional[int]
    federal_share_cents: Optional[int]
    state_share_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosureAgreement(TypedDict, total=False):
    id: str
    crossing_id: str
    locality_id: str
    closure_type: str
    consolidation_target_crossing_id: Optional[str]
    computed_incentive_cents: int
    current_offer_cents: int
    negotiation_round: int
    created_by_party: str
    created_by_user_id: str
    last_offer_by_party: str
    last_offer_by_user_id: str
    dot_accepted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QuietZoneApplication(TypedDict, total=False):
    id: str
    locality_id: str
    notes: Optional[str]
    riwh_pre_ssm: Optional[float]
    riwh_post_ssm: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class QuietZoneCrossing(TypedDict, total=False):
    id: str
    quiet_zone_application_id: str
    crossing_id: str
    ssm_codes: List[str]
    membership_status: str
    created_at: str
    # PRD §2.4: no updated_at, no version on this resource


class MaintenanceResponsibilityAssignment(TypedDict, total=False):
    id: str
    crossing_id: str
    category: str
    responsible_party: str
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWorkOrder(TypedDict, total=False):
    id: str
    crossing_id: str
    category: str
    window_start: str
    window_end: str
    fouls_track: bool
    flagging_vendor: Optional[str]
    responsible_party: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PreemptionInterconnection(TypedDict, total=False):
    id: str
    crossing_id: str
    traffic_signal_ref: str
    track_approach_distance_ft: int
    design_train_speed_mph: int
    clear_storage_distance_ft: int
    advance_preemption_seconds: int
    track_clearance_green_seconds: int
    approach_seconds: int
    required_clearance_green_seconds: int
    required_advance_preemption_seconds: int
    timing_check_pass: bool
    status: str
    created_at: str
    updated_at: str
    version: int
