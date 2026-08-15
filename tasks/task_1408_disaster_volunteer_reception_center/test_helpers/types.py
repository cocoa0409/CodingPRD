"""Domain types: entity TypedDicts, status enums, role enum.

All resources carry the common system-managed fields: id (server-minted UUID),
created_at, updated_at (ISO 8601 UTC, three fractional digits), and version
(integer, starts at 1, +1 per mutation).
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    VRC_MANAGER = "VRCManager"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    VETTING_OFFICER = "VettingOfficer"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    SITE_SUPERVISOR = "SiteSupervisor"
    RISK_OFFICER = "RiskOfficer"
    AGENCY_COORDINATOR = "AgencyCoordinator"
    VOLUNTEER = "Volunteer"


class IncidentLifecycleStatus(str, Enum):
    ACTIVATION = "ACTIVATION"
    ACTIVE = "ACTIVE"
    DEMOBILIZATION = "DEMOBILIZATION"
    CLOSED = "CLOSED"


class OperationalPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class VolunteerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    VETTING = "VETTING"
    CLEARED = "CLEARED"
    READY = "READY"
    DEPLOYED = "DEPLOYED"
    SUSPENDED = "SUSPENDED"
    DEMOBILIZED = "DEMOBILIZED"
    WITHDRAWN = "WITHDRAWN"
    REJECTED = "REJECTED"


class CredentialStatus(str, Enum):
    CLAIMED = "CLAIMED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class BackgroundCheckStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    EXPIRED = "EXPIRED"


class ClearanceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ClearanceType(str, Enum):
    SAFETY_BRIEFING = "SAFETY_BRIEFING"
    LIABILITY_WAIVER = "LIABILITY_WAIVER"


class SupportRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    MATCHING = "MATCHING"
    FILLED = "FILLED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN_FOR_ROSTER = "OPEN_FOR_ROSTER"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DECLINED = "DECLINED"
    NO_SHOW = "NO_SHOW"
    RECALLED = "RECALLED"


class AssignmentOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_MATCH = "AUTO_MATCH"


class TripStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class SeatBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    BOARDED = "BOARDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class PPEIssuanceStatus(str, Enum):
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    DAMAGED = "DAMAGED"
    LOST = "LOST"


class PPEItemType(str, Enum):
    GLOVES = "GLOVES"
    MASK = "MASK"
    HARD_HAT = "HARD_HAT"
    VEST = "VEST"
    GOGGLES = "GOGGLES"


class HourEntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    REJECTED_FINAL = "REJECTED_FINAL"


class RiskReportStatus(str, Enum):
    FILED = "FILED"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskCategory(str, Enum):
    SAFETY_VIOLATION = "SAFETY_VIOLATION"
    MISCONDUCT = "MISCONDUCT"
    NO_SHOW_PATTERN = "NO_SHOW_PATTERN"
    OTHER = "OTHER"


class SkillCode(str, Enum):
    GENERAL_LABOR = "GENERAL_LABOR"
    CHAINSAW = "CHAINSAW"
    MEDICAL = "MEDICAL"
    CDL = "CDL"
    SHELTER_OPS = "SHELTER_OPS"
    TRANSLATION = "TRANSLATION"


class CredentialClass(str, Enum):
    STANDARD = "STANDARD"
    ADVANCED = "ADVANCED"


class HazardLevel(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class Criticality(str, Enum):
    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"


class RecognitionTier(str, Enum):
    NONE = "NONE"
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class Incident(TypedDict, total=False):
    id: str
    name: str
    lifecycle_status: str
    operational_posture: str
    ppe_stock: dict
    provisional_cost_share_cents: int
    verified_cost_share_cents: int
    federal_share_cents: int
    state_share_cents: int
    local_share_cents: int
    activated_at: Optional[str]
    demobilized_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    incident_id: str
    full_name: str
    phone: str
    email: str
    home_locality: str
    status: str
    registered_by_user_id: str
    committed_hours: float
    verified_hours_total: float
    current_risk_score: int
    lifetime_risk_score: int
    recognition_tier: str
    demobilized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SkillCredential(TypedDict, total=False):
    id: str
    volunteer_id: str
    skill_code: str
    credential_class: str
    evidence_notes: Optional[str]
    expires_at: str
    status: str
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict, total=False):
    id: str
    volunteer_id: str
    status: str
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Clearance(TypedDict, total=False):
    id: str
    volunteer_id: str
    clearance_type: str
    status: str
    completed_at: str
    valid_until: Optional[str]
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupportRequest(TypedDict, total=False):
    id: str
    incident_id: str
    requesting_agency: str
    site_name: str
    required_skill: str
    min_credential_class: str
    headcount_needed: int
    criticality: str
    window_start: str
    window_end: str
    status: str
    filled_count: int
    created_at: str
    updated_at: str
    version: int


class SiteShift(TypedDict, total=False):
    id: str
    incident_id: str
    site_name: str
    hazard_level: str
    start_at: str
    end_at: str
    capacity: int
    duration_hours: float
    rostered_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeploymentAssignment(TypedDict, total=False):
    id: str
    incident_id: str
    volunteer_id: str
    support_request_id: str
    site_shift_id: str
    status: str
    origin: str
    checked_in_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransportTrip(TypedDict, total=False):
    id: str
    incident_id: str
    site_shift_id: str
    vehicle_id: str
    seat_capacity: int
    depart_at: str
    arrive_estimate_at: str
    booked_seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeatBooking(TypedDict, total=False):
    id: str
    trip_id: str
    assignment_id: str
    volunteer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PPEIssuance(TypedDict, total=False):
    id: str
    volunteer_id: str
    item_type: str
    quantity: int
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HourEntry(TypedDict, total=False):
    id: str
    assignment_id: str
    work_date: str
    hours: float
    status: str
    submitted_by_user_id: str
    verified_by_user_id: Optional[str]
    dispute_count: int
    resubmit_count: int
    dispute_reason: Optional[str]
    entry_value_cents: int
    created_at: str
    updated_at: str
    version: int


class RiskReport(TypedDict, total=False):
    id: str
    subject_volunteer_id: str
    reporter_user_id: str
    severity: str
    category: str
    description: str
    occurred_at: str
    status: str
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]
    points_awarded: Optional[int]
    created_at: str
    updated_at: str
    version: int
