"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class EventLifecycle(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_LOCKED = "REGISTRATION_LOCKED"
    JUDGING = "JUDGING"
    TABULATING = "TABULATING"
    FINALIZED = "FINALIZED"
    CLOSED = "CLOSED"


class WeatherPosture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"


class SoundPermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TabulationMethod(str, Enum):
    STRAIGHT_AVERAGE = "STRAIGHT_AVERAGE"
    DROP_EXTREMES = "DROP_EXTREMES"


class JudgingMode(str, Enum):
    JUDGED = "JUDGED"
    PEOPLES_CHOICE = "PEOPLES_CHOICE"
    BOTH = "BOTH"


class ZoneType(str, Enum):
    SHOW_FIELD = "SHOW_FIELD"
    OVERFLOW = "OVERFLOW"
    VENDOR_ROW = "VENDOR_ROW"


class RegistrationStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    REFUND_REQUESTED = "REFUND_REQUESTED"
    REFUNDED = "REFUNDED"
    NO_SHOW = "NO_SHOW"


class PricingTier(str, Enum):
    PREREG = "PREREG"
    DAY_OF = "DAY_OF"


class PaymentKind(str, Enum):
    ENTRY_FEE = "ENTRY_FEE"
    BOOTH_FEE = "BOOTH_FEE"
    REFUND = "REFUND"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    CHECK = "CHECK"


class PaymentStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"


class BoothStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    ASSIGNED = "ASSIGNED"
    CANCELLED = "CANCELLED"


class BoothTier(str, Enum):
    SINGLE = "SINGLE"
    DOUBLE = "DOUBLE"
    SPONSOR = "SPONSOR"


class ScoreSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"


class Criterion(str, Enum):
    EXTERIOR = "EXTERIOR"
    INTERIOR = "INTERIOR"
    ENGINE = "ENGINE"
    AUTHENTICITY = "AUTHENTICITY"
    CONDITION = "CONDITION"


class BallotStatus(str, Enum):
    VALID = "VALID"
    VOID = "VOID"


class AwardKind(str, Enum):
    CLASS_PLACE = "CLASS_PLACE"
    PEOPLES_CHOICE = "PEOPLES_CHOICE"
    BEST_OF_SHOW = "BEST_OF_SHOW"


class AwardStatus(str, Enum):
    PENDING = "PENDING"
    COMPUTED = "COMPUTED"
    FINALIZED = "FINALIZED"
    PRESENTED = "PRESENTED"


class NoiseSource(str, Enum):
    STAGE = "STAGE"
    PA_SYSTEM = "PA_SYSTEM"
    EXHAUST = "EXHAUST"
    CROWD = "CROWD"


class SoundSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class UserRole(str, Enum):
    ORGANIZER = "Organizer"
    REGISTRATION_DESK = "RegistrationDesk"
    PARTICIPANT = "Participant"
    JUDGE = "Judge"
    VENDOR = "Vendor"


# --- Entity TypedDicts (common_fields: true -> id + created_at + updated_at + version) ---

class Event(TypedDict, total=False):
    id: str
    name: str
    event_date: str
    gates_open_at: str
    judging_start_at: str
    judging_end_at: str
    ballot_close_at: str
    prereg_deadline: str
    curfew_start: str
    curfew_end: str
    liability_policy_number: str
    tabulation_method: str
    lifecycle_status: str
    weather_posture: str
    sound_permit_status: str
    treasury_cents: int
    noise_exceedance_count: int
    finalized_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ShowClass(TypedDict, total=False):
    id: str
    event_id: str
    code: str
    name: str
    min_year: int
    max_year: int
    prereg_fee_cents: int
    day_of_fee_cents: int
    capacity: int
    judging_mode: str
    award_depth: int
    confirmed_count: int
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    zone_type: str
    capacity: int
    has_power: bool
    arrival_window_start: Optional[str]
    arrival_window_end: Optional[str]
    assigned_count: int
    created_at: str
    updated_at: str
    version: int


class Registrant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    club_member: bool
    is_minor: bool
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    registrant_id: str
    year: int
    make: str
    model: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    event_id: str
    registrant_id: str
    vehicle_id: str
    class_id: str
    pricing_tier: str
    fee_cents: int
    status: str
    paid_cents: int
    refunded_cents: int
    assigned_zone_id: Optional[str]
    spot_number: Optional[int]
    checked_in_at: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger rows (common_fields: false -> only id + created_at) ---

class Payment(TypedDict, total=False):
    id: str
    created_at: str
    registration_id: Optional[str]
    booth_application_id: Optional[str]
    kind: str
    amount_cents: int
    method: str
    status: str
    recorded_by_user_id: str


class Waiver(TypedDict, total=False):
    id: str
    created_at: str
    event_id: str
    registrant_id: str
    signature_name: str
    guardian_name: Optional[str]
    signed_at: str


class NoiseReading(TypedDict, total=False):
    id: str
    created_at: str
    event_id: str
    recorded_at: str
    reading_db: float
    source: str
    is_curfew: bool
    limit_db: float
    is_exceedance: bool


class BoothApplication(TypedDict, total=False):
    id: str
    event_id: str
    business_name: str
    contact_email: str
    booth_tier: str
    power_requested: bool
    status: str
    fee_cents: int
    paid_cents: int
    assigned_zone_id: Optional[str]
    assigned_spaces: List[int]
    created_at: str
    updated_at: str
    version: int


class Judge(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    email: str
    assigned_class_ids: List[str]
    submitted_sheet_count: int
    created_at: str
    updated_at: str
    version: int


class ScoreSheet(TypedDict, total=False):
    id: str
    judge_id: str
    registration_id: str
    criteria_scores: List[Any]
    sheet_total: float
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ballot(TypedDict, total=False):
    id: str
    event_id: str
    registration_id: str
    voter_registrant_id: str
    weight: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    event_id: str
    class_id: Optional[str]
    award_kind: str
    place: Optional[int]
    status: str
    winner_registration_id: Optional[str]
    winner_score: Optional[float]
    tie_break_log: str
    overridden: bool
    created_at: str
    updated_at: str
    version: int


class SoundSlot(TypedDict, total=False):
    id: str
    event_id: str
    performer_name: str
    slot_start: str
    slot_end: str
    expected_db: float
    status: str
    created_at: str
    updated_at: str
    version: int
