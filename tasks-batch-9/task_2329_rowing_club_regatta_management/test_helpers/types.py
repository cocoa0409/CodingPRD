"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CLUB_ADMIN = "ClubAdmin"
    MEMBER = "Member"
    COACH = "Coach"
    SAFETY_OFFICER = "SafetyOfficer"
    EQUIPMENT_MANAGER = "EquipmentManager"
    RACE_OFFICIAL = "RaceOfficial"
    JURY_CHAIR = "JuryChair"


class MemberTier(str, Enum):
    COMPETITIVE = "COMPETITIVE"
    RECREATIONAL = "RECREATIONAL"
    LEARN_TO_ROW = "LEARN_TO_ROW"


class ClubRole(str, Enum):
    ATHLETE = "ATHLETE"
    COXSWAIN = "COXSWAIN"
    COACH = "COACH"
    LAUNCH_DRIVER = "LAUNCH_DRIVER"
    JURY = "JURY"
    EQUIPMENT_MANAGER = "EQUIPMENT_MANAGER"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DUES_HOLD = "DUES_HOLD"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class BoathouseAccessLevel(str, Enum):
    FULL = "FULL"
    SUPERVISED = "SUPERVISED"
    NONE = "NONE"


class DuesInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    DELINQUENT = "DELINQUENT"
    PAID = "PAID"
    VOIDED = "VOIDED"


class VariantBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    TRUEUP = "TRUEUP"


class BoatClass(str, Enum):
    SINGLE = "1X"
    DOUBLE = "2X"
    COXED_FOUR = "4+"
    EIGHT = "8+"


class TierRestriction(str, Enum):
    COMPETITIVE_ONLY = "COMPETITIVE_ONLY"
    ANY = "ANY"


class ShellStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    DAMAGED = "DAMAGED"
    IN_REPAIR = "IN_REPAIR"
    RETIRED = "RETIRED"


class DamageSeverity(str, Enum):
    COSMETIC = "COSMETIC"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    STRUCTURAL = "STRUCTURAL"


class DamageReportStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    REPAIR_SCHEDULED = "REPAIR_SCHEDULED"
    VERIFIED = "VERIFIED"
    CONDEMNED = "CONDEMNED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


class TriageDisposition(str, Enum):
    REPAIR = "REPAIR"
    CLOSE_NO_ACTION = "CLOSE_NO_ACTION"


class TrafficPattern(str, Enum):
    STANDARD_COUNTERCLOCKWISE = "STANDARD_COUNTERCLOCKWISE"
    REVERSED_CLOCKWISE = "REVERSED_CLOCKWISE"
    NARROW_CHANNEL = "NARROW_CHANNEL"


class WaterPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class SessionKind(str, Enum):
    PRACTICE = "PRACTICE"
    LEARN_TO_ROW = "LEARN_TO_ROW"
    RACE_PREP = "RACE_PREP"


class WaterSessionStatus(str, Enum):
    PLANNED = "PLANNED"
    CLEARED = "CLEARED"
    LAUNCHED = "LAUNCHED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class VenueKind(str, Enum):
    HOME = "HOME"
    AWAY = "AWAY"


class RegattaStatus(str, Enum):
    OPEN_FOR_ENTRY = "OPEN_FOR_ENTRY"
    ENTRIES_CLOSED = "ENTRIES_CLOSED"
    RACING = "RACING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class RegattaEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    LINEUP_DECLARED = "LINEUP_DECLARED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    RACED = "RACED"
    SCRATCHED = "SCRATCHED"


class SeatRole(str, Enum):
    ROWER = "ROWER"
    COXSWAIN = "COXSWAIN"


class WeighInStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    BLOCKED_SAFETY = "BLOCKED_SAFETY"
    BLOCKED_CERT = "BLOCKED_CERT"
    BLOCKED_DUES = "BLOCKED_DUES"


class RoundKind(str, Enum):
    HEAT = "HEAT"
    SEMI = "SEMI"
    FINAL = "FINAL"


class HeatStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LANES_ASSIGNED = "LANES_ASSIGNED"
    RESULTS_PROVISIONAL = "RESULTS_PROVISIONAL"
    RESULTS_OFFICIAL = "RESULTS_OFFICIAL"


class LaneStatus(str, Enum):
    PENDING = "PENDING"
    PROVISIONAL = "PROVISIONAL"
    OFFICIAL = "OFFICIAL"
    DISQUALIFIED = "DISQUALIFIED"
    VOIDED = "VOIDED"


class ProtestGroundCode(str, Enum):
    INTERFERENCE = "INTERFERENCE"
    LANE_VIOLATION = "LANE_VIOLATION"
    EQUIPMENT = "EQUIPMENT"
    FALSE_START = "FALSE_START"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    UNDER_JURY_REVIEW = "UNDER_JURY_REVIEW"
    REMANDED = "REMANDED"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class JuryDecision(str, Enum):
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    REMAND = "REMAND"


