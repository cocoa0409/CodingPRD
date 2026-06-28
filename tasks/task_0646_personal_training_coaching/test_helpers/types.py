"""Domain types: entity TypedDicts, status enums, and the role enum.

All names and fields mirror the PRD's resource definitions (§2.4, §3).
"""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Status / enum value sets ─────────────────────────────────────────────────

class TrainerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class IntakeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ASSESSED = "ASSESSED"


class BookingPrivilege(str, Enum):
    ALLOWED = "ALLOWED"
    SUSPENDED = "SUSPENDED"


class BillingModel(str, Enum):
    SESSION_PACK = "SESSION_PACK"
    ONLINE_SUBSCRIPTION = "ONLINE_SUBSCRIPTION"


class EngagementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class PauseReason(str, Enum):
    NONE = "NONE"
    PACK_DEPLETED = "PACK_DEPLETED"
    MANUAL = "MANUAL"


class SessionPackStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    REFUNDED = "REFUNDED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    LATE_CANCELLED = "LATE_CANCELLED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"


class ProgramAssignmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class MacroPlanStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    LOCKED = "LOCKED"


class CheckInStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ASSESSED = "ASSESSED"


class Sex(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class MacroGoal(str, Enum):
    FAT_LOSS = "FAT_LOSS"
    MAINTENANCE = "MAINTENANCE"
    MUSCLE_GAIN = "MUSCLE_GAIN"


class ActivityLevel(str, Enum):
    SEDENTARY = "SEDENTARY"
    MODERATE = "MODERATE"
    ACTIVE = "ACTIVE"


class HabitKind(str, Enum):
    WORKOUT_COMPLETED = "WORKOUT_COMPLETED"
    NUTRITION_LOGGED = "NUTRITION_LOGGED"
    HABIT_CHECK = "HABIT_CHECK"


class SenderRole(str, Enum):
    TRAINER = "TRAINER"
    CLIENT = "CLIENT"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    TRAINER = "Trainer"
    CLIENT = "Client"


# ─── Full resources (carry id + created_at + updated_at + version) ────────────

class Trainer(TypedDict):
    id: str
    full_name: str
    email: str
    timezone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    trainer_id: str
    full_name: str
    email: str
    sex: str
    birth_year: int
    height_cm: float
    intake_status: str
    latest_weight_kg: Optional[float]
    no_show_strikes: int
    booking_privilege: str
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    client_id: str
    trainer_id: str
    billing_model: str
    status: str
    wallet_credit_cents: int
    pause_reason: str
    created_at: str
    updated_at: str
    version: int


class SessionPack(TypedDict):
    id: str
    engagement_id: str
    total_sessions: int
    price_cents: int
    per_session_value_cents: int
    sessions_committed: int
    sessions_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    engagement_id: str
    session_pack_id: Optional[str]
    trainer_id: str
    start_utc: str
    end_utc: str
    rescheduled_from_booking_id: Optional[str]
    fee_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramAssignment(TypedDict):
    id: str
    engagement_id: str
    title: str
    planned_workouts_per_week: int
    habit_checks_target: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MacroPlan(TypedDict):
    id: str
    engagement_id: str
    goal: str
    activity_level: str
    snapshot_weight_kg: Optional[float]
    target_calories: int
    protein_g: int
    carb_g: int
    fat_g: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CheckIn(TypedDict):
    id: str
    engagement_id: str
    measured_at: str
    weight_kg: float
    photo_urls: List[str]
    window_start_utc: str
    window_end_utc: str
    adherence_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only event records (carry only id + created_at) ───────────────────

class HabitLog(TypedDict):
    id: str
    engagement_id: str
    program_assignment_id: str
    kind: str
    logged_at: str
    created_at: str


class Message(TypedDict):
    id: str
    engagement_id: str
    sender_role: str
    body: str
    created_at: str
