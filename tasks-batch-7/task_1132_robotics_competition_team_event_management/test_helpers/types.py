"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class FrcEventStatus(str, Enum):
    SETUP = "SETUP"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_LOCKED = "REGISTRATION_LOCKED"
    BUILD_SEASON = "BUILD_SEASON"
    INSPECTION = "INSPECTION"
    MATCHES_RUNNING = "MATCHES_RUNNING"
    ALLIANCE_SELECTION = "ALLIANCE_SELECTION"
    AWARDS = "AWARDS"
    CLOSED = "CLOSED"


class EventPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class RegistrationStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAYMENT_CLEARED = "PAYMENT_CLEARED"
    ROSTER_SUBMITTED = "ROSTER_SUBMITTED"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class RobotInspectionStatus(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    SUBMITTED = "SUBMITTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class ScreeningStatus(str, Enum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PersonRoleKind(str, Enum):
    MENTOR = "MENTOR"
    VOLUNTEER = "VOLUNTEER"
    JUDGE = "JUDGE"
    STUDENT = "STUDENT"


class ScreeningDecision(str, Enum):
    PENDING = "PENDING"
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    EXPIRE = "EXPIRE"


class MilestoneKind(str, Enum):
    KICKOFF = "KICKOFF"
    STOP_BUILD = "STOP_BUILD"
    BAG_DAY = "BAG_DAY"
    SHIP_DATE = "SHIP_DATE"
    UNBAG_WINDOW = "UNBAG_WINDOW"


class MilestoneStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARMED = "ARMED"
    PASSED = "PASSED"
    CANCELLED = "CANCELLED"


class PartOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    VENDOR_PLACED = "VENDOR_PLACED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class RobotInspectionRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class ViolationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ViolationSourceKind(str, Enum):
    INSPECTION = "INSPECTION"
    MATCH_REVIEW = "MATCH_REVIEW"
    FIELD_SAFETY = "FIELD_SAFETY"
    JUDGE_REFERRAL = "JUDGE_REFERRAL"


class ResolutionStatus(str, Enum):
    OPEN = "OPEN"
    ACKED = "ACKED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class MatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    QUEUED = "QUEUED"
    ON_FIELD = "ON_FIELD"
    SCORED = "SCORED"
    FINALIZED = "FINALIZED"
    REPLAYED = "REPLAYED"
    CANCELLED = "CANCELLED"


class MatchSeries(str, Enum):
    QUALIFICATION = "QUALIFICATION"
    PLAYOFF = "PLAYOFF"


class AllianceStatus(str, Enum):
    FORMING = "FORMING"
    SEALED = "SEALED"
    ELIMINATED = "ELIMINATED"
    CHAMPION = "CHAMPION"


class SelectionRoundStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    COMPLETE = "COMPLETE"


class AllianceColor(str, Enum):
    RED = "RED"
    BLUE = "BLUE"


class CardIssued(str, Enum):
    NONE = "NONE"
    YELLOW = "YELLOW"
    RED = "RED"


class QueueSlotPosition(str, Enum):
    RED_1 = "RED_1"
    RED_2 = "RED_2"
    RED_3 = "RED_3"
    BLUE_1 = "BLUE_1"
    BLUE_2 = "BLUE_2"
    BLUE_3 = "BLUE_3"


class QueueSlotStatus(str, Enum):
    STAGED = "STAGED"
    AT_FIELD = "AT_FIELD"
    ON_FIELD = "ON_FIELD"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"


class FieldResetStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    ABORTED = "ABORTED"


class AwardKind(str, Enum):
    CHAIRMANS = "CHAIRMANS"
    ENGINEERING_INSPIRATION = "ENGINEERING_INSPIRATION"
    ROOKIE_ALL_STAR = "ROOKIE_ALL_STAR"
    WOODIE_FLOWERS = "WOODIE_FLOWERS"
    DEANS_LIST = "DEANS_LIST"
    SAFETY = "SAFETY"
    CREATIVITY = "CREATIVITY"
    QUALITY = "QUALITY"
    INNOVATION = "INNOVATION"
    GRACIOUS_PROFESSIONALISM = "GRACIOUS_PROFESSIONALISM"


class AwardStatus(str, Enum):
    OPEN = "OPEN"
    JUDGING = "JUDGING"
    DECIDED = "DECIDED"
    PRESENTED = "PRESENTED"


class InterviewSlotStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class TravelMode(str, Enum):
    AIR = "AIR"
    RAIL = "RAIL"
    BUS = "BUS"
    SELF_DRIVE = "SELF_DRIVE"


class ReimbursementStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"


class UserRole(str, Enum):
    EventDirector = "EventDirector"
    RegistrationOfficer = "RegistrationOfficer"
    ScreeningOfficer = "ScreeningOfficer"
    TeamLead = "TeamLead"
    ProcurementOfficer = "ProcurementOfficer"
    Inspector = "Inspector"
    LeadInspector = "LeadInspector"
    HeadReferee = "HeadReferee"
    Scorekeeper = "Scorekeeper"
    QueueManager = "QueueManager"
    FieldResetCrew = "FieldResetCrew"
    JudgeAdvisor = "JudgeAdvisor"
    Judge = "Judge"
    TravelOfficer = "TravelOfficer"
