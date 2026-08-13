"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    REC_ADMIN = "RecAdmin"
    LEAGUE_COORDINATOR = "LeagueCoordinator"
    FACILITY_MANAGER = "FacilityManager"
    MEMBER = "Member"
    STAFF = "Staff"


class Affiliation(str, Enum):
    STUDENT = "STUDENT"
    FACULTY = "FACULTY"
    COMMUNITY = "COMMUNITY"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class MembershipTerm(str, Enum):
    FALL_2026 = "FALL_2026"
    SPRING_2027 = "SPRING_2027"
    SUMMER_2027 = "SUMMER_2027"


class PricingVariant(str, Enum):
    FULL = "FULL"
    PRORATED = "PRORATED"


class LeagueStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    SCHEDULING = "SCHEDULING"
    IN_SEASON = "IN_SEASON"
    PLAYOFFS = "PLAYOFFS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Sport(str, Enum):
    BASKETBALL = "BASKETBALL"
    SOCCER = "SOCCER"
    VOLLEYBALL = "VOLLEYBALL"
    FLAG_FOOTBALL = "FLAG_FOOTBALL"
    DODGEBALL = "DODGEBALL"


class TeamStatus(str, Enum):
    REGISTERED = "REGISTERED"
    PLACED = "PLACED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class RosterEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class RosterRole(str, Enum):
    CAPTAIN = "CAPTAIN"
    PLAYER = "PLAYER"


class FacilityKind(str, Enum):
    COURT = "COURT"
    FIELD = "FIELD"
    ROOM = "ROOM"
    POOL = "POOL"


class GameStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULE_REQUIRED = "RESCHEDULE_REQUIRED"
    PLAYED_PENDING_CONFIRM = "PLAYED_PENDING_CONFIRM"
    DISPUTED = "DISPUTED"
    FINAL = "FINAL"
    FORFEITED = "FORFEITED"
    CANCELLED = "CANCELLED"


class BracketRound(str, Enum):
    REGULAR = "REGULAR"
    SEMIFINAL = "SEMIFINAL"
    CHAMPIONSHIP = "CHAMPIONSHIP"


class StaffRole(str, Enum):
    OFFICIAL = "OFFICIAL"
    INSTRUCTOR = "INSTRUCTOR"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WORKED = "WORKED"
    CANCELLED = "CANCELLED"
    PAID = "PAID"


class InjurySeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class InjuryReportStatus(str, Enum):
    REPORTED = "REPORTED"
    CLEARED = "CLEARED"


class CheckoutStatus(str, Enum):
    OUT = "OUT"
    RETURNED = "RETURNED"
    LOST = "LOST"


class LockerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"


class LockerSize(str, Enum):
    S = "S"
    M = "M"
    L = "L"


class ClassType(str, Enum):
    YOGA = "YOGA"
    SPIN = "SPIN"
    PILATES = "PILATES"
    HIIT = "HIIT"
    ZUMBA = "ZUMBA"


class FitnessClassStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    affiliation: str
    status: str
    waiver_signed_date: Optional[str]
    outstanding_fines_cents: int
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    term: str
    pricing_variant: str
    fee_cents: int
    status: str
    supersedes_membership_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class League(TypedDict):
    id: str
    name: str
    sport: str
    divisions: list
    registration_open_at: str
    registration_close_at: str
    season_start_at: str
    season_end_at: str
    team_capacity: int
    min_teams: int
    roster_min: int
    roster_max: int
    status: str
    free_agent_pool: list
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict):
    id: str
    league_id: str
    name: str
    captain_member_id: str
    skill_rating: int
    division_name: Optional[str]
    status: str
    wins: int
    losses: int
    ties: int
    points: int
    forfeit_count: int
    sportsmanship_points_total: int
    sportsmanship_rating_count: int
    sportsmanship_rating: Optional[float]
    active_roster_count: int
    created_at: str
    updated_at: str
    version: int


class RosterEntry(TypedDict):
    id: str
    team_id: str
    member_id: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    name: str
    kind: str
    operating_windows: list
    closures: list
    created_at: str
    updated_at: str
    version: int


class Game(TypedDict):
    id: str
    league_id: str
    division_name: Optional[str]
    home_team_id: str
    away_team_id: str
    facility_id: Optional[str]
    start_at: Optional[str]
    end_at: Optional[str]
    duration_minutes: Optional[int]
    status: str
    bracket_round: str
    next_game_id: Optional[str]
    report_home: Optional[dict]
    report_away: Optional[dict]
    final_home_score: Optional[int]
    final_away_score: Optional[int]
    actual_duration_minutes: Optional[int]
    forfeiting_team_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Staff(TypedDict):
    id: str
    full_name: str
    staff_role: str
    certification_level: Optional[int]
    certified_class_types: Optional[list]
    base_hourly_rate_cents: int
    payroll_pending_cents: int
    payroll_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class OfficiatingAssignment(TypedDict):
    id: str
    game_id: str
    staff_id: str
    status: str
    provisional_pay_cents: int
    final_pay_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InjuryReport(TypedDict):
    id: str
    member_id: str
    game_id: Optional[str]
    severity: str
    description: str
    status: str
    clearance_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentPool(TypedDict):
    id: str
    item_type: str
    total_qty: int
    daily_late_fee_cents: int
    unit_replacement_cents: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class EquipmentCheckout(TypedDict):
    id: str
    equipment_pool_id: str
    member_id: str
    quantity: int
    due_at: str
    status: str
    returned_at: Optional[str]
    late_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Locker(TypedDict):
    id: str
    locker_number: int
    size: str
    status: str
    rented_by_member_id: Optional[str]
    rental_term: Optional[str]
    rental_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FitnessClass(TypedDict):
    id: str
    title: str
    class_type: str
    instructor_staff_id: str
    facility_id: str
    start_at: str
    end_at: str
    duration_minutes: int
    capacity: int
    registered_count: int
    waitlist_count: int
    status: str
    attendance_count: Optional[int]
    instructor_pay_estimate_cents: int
    instructor_pay_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ClassRegistration(TypedDict):
    id: str
    fitness_class_id: str
    member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
