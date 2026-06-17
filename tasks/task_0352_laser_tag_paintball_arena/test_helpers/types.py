"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the full common-field discipline
(id, created_at, updated_at, version) per PRD §2.4 — there are no
creation-only resources here.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    ARENA_MANAGER = "ArenaManager"
    FRONT_DESK = "FrontDesk"
    FIELD_MARSHAL = "FieldMarshal"
    LEAGUE_DIRECTOR = "LeagueDirector"


# --- Status enums ---
class ArenaStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FieldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class GameMode(str, Enum):
    LASER_TAG = "LASER_TAG"
    PAINTBALL = "PAINTBALL"


class BookingType(str, Enum):
    RESERVATION = "RESERVATION"
    WALK_IN = "WALK_IN"


class BookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class WaiverStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    VOID = "VOID"


class UnitType(str, Enum):
    MARKER = "MARKER"
    VEST = "VEST"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    CHECKED_OUT = "CHECKED_OUT"
    MAINTENANCE = "MAINTENANCE"


class RentalStatus(str, Enum):
    HELD = "HELD"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"
    RELEASED = "RELEASED"


class AddOnStatus(str, Enum):
    QUOTED = "QUOTED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class RefereeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_DUTY = "ON_DUTY"
    OFF_SHIFT = "OFF_SHIFT"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class LeagueStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    ROUND_LOCKED = "ROUND_LOCKED"
    FINALIZED = "FINALIZED"


class MatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESULT_RECORDED = "RESULT_RECORDED"
    VOID = "VOID"


class MatchOutcome(str, Enum):
    HOME = "HOME"
    AWAY = "AWAY"
    DRAW = "DRAW"


# --- Entity TypedDicts (all carry common fields per PRD §2.4) ---
class Arena(TypedDict):
    id: str
    name: str
    timezone: str
    current_utc: str
    marker_pool_total: int
    vest_pool_total: int
    marker_available_count: int
    vest_available_count: int
    deposit_held_cents: int
    deposit_refunded_cents: int
    deposit_forfeited_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict):
    id: str
    arena_id: str
    name: str
    game_mode: str
    capacity_max: int
    turnaround_minutes: int
    reserved_headcount: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartyPackage(TypedDict):
    id: str
    arena_id: str
    name: str
    included_players: int
    extra_player_fee_cents: int
    base_fee_cents: int
    included_ammo_balls: int
    discount_pct: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    arena_id: str
    field_id: str
    package_id: Optional[str]
    booking_type: str
    party_size: int
    window_start: str
    window_end: str
    status: str
    field_fee_cents: int
    invoice_total_cents: int
    checked_in_count: int
    minors_present: bool
    referee_required: bool
    created_at: str
    updated_at: str
    version: int


class WaiverProfile(TypedDict):
    id: str
    arena_id: str
    booking_id: str
    participant_name: str
    date_of_birth: str
    age_years: int
    is_minor: bool
    guardian_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict):
    id: str
    arena_id: str
    unit_type: str
    asset_tag: str
    deposit_cents: int
    condition_grade: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Rental(TypedDict):
    id: str
    arena_id: str
    booking_id: str
    equipment_unit_id: str
    deposit_hold_cents: int
    damage_fee_cents: int
    deposit_refund_cents: int
    deposit_forfeit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOnOrder(TypedDict):
    id: str
    arena_id: str
    booking_id: str
    ammo_balls: int
    co2_tanks: int
    misc_cents: int
    quote_total_cents: int
    settled_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referee(TypedDict):
    id: str
    arena_id: str
    name: str
    certified_paintball: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RefereeAssignment(TypedDict):
    id: str
    arena_id: str
    booking_id: str
    referee_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class League(TypedDict):
    id: str
    arena_id: str
    name: str
    total_rounds: int
    current_round: int
    win_points: int
    draw_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeagueMatch(TypedDict):
    id: str
    arena_id: str
    league_id: str
    booking_id: str
    round_index: int
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int
