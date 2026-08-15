"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    CLUB_ADMIN = "ClubAdmin"
    MEMBER = "Member"
    NET_CONTROL = "NetControl"
    EMERGENCY_COORDINATOR = "EmergencyCoordinator"
    EXAM_LIAISON = "ExamLiaison"


class LicenseClass(str, Enum):
    TECHNICIAN = "TECHNICIAN"
    GENERAL = "GENERAL"
    EXTRA = "EXTRA"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    SUSPENDED = "SUSPENDED"


class EquipmentPrivilege(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    SUSPENDED = "SUSPENDED"


class ReadinessTier(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    PROVISIONAL = "PROVISIONAL"
    INELIGIBLE = "INELIGIBLE"


class SiteAgreementStatus(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class RepeaterStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    MAINTENANCE = "MAINTENANCE"
    OFFLINE = "OFFLINE"


class CoordinationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    GRANTED = "GRANTED"
    RETURNED = "RETURNED"
    WITHDRAWN = "WITHDRAWN"


class NetStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ServedAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class ActivationStatus(str, Enum):
    STANDBY = "STANDBY"
    ACTIVATED = "ACTIVATED"
    DEMOBILIZED = "DEMOBILIZED"
    CANCELLED = "CANCELLED"


class StaffingPosture(str, Enum):
    UNDERSTAFFED = "UNDERSTAFFED"
    ADEQUATE = "ADEQUATE"


class RosterEntryStatus(str, Enum):
    VOLUNTEERED = "VOLUNTEERED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"
    NO_SHOW = "NO_SHOW"


class DrillStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DrillMessageStatus(str, Enum):
    ORIGINATED = "ORIGINATED"
    RELAYED = "RELAYED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class Precedence(str, Enum):
    ROUTINE = "ROUTINE"
    PRIORITY = "PRIORITY"
    EMERGENCY = "EMERGENCY"


class FieldDayEventStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    SCORING = "SCORING"
    FINALIZED = "FINALIZED"


class Band(str, Enum):
    B160M = "B160M"
    B80M = "B80M"
    B40M = "B40M"
    B20M = "B20M"
    B15M = "B15M"
    B10M = "B10M"
    B6M = "B6M"
    B2M = "B2M"


class Mode(str, Enum):
    CW = "CW"
    PHONE = "PHONE"
    DIGITAL = "DIGITAL"


class PowerCategory(str, Enum):
    QRP = "QRP"
    LOW = "LOW"
    HIGH = "HIGH"


class ExamSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ExamCandidateStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    PASSED = "PASSED"
    FAILED = "FAILED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    LOST = "LOST"


class ReturnCondition(str, Enum):
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"


class Member(TypedDict, total=False):
    id: str
    callsign: str
    full_name: str
    license_class: str
    license_expires_at: str
    membership_status: str
    dues_paid_through: Optional[str]
    equipment_privilege: str
    readiness_score: int
    readiness_score_optimistic: int
    readiness_tier: str
    check_ins_12m_count: int
    drills_12m_count: int
    no_shows_12m_count: int
    created_at: str
    updated_at: str
    version: int


class AntennaSiteAgreement(TypedDict):
    id: str
    site_name: str
    owner_name: str
    lease_start: str
    lease_end: str
    status: str
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class Repeater(TypedDict):
    id: str
    callsign: str
    output_frequency_mhz: float
    site_agreement_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CoordinationRequest(TypedDict, total=False):
    id: str
    repeater_id: str
    requested_frequency_mhz: float
    status: str
    council_reference: Optional[str]
    revision_number: int
    submitted_at: Optional[str]
    decision_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NetSession(TypedDict):
    id: str
    name: str
    repeater_id: str
    net_control_member_id: str
    scheduled_start: str
    scheduled_end: str
    min_license_class: str
    status: str
    checkin_count: int
    created_at: str
    updated_at: str
    version: int


class CheckIn(TypedDict):
    # Immutable record: carries ONLY id + created_at as common fields
    # (no updated_at, no version) per PRD §2.4.
    id: str
    net_session_id: str
    member_id: str
    has_traffic: bool
    traffic_count: int
    checked_in_at: str
    created_at: str


class ServedAgencyAgreement(TypedDict):
    id: str
    agency_name: str
    max_operators: int
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EmergencyActivation(TypedDict, total=False):
    id: str
    agreement_id: str
    title: str
    required_operators: int
    status: str
    activated_by_member_id: Optional[str]
    activated_at: Optional[str]
    demobilized_at: Optional[str]
    confirmed_count: int
    staffing_posture: str
    created_at: str
    updated_at: str
    version: int


class RosterEntry(TypedDict, total=False):
    id: str
    activation_id: str
    member_id: str
    status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Drill(TypedDict):
    id: str
    title: str
    scheduled_start: str
    scheduled_end: str
    passing_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DrillMessage(TypedDict, total=False):
    id: str
    drill_id: str
    originator_member_id: str
    precedence: str
    relay_count: int
    status: str
    delivered_at: Optional[str]
    handling_seconds: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FieldDayEvent(TypedDict):
    id: str
    name: str
    start_at: str
    end_at: str
    status: str
    contact_count: int
    provisional_score: int
    final_score: int
    created_at: str
    updated_at: str
    version: int


class FieldDayContact(TypedDict):
    id: str
    event_id: str
    operator_member_id: str
    worked_callsign: str
    band: str
    mode: str
    power_category: str
    is_duplicate: bool
    points: int
    created_at: str
    updated_at: str
    version: int


class ExamSession(TypedDict):
    id: str
    location: str
    scheduled_at: str
    max_candidates: int
    status: str
    registered_count: int
    created_at: str
    updated_at: str
    version: int


class ExamCandidate(TypedDict, total=False):
    id: str
    session_id: str
    candidate_name: str
    frn: str
    element: str
    member_id: Optional[str]
    status: str
    checked_in_by_member_id: Optional[str]
    score_percent: Optional[int]
    created_at: str
    updated_at: str
    version: int


class EquipmentLoan(TypedDict, total=False):
    id: str
    item_tag: str
    member_id: str
    estimated_value_cents: int
    checked_out_at: str
    due_at: str
    returned_at: Optional[str]
    return_condition: Optional[str]
    status: str
    late_fee_cents: int
    created_at: str
    updated_at: str
    version: int
