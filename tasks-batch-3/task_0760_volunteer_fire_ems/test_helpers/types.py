"""Domain types: entity TypedDicts, status enums, role enum.

All names follow the PRD's vocabulary. Append-only event logs (TrainingRecord,
PointAdjustment) carry only ``id`` and ``created_at`` — never ``updated_at`` or
``version`` (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    CHIEF = "Chief"
    OFFICER = "Officer"
    MEMBER = "Member"


# ------------------------------------------------------------------ status enums
class MembershipStatus(str, Enum):
    PROBATIONARY = "PROBATIONARY"
    ACTIVE = "ACTIVE"
    LOA = "LOA"
    RETIRED = "RETIRED"
    EXPELLED = "EXPELLED"


class RoleClass(str, Enum):
    OFFICER = "OFFICER"
    PARAMEDIC = "PARAMEDIC"
    EMT = "EMT"
    FIREFIGHTER = "FIREFIGHTER"
    PROBATIONARY = "PROBATIONARY"


class PointsTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class CertType(str, Enum):
    FIREFIGHTER_1 = "FIREFIGHTER_1"
    EMT_BASIC = "EMT_BASIC"
    PARAMEDIC = "PARAMEDIC"
    HAZMAT = "HAZMAT"
    DRIVER_OPERATOR = "DRIVER_OPERATOR"
    CPR = "CPR"


class TrainingCategory(str, Enum):
    FIRE = "FIRE"
    EMS = "EMS"
    HAZMAT = "HAZMAT"
    DRIVER = "DRIVER"
    CPR = "CPR"


class CertStatus(str, Enum):
    PENDING = "PENDING"
    CURRENT = "CURRENT"
    EXPIRING = "EXPIRING"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ApparatusType(str, Enum):
    ENGINE = "ENGINE"
    LADDER = "LADDER"
    AMBULANCE = "AMBULANCE"
    RESCUE = "RESCUE"
    TANKER = "TANKER"


class ApparatusPosture(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    RESERVE = "RESERVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class EquipmentStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DutyShiftStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StaffingStatus(str, Enum):
    UNDERSTAFFED = "UNDERSTAFFED"
    STAFFED = "STAFFED"
    FULL = "FULL"


class DutyAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CHECKED_IN = "CHECKED_IN"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class IncidentType(str, Enum):
    STRUCTURE_FIRE = "STRUCTURE_FIRE"
    MVA = "MVA"
    EMS = "EMS"
    ALARM = "ALARM"
    OTHER = "OTHER"


class ResponseStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    ENROUTE = "ENROUTE"
    ONSCENE = "ONSCENE"
    CLEARED = "CLEARED"


class ReportStatus(str, Enum):
    NONE = "NONE"
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    AMENDED = "AMENDED"


class TurnoutStatus(str, Enum):
    RESPONDED = "RESPONDED"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class DonationStatus(str, Enum):
    POSTED = "POSTED"
    REFUNDED = "REFUNDED"


# ------------------------------------------------------------- entity TypedDicts
# common_fields: true -> id + created_at + updated_at + version
class Member(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    role_class: str
    membership_status: str
    join_date: str
    dues_balance_cents: int
    dues_paid_through: Optional[str]
    response_eligible: bool
    training_hours_ytd: float
    points_ytd: int
    stipend_cents: int
    points_tier: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    member_id: str
    cert_type: str
    is_required: bool
    category: str
    status: str
    cycle_start_at: str
    issued_at: Optional[str]
    expires_at: Optional[str]
    completed_hours_strict: float
    completed_hours_carryover: float
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict, total=False):
    id: str
    name: str
    address: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Apparatus(TypedDict, total=False):
    id: str
    station_id: str
    unit_designation: str
    apparatus_type: str
    min_crew: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict, total=False):
    id: str
    apparatus_id: str
    name: str
    is_critical: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    apparatus_id: str
    start_at: str
    end_at: str
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DutyShift(TypedDict, total=False):
    id: str
    station_id: str
    apparatus_id: str
    start_at: str
    end_at: str
    min_crew: int
    max_crew: int
    assigned_count: int
    staffing_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DutyAssignment(TypedDict, total=False):
    id: str
    duty_shift_id: str
    member_id: str
    status: str
    checked_in_at: Optional[str]
    duty_points: int
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    station_id: str
    apparatus_id: str
    incident_type: str
    alarm_at: str
    enroute_at: Optional[str]
    onscene_at: Optional[str]
    cleared_at: Optional[str]
    response_status: str
    report_status: str
    nfirs_property_use: Optional[str]
    nfirs_actions_taken: Optional[str]
    report_revision: int
    created_at: str
    updated_at: str
    version: int


class TurnoutResponse(TypedDict, total=False):
    id: str
    incident_id: str
    member_id: str
    responded_at: str
    status: str
    turnout_points: int
    created_at: str
    updated_at: str
    version: int


class FundraisingCampaign(TypedDict, total=False):
    id: str
    name: str
    goal_cents: int
    raised_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict, total=False):
    id: str
    campaign_id: str
    donor_name: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only, id + created_at ONLY (no updated_at/version)
class TrainingRecord(TypedDict, total=False):
    id: str
    member_id: str
    certification_id: Optional[str]
    category: str
    hours: float
    training_date: str
    description: Optional[str]
    created_at: str


class PointAdjustment(TypedDict, total=False):
    id: str
    member_id: str
    points: int
    reason: str
    reversed: bool
    created_at: str
