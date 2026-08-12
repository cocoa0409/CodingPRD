"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class SeasonStatus(str, Enum):
    PLANNING = "PLANNING"
    BUILD = "BUILD"
    OPEN = "OPEN"
    STRIKE = "STRIKE"
    CLOSED = "CLOSED"


class ReadinessPosture(str, Enum):
    BLOCKED = "BLOCKED"
    CONDITIONAL = "CONDITIONAL"
    READY = "READY"


class FaireDayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN_FOR_SALES = "OPEN_FOR_SALES"
    WEATHER_HOLD = "WEATHER_HOLD"
    OPERATING = "OPERATING"
    COMPLETED = "COMPLETED"
    CANCELLED_WEATHER = "CANCELLED_WEATHER"


class ActType(str, Enum):
    MUSIC = "MUSIC"
    COMBAT = "COMBAT"
    COMEDY = "COMEDY"
    ACROBATICS = "ACROBATICS"
    ROVING = "ROVING"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REHEARSING = "REHEARSING"
    PERFORMING = "PERFORMING"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class SlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class VendorCategory(str, Enum):
    FOOD = "FOOD"
    BEVERAGE = "BEVERAGE"
    ARTISAN = "ARTISAN"
    GAMES = "GAMES"


class ApplicationStatus(str, Enum):
    JURY_REVIEW = "JURY_REVIEW"
    JURIED_IN = "JURIED_IN"
    JURIED_OUT = "JURIED_OUT"
    WAITLISTED = "WAITLISTED"
    APPEALED = "APPEALED"
    WITHDRAWN = "WITHDRAWN"


class LocationTier(str, Enum):
    PRIME = "PRIME"
    STANDARD = "STANDARD"
    MEADOW = "MEADOW"


class BoothStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    SUSPENDED = "SUSPENDED"
    RELEASED = "RELEASED"
    SETTLED = "SETTLED"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    AWAITING_REINSPECTION = "AWAITING_REINSPECTION"
    FAILED_FINAL = "FAILED_FINAL"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class OrderType(str, Enum):
    DAY = "DAY"
    SEASON = "SEASON"
    GROUP = "GROUP"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class RedemptionStatus(str, Enum):
    UNREDEEMED = "UNREDEEMED"
    PARTIALLY_REDEEMED = "PARTIALLY_REDEEMED"
    FULLY_REDEEMED = "FULLY_REDEEMED"
    RAINCHECKED = "RAINCHECKED"
    VOID = "VOID"


class TicketType(str, Enum):
    DAY = "DAY"
    SEASON = "SEASON"


class TicketStatus(str, Enum):
    VALID = "VALID"
    REDEEMED = "REDEEMED"
    RAINCHECKED = "RAINCHECKED"
    VOID = "VOID"
    EXPIRED = "EXPIRED"


class RainCheckStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class VolunteerRole(str, Enum):
    GATE = "GATE"
    PARKING = "PARKING"
    TAVERN = "TAVERN"
    INFO = "INFO"
    BACKSTAGE = "BACKSTAGE"


class ShiftStatus(str, Enum):
    SIGNED_UP = "SIGNED_UP"
    CONFIRMED = "CONFIRMED"
    WORKED = "WORKED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class CaseCategory(str, Enum):
    COSTUME_POLICY = "COSTUME_POLICY"
    WEAPON_UNTIED = "WEAPON_UNTIED"
    BEHAVIOR = "BEHAVIOR"
    VENDOR_CONDUCT = "VENDOR_CONDUCT"


class CaseStatus(str, Enum):
    REPORTED = "REPORTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class Sanction(str, Enum):
    NONE = "NONE"
    BAN_GUEST = "BAN_GUEST"
    REVOKE_PERMIT = "REVOKE_PERMIT"


