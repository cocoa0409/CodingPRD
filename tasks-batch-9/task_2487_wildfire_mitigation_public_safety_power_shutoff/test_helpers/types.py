"""Enumerations and literal vocabularies declared by the Wildfire Mitigation PSPS
contract.

Every member below is spelled exactly as the PRD spells it, because the API
compares these strings verbatim.
"""

from enum import Enum


class UserRole(str, Enum):
    """The eight roles of PRD §2.1."""

    GRID_PLANNER = "GridPlanner"
    METEOROLOGY_ANALYST = "MeteorologyAnalyst"
    PSPS_DUTY_OFFICER = "PSPSDutyOfficer"
    COMMUNITY_LIAISON = "CommunityLiaison"
    REGULATORY_REVIEWER = "RegulatoryReviewer"
    FIELD_PATROL_SUPERVISOR = "FieldPatrolSupervisor"
    ASSET_INSPECTOR = "AssetInspector"
    TRANSMISSION_ENGINEER = "TransmissionEngineer"


ALL_ROLES = [role.value for role in UserRole]


class HftdTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    NON_HFTD = "NON_HFTD"


class EnergizationState(str, Enum):
    ENERGIZED = "ENERGIZED"
    DE_ENERGIZATION_PENDING = "DE_ENERGIZATION_PENDING"
    DE_ENERGIZED = "DE_ENERGIZED"
    PATROL_IN_PROGRESS = "PATROL_IN_PROGRESS"
    CLEARED_FOR_RESTORE = "CLEARED_FOR_RESTORE"


class RiskPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    EXTREME = "EXTREME"
    LOCKED = "LOCKED"


class TelemetryStatus(str, Enum):
    ONLINE = "ONLINE"
    DEGRADED = "DEGRADED"
    OFFLINE = "OFFLINE"


class ComputationVariant(str, Enum):
    FORECAST = "FORECAST"
    VALIDATED = "VALIDATED"


class FpiTier(str, Enum):
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"
    R4 = "R4"
    R5 = "R5"


class CustomerClass(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    CRITICAL_FACILITY = "CRITICAL_FACILITY"


class NotificationTier(str, Enum):
    TIER_A_CRITICAL = "TIER_A_CRITICAL"
    TIER_B_MEDICAL = "TIER_B_MEDICAL"
    TIER_C_STANDARD = "TIER_C_STANDARD"


class Language(str, Enum):
    EN = "EN"
    ES = "ES"
    ZH = "ZH"
    TL = "TL"
    VI = "VI"


class Channel(str, Enum):
    SMS = "SMS"
    VOICE = "VOICE"
    EMAIL = "EMAIL"


class AccessibilityNeed(str, Enum):
    LARGE_PRINT = "LARGE_PRINT"
    TTY = "TTY"
    AUDIO = "AUDIO"


class AccessibilityFormat(str, Enum):
    LARGE_PRINT = "LARGE_PRINT"
    STANDARD = "STANDARD"


class DeliveryStatus(str, Enum):
    DELIVERED = "DELIVERED"
    UNREACHABLE = "UNREACHABLE"


class EventScopeStatus(str, Enum):
    """The `scope_status` dimension of a PSPSEvent (PRD §3.4)."""

    DRAFT = "DRAFT"
    SCOPED = "SCOPED"
    ARMED = "ARMED"
    ACTIVE = "ACTIVE"
    RESTORING = "RESTORING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class NotificationStatus(str, Enum):
    """The `notification_status` dimension of a PSPSEvent (PRD §3.4)."""

    NOT_STARTED = "NOT_STARTED"
    ADVANCE_SENT = "ADVANCE_SENT"
    IMMINENT_SENT = "IMMINENT_SENT"
    ACTIVATION_SENT = "ACTIVATION_SENT"
    RESTORATION_SENT = "RESTORATION_SENT"


class ScopeRowStatus(str, Enum):
    """The `scope_status` of an individual EventScope row."""

    CONFIRMED = "CONFIRMED"
    EXCLUDED = "EXCLUDED"


class InclusionBasis(str, Enum):
    PRIMARY_RISK = "PRIMARY_RISK"
    DOWNSTREAM_DEPENDENCY = "DOWNSTREAM_DEPENDENCY"


class BenefitVariant(str, Enum):
    PRE_EVENT = "PRE_EVENT"
    POST_EVENT = "POST_EVENT"


class NotificationStage(str, Enum):
    ADVANCE_48H = "ADVANCE_48H"
    ADVANCE_24H = "ADVANCE_24H"
    IMMINENT_1H = "IMMINENT_1H"
    ACTIVATION = "ACTIVATION"
    RESTORATION = "RESTORATION"


class BatchStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    FAILED_PARTIAL = "FAILED_PARTIAL"


class ProgramType(str, Enum):
    COVERED_CONDUCTOR = "COVERED_CONDUCTOR"
    UNDERGROUNDING = "UNDERGROUNDING"
    FAST_TRIP_SETTING = "FAST_TRIP_SETTING"
    INSPECTION_CYCLE = "INSPECTION_CYCLE"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    IN_EXECUTION = "IN_EXECUTION"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_REVISION = "REQUEST_REVISION"
    WITHDRAW = "WITHDRAW"


class PatrolMode(str, Enum):
    GROUND = "GROUND"
    AERIAL = "AERIAL"
    DRONE = "DRONE"


class PatrolStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class DamageSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    IGNITION_RISK = "IGNITION_RISK"


class ResourceCenterStatus(str, Enum):
    STANDBY = "STANDBY"
    ACTIVATED = "ACTIVATED"
    DEMOBILIZED = "DEMOBILIZED"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DEFICIENCY_ISSUED = "DEFICIENCY_ISSUED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewTrack(str, Enum):
    SAFETY = "SAFETY"
    FISCAL = "FISCAL"


class ReviewTrackState(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DEFICIENT = "DEFICIENT"


class FilingDecision(str, Enum):
    CLEAR = "CLEAR"
    DEFICIENT = "DEFICIENT"
