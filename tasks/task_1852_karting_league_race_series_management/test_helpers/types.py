"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2.4 and 3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class SeasonStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    FINALIZED = "FINALIZED"
    AWARDS_CONCLUDED = "AWARDS_CONCLUDED"


class ClassCode(str, Enum):
    CADET = "CADET"
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    HEAVY = "HEAVY"


class DriverStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LicenseType(str, Enum):
    RENTAL = "RENTAL"
    OWNER = "OWNER"


class KartStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    RETIRED = "RETIRED"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FINALIZED = "FINALIZED"
    CANCELLED = "CANCELLED"


class EntryStatus(str, Enum):
    ENTERED = "ENTERED"
    TECH_CHECK = "TECH_CHECK"
    TECH_FAILED = "TECH_FAILED"
    TECH_PASSED = "TECH_PASSED"
    GRID_LOCKED = "GRID_LOCKED"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class EntryType(str, Enum):
    RENTAL = "RENTAL"
    OWNER_DRIVER = "OWNER_DRIVER"


class FeeStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class SessionType(str, Enum):
    PRACTICE = "PRACTICE"
    QUALIFYING = "QUALIFYING"
    HEAT = "HEAT"
    MAIN = "MAIN"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SCORED = "SCORED"


class ResultStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    AMENDED = "AMENDED"
    FINAL = "FINAL"


class InspectionOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"


class PenaltyKind(str, Enum):
    NONE = "NONE"
    TIME_SECONDS = "TIME_SECONDS"
    DISQUALIFICATION = "DISQUALIFICATION"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PricingMode(str, Enum):
    FLAT = "FLAT"
    METERED = "METERED"


class UserRole(str, Enum):
    LEAGUE_ADMIN = "LeagueAdmin"
    RACE_DIRECTOR = "RaceDirector"
    STEWARD = "Steward"
    DRIVER = "Driver"


# PRD 2.4: primary resources carry id, created_at, updated_at and version.
class LeagueSeason(TypedDict, total=False):
    id: str
    name: str
    year: int
    drop_rounds: int
    points_scheme: List[int]
    fastest_lap_bonus_points: int
    status: str
    rounds_completed: int
    collected_fees_cents: int
    created_at: str
    updated_at: str
    version: int


class RaceClass(TypedDict, total=False):
    id: str
    season_id: str
    code: str
    min_age: int
    max_age: int
    min_combined_weight_kg: float
    entry_fee_cents: int
    rental_kart_allowed: bool
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    body_weight_kg: float
    license_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalKart(TypedDict, total=False):
    id: str
    fleet_number: str
    eligible_class_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RaceEvent(TypedDict, total=False):
    id: str
    season_id: str
    round_number: int
    event_date: str
    track_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EventEntry(TypedDict, total=False):
    id: str
    event_id: str
    driver_id: str
    class_id: str
    entry_type: str
    kart_id: Optional[str]
    status: str
    entry_fee_cents: int
    fee_status: str
    tech_fail_count: int
    event_points: int
    created_at: str
    updated_at: str
    version: int


class RaceSession(TypedDict, total=False):
    id: str
    event_id: str
    session_type: str
    sequence: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionResult(TypedDict, total=False):
    id: str
    session_id: str
    entry_id: str
    finish_position: int
    best_lap_ms: int
    total_time_ms: int
    penalty_seconds_applied: int
    is_fastest_lap: bool
    points_awarded: int
    status: str
    created_at: str
    updated_at: str
    version: int


# PRD 2.4: an inspection record is append-only and carries only id and
# created_at; updated_at and version are deliberately absent.
class TechInspection(TypedDict, total=False):
    id: str
    entry_id: str
    measured_combined_weight_kg: float
    outcome: str
    inspector_user_id: str
    notes: Optional[str]
    created_at: str


class Incident(TypedDict, total=False):
    id: str
    event_id: str
    entry_id: str
    session_id: str
    description: str
    reporter_user_id: str
    status: str
    penalty_kind: Optional[str]
    penalty_seconds: Optional[int]
    adjudicator_user_id: Optional[str]
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class PracticeBooking(TypedDict, total=False):
    id: str
    driver_id: str
    kart_id: str
    start_time: str
    end_time: str
    pricing_mode: str
    status: str
    minutes_used: Optional[int]
    fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StandingsRow(TypedDict, total=False):
    driver_id: str
    provisional_points: int
    final_points: int
    dropped_round_numbers: List[int]
    rank: int


class Standings(TypedDict, total=False):
    season_id: str
    class_id: str
    rows: List[StandingsRow]