class TaskPhase(str, Enum):
    BUILD = "BUILD"
    STRIKE = "STRIKE"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class UserRole(str, Enum):
    FAIRE_OPERATOR = "FaireOperator"
    CAST_DIRECTOR = "CastDirector"
    VENDOR_COORDINATOR = "VendorCoordinator"
    GATE_AGENT = "GateAgent"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    PERFORMER = "Performer"
    VENDOR = "Vendor"
    VOLUNTEER = "Volunteer"
    GUEST = "Guest"
    ANY = "Any"


class Season(TypedDict, total=False):
    id: str
    name: str
    status: str
    readiness_posture: str
    opening_date: str
    closing_date: str
    daily_capacity: int
    group_min_size: int
    volunteer_min_hours: float
    weather_call_deadline_hour: int
    rain_check_grace_days: int
    volunteer_confirmed_hours: float
    outstanding_admissions: int
    season_weeks: int
    created_at: str
    updated_at: str
    version: int


class FaireDay(TypedDict, total=False):
    id: str
    season_id: str
    date: str
    status: str
    tickets_sold_count: int
    created_at: str
    updated_at: str
    version: int


class Performer(TypedDict, total=False):
    id: str
    stage_name: str
    act_type: str
    base_day_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class CastContract(TypedDict, total=False):
    id: str
    season_id: str
    performer_id: str
    status: str
    offered_day_rate_cents: int
    countered_day_rate_cents: Optional[int]
    guaranteed_days: int
    weather_pay_pct: float
    required_rehearsal_hours: float
    completed_rehearsal_hours: float
    negotiation_round: int
    accrued_payout_cents: int
    final_payout_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RehearsalSlot(TypedDict, total=False):
    id: str
    contract_id: str
    stage_name: str
    start_time: str
    end_time: str
    status: str
    hours_credit: float
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    business_name: str
    category: str
    created_at: str
    updated_at: str
    version: int


class VendorApplication(TypedDict, total=False):
    id: str
    season_id: str
    vendor_id: str
    status: str
    booth_size_sqft: int
    requested_location_tier: str
    craft_score: float
    authenticity_score: float
    safety_score: float
    jury_score: Optional[float]
    appeal_used: bool
    created_at: str
    updated_at: str
    version: int


class BoothAssignment(TypedDict, total=False):
    id: str
    season_id: str
    application_id: str
    booth_site: str
    residency_start_date: str
    residency_end_date: str
    status: str
    provisional_fee_cents: int
    weather_credit_cents: int
    final_fee_cents: Optional[int]
    settlement_delta_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FoodPermit(TypedDict, total=False):
    id: str
    application_id: str
    status: str
    permit_number: Optional[str]
    inspection_attempts: int
    expiry_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TicketOrder(TypedDict, total=False):
    id: str
    season_id: str
    buyer_email: str
    order_type: str
    quantity: int
    faire_day_id: Optional[str]
    unit_price_cents: int
    discount_pct: float
    total_cents: int
    refunded_cents: int
    retained_cents: int
    payment_status: str
    redemption_status: str
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict, total=False):
    id: str
    order_id: str
    faire_day_id: Optional[str]
    ticket_type: str
    status: str
    redeemed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RainCheck(TypedDict, total=False):
    id: str
    season_id: str
    ticket_id: str
    issued_for_day_id: str
    status: str
    redeem_by_date: str
    redeemed_on_day_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VolunteerShift(TypedDict, total=False):
    id: str
    season_id: str
    faire_day_id: str
    volunteer_handle: str
    role: str
    start_time: str
    end_time: str
    status: str
    hours: float
    created_at: str
    updated_at: str
    version: int


class ConductCase(TypedDict, total=False):
    id: str
    season_id: str
    category: str
    subject_description: str
    linked_order_id: Optional[str]
    linked_permit_id: Optional[str]
    status: str
    sanction: str
    created_at: str
    updated_at: str
    version: int


class BuildTask(TypedDict, total=False):
    id: str
    season_id: str
    phase: str
    name: str
    status: str
    depends_on_task_ids: list
    created_at: str
    updated_at: str
    version: int
