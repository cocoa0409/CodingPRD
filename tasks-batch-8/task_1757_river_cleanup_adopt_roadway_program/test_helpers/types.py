"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    GROUP_LEADER = "GroupLeader"


class AgreementStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RENEWAL_REVIEW = "RENEWAL_REVIEW"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    REJECTED = "REJECTED"


class AgreementStanding(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BRIEFING_DONE = "BRIEFING_DONE"
    POSTPONED = "POSTPONED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class WaiverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class SegmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ADOPTED = "ADOPTED"


class SegmentType(str, Enum):
    ROADWAY = "ROADWAY"
    RIVERBANK = "RIVERBANK"


class OrgType(str, Enum):
    CIVIC = "CIVIC"
    BUSINESS = "BUSINESS"
    SCHOOL = "SCHOOL"
    FAITH = "FAITH"
    OTHER = "OTHER"


class SupplyDistributionStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
    RECONCILED = "RECONCILED"


class HazardStatus(str, Enum):
    REPORTED = "REPORTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class HazardType(str, Enum):
    CHEMICAL_CONTAINER = "CHEMICAL_CONTAINER"
    SYRINGES = "SYRINGES"
    PROPANE_TANK = "PROPANE_TANK"
    ASBESTOS = "ASBESTOS"
    OTHER = "OTHER"


class SignStatus(str, Enum):
    REQUESTED = "REQUESTED"
    INSTALLED = "INSTALLED"
    REMOVED = "REMOVED"


class WeightMethod(str, Enum):
    MEASURED = "MEASURED"
    ESTIMATED = "ESTIMATED"


class MaterialType(str, Enum):
    GENERAL_TRASH = "GENERAL_TRASH"
    RECYCLABLES = "RECYCLABLES"
    METALS = "METALS"
    YARD_WASTE = "YARD_WASTE"
    OTHER = "OTHER"


# --- Entity TypedDicts (common_fields: true unless noted) ---


class AdopterGroup(TypedDict, total=False):
    id: str
    name: str
    org_type: str
    contact_name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class RoadSegment(TypedDict, total=False):
    id: str
    route_name: str
    mile_marker_start: float
    mile_marker_end: float
    mile_length: float
    segment_type: str
    water_adjacent: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AdoptionAgreement(TypedDict, total=False):
    id: str
    group_id: str
    segment_id: str
    contact_email: str
    special_instructions: Optional[str]
    status: str
    term_start_date: Optional[str]
    term_end_date: Optional[str]
    cleanups_completed_in_window: int
    standing: str
    renewal_count: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CleanupEvent(TypedDict, total=False):
    id: str
    agreement_id: str
    scheduled_date: str
    expected_volunteers: int
    status: str
    briefing_attendee_count: int
    postpone_count: int
    completed_weight_lbs: Optional[float]
    created_at: str
    updated_at: str
    version: int


class VolunteerWaiver(TypedDict, total=False):
    id: str
    agreement_id: str
    volunteer_full_name: str
    dob: str
    is_minor: bool
    guardian_full_name: Optional[str]
    guardian_consent: bool
    supervisor_waiver_id: Optional[str]
    status: str
    signed_date: str
    expiry_date: str
    created_at: str
    updated_at: str
    version: int


class SupplyDepot(TypedDict, total=False):
    id: str
    name: str
    bags_on_hand: int
    vests_on_hand: int
    grabbers_on_hand: int
    vests_pool_total: int
    grabbers_pool_total: int
    lost_vests_total: int
    lost_grabbers_total: int
    created_at: str
    updated_at: str
    version: int


class SupplyDistribution(TypedDict, total=False):
    id: str
    event_id: str
    depot_id: str
    status: str
    vests_issued: int
    grabbers_issued: int
    bags_issued: int
    vests_returned: int
    grabbers_returned: int
    lost_vests: int
    lost_grabbers: int
    created_at: str
    updated_at: str
    version: int


class MaterialLine(TypedDict, total=False):
    material_type: str
    bag_count: int
    line_weight_lbs: float


# DebrisReport carries ONLY id + created_at (common_fields: false per PRD §2.4).
class DebrisReport(TypedDict, total=False):
    id: str
    created_at: str
    event_id: str
    weight_method: str
    measured_total_weight_lbs: Optional[float]
    material_lines: List[MaterialLine]
    material_breakdown: List[MaterialLine]
    official_weight_lbs: float


class HazardReport(TypedDict, total=False):
    id: str
    segment_id: str
    event_id: Optional[str]
    hazard_type: str
    description: str
    location_note: str
    status: str
    agency_reference: Optional[str]
    acknowledged_at: Optional[str]
    resolved_at: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SignRecognition(TypedDict, total=False):
    id: str
    agreement_id: str
    sign_text: str
    status: str
    installed_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramMetrics(TypedDict, total=False):
    active_agreements: int
    adopted_miles: float
    available_miles: float
    total_debris_lbs: float
    completed_cleanups: int
    open_hazards: int
