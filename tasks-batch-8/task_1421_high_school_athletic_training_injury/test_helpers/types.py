"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    ATHLETIC_TRAINER = "AthleticTrainer"
    ATHLETIC_DIRECTOR = "AthleticDirector"
    SCHOOL_NURSE = "SchoolNurse"
    PHYSICIAN = "Physician"
    TEAM_COACH = "TeamCoach"
    PARENT_GUARDIAN = "ParentGuardian"


class StaffRoleType(str, Enum):
    ATHLETIC_TRAINER = "ATHLETIC_TRAINER"
    TEAM_COACH = "TEAM_COACH"
    PHYSICIAN = "PHYSICIAN"
    ATHLETIC_DIRECTOR = "ATHLETIC_DIRECTOR"
    SCHOOL_NURSE = "SCHOOL_NURSE"


class Sport(str, Enum):
    FOOTBALL = "FOOTBALL"
    SOCCER = "SOCCER"
    BASKETBALL = "BASKETBALL"
    BASEBALL = "BASEBALL"
    SOFTBALL = "SOFTBALL"
    VOLLEYBALL = "VOLLEYBALL"
    WRESTLING = "WRESTLING"
    LACROSSE = "LACROSSE"
    FIELD_HOCKEY = "FIELD_HOCKEY"
    CROSS_COUNTRY = "CROSS_COUNTRY"
    TRACK = "TRACK"
    SWIMMING = "SWIMMING"
    TENNIS = "TENNIS"
    GOLF = "GOLF"


class TeamLevel(str, Enum):
    VARSITY = "VARSITY"
    JV = "JV"
    FRESHMAN = "FRESHMAN"


class ParticipationPosture(str, Enum):
    NOT_CLEARED = "NOT_CLEARED"
    INELIGIBLE = "INELIGIBLE"
    MEDICAL_HOLD = "MEDICAL_HOLD"
    CLEARED_WITH_RESTRICTIONS = "CLEARED_WITH_RESTRICTIONS"
    CLEARED = "CLEARED"


class PostureReason(str, Enum):
    NO_VERIFIED_PHYSICAL = "NO_VERIFIED_PHYSICAL"
    PHYSICAL_EXPIRED = "PHYSICAL_EXPIRED"
    PHYSICAL_OUTCOME_BLOCKS = "PHYSICAL_OUTCOME_BLOCKS"
    NO_CURRENT_BASELINE = "NO_CURRENT_BASELINE"
    ACUTE_INJURY_OPEN = "ACUTE_INJURY_OPEN"
    PHYSICIAN_REVIEW_PENDING = "PHYSICIAN_REVIEW_PENDING"
    INJURY_RESTRICTIONS = "INJURY_RESTRICTIONS"
    PHYSICAL_RESTRICTIONS = "PHYSICAL_RESTRICTIONS"


class PhysicalOutcome(str, Enum):
    CLEARED = "CLEARED"
    CLEARED_WITH_RESTRICTIONS = "CLEARED_WITH_RESTRICTIONS"
    NOT_CLEARED = "NOT_CLEARED"
    DEFERRED = "DEFERRED"


class ValidityPolicy(str, Enum):
    DISTRICT_13MO = "DISTRICT_13MO"
    STATE_SCHOOL_YEAR = "STATE_SCHOOL_YEAR"


class PhysicalStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class Instrument(str, Enum):
    SCAT6 = "SCAT6"
    IMPACT = "IMPACT"
    SWAY = "SWAY"


class BaselineStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class VenueType(str, Enum):
    INDOOR = "INDOOR"
    OUTDOOR = "OUTDOOR"


class Surface(str, Enum):
    GRASS = "GRASS"
    TURF = "TURF"
    COURT = "COURT"
    TRACK = "TRACK"
    POOL = "POOL"
    GYM_FLOOR = "GYM_FLOOR"


class EapStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class EventType(str, Enum):
    PRACTICE = "PRACTICE"
    SCRIMMAGE = "SCRIMMAGE"
    HOME_GAME = "HOME_GAME"
    AWAY_GAME = "AWAY_GAME"
    TOURNAMENT = "TOURNAMENT"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COVERED = "COVERED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED_WEATHER = "SUSPENDED_WEATHER"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SuspensionReason(str, Enum):
    LIGHTNING = "LIGHTNING"
    HEAT = "HEAT"
    MANUAL = "MANUAL"