class JuryRemedy(str, Enum):
    DISQUALIFY = "DISQUALIFY"
    RE_ROW = "RE_ROW"


class TrailerLoadStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    RETURNED = "RETURNED"


# --- Entities ---------------------------------------------------------------
# Every persisted resource carries id + created_at; all of them except
# river-condition readings additionally carry updated_at and version (PRD §2.4).


class Member(TypedDict):
    id: str
    full_name: str
    tier: str
    body_weight_kg: float
    club_roles: List[str]
    swim_test_passed_on: Optional[str]
    coxswain_cert_expires_at: Optional[str]
    coach_cert_expires_at: Optional[str]
    safety_launch_cert_expires_at: Optional[str]
    launch_supervision_limit: int
    membership_status: str
    dues_balance_cents: int
    logged_session_count: int
    boathouse_access_level: str
    created_at: str
    updated_at: str
    version: int


class DuesInvoice(TypedDict):
    id: str
    member_id: str
    season_year: int
    billable_months: int
    locker_requested: bool
    due_at: str
    status: str
    variant_basis: str
    assessed_cents: int
    paid_cents: int
    trueup_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Shell(TypedDict):
    id: str
    hull_name: str
    boat_class: str
    hull_weight_kg: float
    home_bay: str
    tier_restriction: str
    last_serviced_at: Optional[str]
    status: str
    slot_units: int
    condition_index_conservative: int
    condition_index_optimistic: int
    created_at: str
    updated_at: str
    version: int


class DamageReport(TypedDict):
    id: str
    shell_id: str
    reported_by_member_id: str
    severity: str
    narrative: str
    reported_at: str
    status: str
    triaged_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    assigned_repair_bay: Optional[str]
    repair_window_start_at: Optional[str]
    repair_window_end_at: Optional[str]
    severity_points: float
    created_at: str
    updated_at: str
    version: int


class WaterConditionReading(TypedDict):
    """A reading is an immutable observation, so it carries only id and
    created_at — it has neither updated_at nor version (PRD §2.4)."""

    id: str
    observed_at: str
    air_temp_c: float
    water_temp_c: float
    wind_speed_kt: float
    visibility_m: int
    traffic_pattern: str
    cold_water_flag: bool
    posture: str
    created_at: str


class WaterSession(TypedDict):
    id: str
    shell_id: str
    session_kind: str
    planned_start_at: str
    planned_end_at: str
    coach_member_id: Optional[str]
    coxswain_member_id: Optional[str]
    primary_launch_driver_member_id: Optional[str]
    secondary_launch_driver_member_id: Optional[str]
    athlete_member_ids: List[str]
    status: str
    reading_id: Optional[str]
    required_launch_count: int
    assigned_launch_count: int
    actual_return_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Regatta(TypedDict):
    id: str
    name: str
    host_club: str
    venue_kind: str
    race_date_at: str
    entry_deadline_at: str
    scratch_deadline_at: str
    weigh_in_opens_at: str
    weigh_in_closes_at: str
    late_entry_allowed: bool
    status: str
    net_fee_cents: int
    deposit_held_cents: int
    created_at: str
    updated_at: str
    version: int


class RegattaEntry(TypedDict):
    id: str
    regatta_id: str
    shell_id: str
    event_code: str
    boat_class: str
    seed_time_seconds: float
    status: str
    base_fee_cents: int
    transport_levy_cents: int
    late_fee_cents: int
    total_fee_cents: int
    refund_cents: Optional[int]
    submitted_at: Optional[str]
    trailer_load_id: Optional[str]
    rack_tier: Optional[int]
    rack_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LineupSeat(TypedDict):
    id: str
    regatta_entry_id: str
    member_id: str
    seat_number: int
    seat_role: str
    weighed_kg: Optional[float]
    weighed_by_user_id: Optional[str]
    deadweight_kg: Optional[float]
    weigh_in_status: str
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


class Heat(TypedDict):
    id: str
    regatta_id: str
    event_code: str
    round_kind: str
    scheduled_start_at: str
    lane_count: int
    advance_count: int
    advances_to_heat_id: Optional[str]
    status: str
    occupied_lane_count: int
    free_lane_count: int
    protest_window_closes_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RaceLane(TypedDict):
    id: str
    heat_id: str
    regatta_entry_id: str
    lane_number: int
    lane_status: str
    elapsed_seconds: Optional[float]
    place: Optional[int]
    advanced: bool
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict):
    id: str
    heat_id: str
    filed_by_member_id: str
    against_race_lane_id: str
    ground_code: str
    narrative: str
    filed_at: str
    status: str
    deposit_cents: int
    deposit_refunded: bool
    review_round: int
    jury_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrailerLoad(TypedDict):
    id: str
    regatta_id: str
    driver_member_id: str
    tow_vehicle_code: str
    depart_at: str
    return_at: str
    rack_tier_count: int
    rack_units_per_tier: int
    rack_unit_capacity: int
    status: str
    rack_units_used: int
    rack_units_free: int
    created_at: str
    updated_at: str
    version: int