class CoverageRole(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ON_SITE = "ON_SITE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class ReadingType(str, Enum):
    HEAT_WBGT = "HEAT_WBGT"
    LIGHTNING_STRIKE = "LIGHTNING_STRIKE"


class ReadingSource(str, Enum):
    ON_SITE_SENSOR = "ON_SITE_SENSOR"
    WEATHER_SERVICE = "WEATHER_SERVICE"
    MANUAL = "MANUAL"


class HeatTier(str, Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    EXTREME = "EXTREME"


class BodyRegion(str, Enum):
    HEAD_NECK = "HEAD_NECK"
    SHOULDER = "SHOULDER"
    ARM_HAND = "ARM_HAND"
    TRUNK = "TRUNK"
    HIP_PELVIS = "HIP_PELVIS"
    KNEE = "KNEE"
    LOWER_LEG = "LOWER_LEG"
    ANKLE_FOOT = "ANKLE_FOOT"
    SYSTEMIC = "SYSTEMIC"


class InjuryType(str, Enum):
    CONCUSSION = "CONCUSSION"
    FRACTURE = "FRACTURE"
    SPRAIN = "SPRAIN"
    STRAIN = "STRAIN"
    LACERATION = "LACERATION"
    HEAT_ILLNESS = "HEAT_ILLNESS"
    CARDIAC = "CARDIAC"
    OTHER = "OTHER"


class Severity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    CRITICAL = "CRITICAL"


class InjuryStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_CARE = "UNDER_CARE"
    REFERRED = "REFERRED"
    RTP_IN_PROGRESS = "RTP_IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class Urgency(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    EMERGENT = "EMERGENT"


class ReferralStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    ADDENDUM_REQUESTED = "ADDENDUM_REQUESTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ReportClearance(str, Enum):
    CLEARED_FULL = "CLEARED_FULL"
    CLEARED_RESTRICTED = "CLEARED_RESTRICTED"
    NOT_CLEARED = "NOT_CLEARED"


class ClearanceAuthority(str, Enum):
    PHYSICIAN = "PHYSICIAN"
    TRAINER = "TRAINER"


class ProtocolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"
    TERMINATED = "TERMINATED"


class NotificationType(str, Enum):
    INJURY_INITIAL = "INJURY_INITIAL"
    REFERRAL_REQUEST = "REFERRAL_REQUEST"
    RTP_REGRESSION = "RTP_REGRESSION"
    CLEARANCE_GRANTED = "CLEARANCE_GRANTED"
    EVENT_SUSPENSION = "EVENT_SUSPENSION"


class Channel(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"


class NotificationStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"


class SupplyCategory(str, Enum):
    TAPE = "TAPE"
    FIRST_AID = "FIRST_AID"
    HYDRATION = "HYDRATION"
    EQUIPMENT = "EQUIPMENT"
    MEDICATION = "MEDICATION"


class SupplyUnit(str, Enum):
    ROLL = "ROLL"
    EACH = "EACH"
    CASE = "CASE"
    LITER = "LITER"
    BOX = "BOX"


class StockStatus(str, Enum):
    OUT_OF_STOCK = "OUT_OF_STOCK"
    LOW_STOCK = "LOW_STOCK"
    IN_STOCK = "IN_STOCK"


class TxnType(str, Enum):
    RESTOCK = "RESTOCK"
    USAGE = "USAGE"
    WASTE = "WASTE"
    ADJUSTMENT = "ADJUSTMENT"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).


class Staff(TypedDict, total=False):
    id: str
    full_name: str
    role_type: str
    sport_certifications: List[str]
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Athlete(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    grade: int
    sex: str
    primary_sport: str
    team_level: str
    guardian_name: str
    guardian_user_id: str
    guardian_email: Optional[str]
    guardian_phone: Optional[str]
    participation_posture: str
    posture_reasons: List[str]
    created_at: str
    updated_at: str
    version: int


class PreParticipationPhysical(TypedDict, total=False):
    id: str
    athlete_id: str
    exam_date: str
    examining_physician_name: str
    outcome: str
    validity_policy: str
    restriction_notes: Optional[str]
    recorded_by_staff_id: str
    verified_by_staff_id: Optional[str]
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BaselineConcussionTest(TypedDict, total=False):
    id: str
    athlete_id: str
    test_date: str
    instrument: str
    symptom_score: int
    memory_index: float
    reaction_time_ms: float
    balance_errors: int
    administered_by_staff_id: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    venue_name: str
    venue_type: str
    surface: str
    lightning_detection: bool
    lightning_radius_miles: float
    address: str
    is_active: bool
    active_eap_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmergencyActionPlan(TypedDict, total=False):
    id: str
    venue_id: str
    version_label: str
    evacuation_route: str
    aed_location: str
    ems_contact: str
    nearest_hospital: str
    supersedes_eap_id: Optional[str]
    authored_by_staff_id: str
    approved_by_staff_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AthleticEvent(TypedDict, total=False):
    id: str
    event_name: str
    sport: str
    team_level: str
    event_type: str
    venue_id: str
    scheduled_start: str
    scheduled_end: str
    expected_attendance: int
    required_trainer_count: int
    active_assignment_count: int
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageAssignment(TypedDict, total=False):
    id: str
    event_id: str
    staff_id: str
    coverage_role: str
    status: str
    pre_hold_status: Optional[str]
    acknowledged_at: Optional[str]
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InjuryEvaluation(TypedDict, total=False):
    id: str
    athlete_id: str
    event_id: Optional[str]
    body_region: str
    injury_type: str
    severity: str
    mechanism: str
    evaluated_at: str
    restricted_activities: List[str]
    reopen_of_id: Optional[str]
    evaluated_by_staff_id: str
    recurrence_count: int
    resolved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PhysicianReferral(TypedDict, total=False):
    id: str
    injury_id: str
    athlete_id: str
    physician_staff_id: str
    reason: str
    urgency: str
    due_by: str
    appointment_at: Optional[str]
    report_diagnosis: Optional[str]
    report_clearance: Optional[str]
    reported_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnToPlayProtocol(TypedDict, total=False):
    id: str
    injury_id: str
    athlete_id: str
    protocol_type: str
    current_stage: int
    stage_entered_at: str
    recurrence_count: int
    clearance_authority_required: str
    stage_history: List[dict]
    cleared_by_staff_id: Optional[str]
    cleared_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GuardianNotification(TypedDict, total=False):
    id: str
    athlete_id: str
    injury_id: Optional[str]
    referral_id: Optional[str]
    notification_type: str
    channel: str
    subject: str
    sent_at: Optional[str]
    acknowledged_at: Optional[str]
    attempts: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyItem(TypedDict, total=False):
    id: str
    item_name: str
    category: str
    unit: str
    par_level: int
    reorder_threshold: int
    unit_cost_cents: int
    is_discontinued: bool
    current_stock: int
    stock_status: str
    created_at: str
    updated_at: str
    version: int


class RestockOrder(TypedDict, total=False):
    id: str
    supply_item_id: str
    quantity: int
    unit_cost_cents: int
    fiscal_year: int
    extended_cost_cents: int
    requested_by_staff_id: str
    approved_by_staff_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyBudget(TypedDict, total=False):
    id: str
    fiscal_year: int
    total_budget_cents: int
    realized_spend_cents: int
    committed_spend_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only observation records (PRD §2.5): ONLY id + created_at are
# system-managed; updated_at and version are absent by design.


class EnvironmentalReading(TypedDict, total=False):
    id: str
    venue_id: str
    reading_type: str
    value_wbgt_f: Optional[float]
    strike_distance_miles: Optional[float]
    recorded_at: str
    source: str
    created_at: str


class InventoryTransaction(TypedDict, total=False):
    id: str
    supply_item_id: str
    txn_type: str
    quantity: int
    unit_cost_cents: Optional[int]
    occurred_at: str
    event_id: Optional[str]
    restock_order_id: Optional[str]
    reason: Optional[str]
    recorded_by_staff_id: str
    created_at: str
