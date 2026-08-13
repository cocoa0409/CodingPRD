"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: every resource carries id + created_at; all resources except birth
records additionally carry updated_at and version. A birth record carries only
id and created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    RANCH_MANAGER = "RanchManager"
    RANGE_HAND = "RangeHand"
    WOOL_POOL_OPERATOR = "WoolPoolOperator"
    GRAZING_CLIENT = "GrazingClient"
    PLATFORM_ADMIN = "PlatformAdmin"


class Species(str, Enum):
    SHEEP = "SHEEP"
    GOAT = "GOAT"


class FlockStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SeasonStatus(str, Enum):
    PLANNED = "PLANNED"
    BREEDING = "BREEDING"
    GESTATION = "GESTATION"
    LAMBING = "LAMBING"
    WEANING = "WEANING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PastureStatus(str, Enum):
    OCCUPIED = "OCCUPIED"
    RESTING = "RESTING"
    AVAILABLE = "AVAILABLE"


class MoveStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CrewStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ShearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MarketingPosture(str, Enum):
    UNGRADED = "UNGRADED"
    GRADING = "GRADING"
    MARKETING = "MARKETING"
    SETTLED_OUT = "SETTLED_OUT"


class GradeCode(str, Enum):
    SUPERFINE = "SUPERFINE"
    FINE = "FINE"
    MEDIUM = "MEDIUM"
    STRONG = "STRONG"
    COARSE = "COARSE"


class LotStatus(str, Enum):
    DRAFT = "DRAFT"
    GRADED = "GRADED"
    REGRADING = "REGRADING"
    CONSIGNED = "CONSIGNED"
    SOLD = "SOLD"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class CoreTestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RESULTED = "RESULTED"
    LOCKED = "LOCKED"
    REJECTED = "REJECTED"


class ConsignmentStatus(str, Enum):
    TENDERED = "TENDERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ADVANCED = "ADVANCED"
    SOLD = "SOLD"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class SaleType(str, Enum):
    MEAT = "MEAT"
    BREEDING = "BREEDING"


class Channel(str, Enum):
    AUCTION = "AUCTION"
    DIRECT = "DIRECT"
    ETHNIC_MARKET = "ETHNIC_MARKET"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PredatorType(str, Enum):
    COYOTE = "COYOTE"
    MOUNTAIN_LION = "MOUNTAIN_LION"
    BEAR = "BEAR"
    DOG = "DOG"
    EAGLE = "EAGLE"
    UNKNOWN = "UNKNOWN"


class ReportStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    DISMISSED = "DISMISSED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Flock(TypedDict, total=False):
    id: str
    flock_name: str
    species: str
    flock_status: str
    baseline_headcount: int
    guardian_dog_count: int
    current_headcount: int
    withdrawal_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BreedingSeason(TypedDict, total=False):
    id: str
    flock_id: str
    season_label: str
    ewes_bred: int
    breeding_start_date: str
    breeding_end_date: str
    expected_lambing_start: str
    season_status: str
    total_born: int
    total_born_alive: int
    lambing_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class BirthRecord(TypedDict, total=False):
    # PRD §2.4: a birth record carries only id and created_at; no updated_at,
    # no version (never modified after it is logged).
    id: str
    season_id: str
    birth_date: str
    births_reported: int
    born_alive: int
    born_dead: int
    recorded_by_user_id: str
    created_at: str


class Pasture(TypedDict, total=False):
    id: str
    pasture_name: str
    acres: float
    carrying_capacity_head: int
    rest_days: int
    occupied_head_count: int
    pasture_status: str
    created_at: str
    updated_at: str
    version: int


class GrazingMove(TypedDict, total=False):
    id: str
    flock_id: str
    pasture_id: Optional[str]
    contract_id: Optional[str]
    move_start: str
    move_end: str
    head_count: int
    move_status: str
    created_at: str
    updated_at: str
    version: int


class ParasiteTreatment(TypedDict, total=False):
    id: str
    flock_id: str
    product_name: str
    treatment_date: str
    withdrawal_days: int
    withdrawal_until: str
    fecal_egg_count_before: int
    fecal_egg_count_after: Optional[int]
    efficacy_pct: Optional[float]
    resistance_flag: bool
    created_at: str
    updated_at: str
    version: int


class ShearingCrew(TypedDict, total=False):
    id: str
    crew_name: str
    crew_status: str
    head_per_day_capacity: int
    daily_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class ShearingEvent(TypedDict, total=False):
    id: str
    flock_id: str
    crew_id: str
    scheduled_start: str
    scheduled_end: str
    expected_head: int
    shearing_status: str
    shorn_head_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class WoolClip(TypedDict, total=False):
    id: str
    shearing_event_id: str
    flock_id: str
    greasy_weight_lbs: float
    skirtings_weight_lbs: float
    allocated_weight_lbs: float
    unallocated_weight_lbs: float
    clip_value_cents: int
    marketing_posture: str
    created_at: str
    updated_at: str
    version: int


class WoolLot(TypedDict, total=False):
    id: str
    clip_id: str
    lot_code: str
    weight_lbs: float
    estimated_micron: float
    certified_micron: Optional[float]
    certified_yield_pct: Optional[float]
    effective_micron: float
    grade_code: str
    lot_status: str
    provisional_value_cents: int
    certified_value_cents: Optional[int]
    effective_value_cents: int
    created_at: str
    updated_at: str
    version: int


class CoreTest(TypedDict, total=False):
    id: str
    lot_id: str
    lab_ref: str
    test_status: str
    measured_micron: Optional[float]
    clean_yield_pct: Optional[float]
    vegetable_matter_pct: Optional[float]
    submitted_by_user_id: str
    locked_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Consignment(TypedDict, total=False):
    id: str
    lot_id: str
    pool_ref: str
    consignment_status: str
    advance_cents: int
    sale_gross_cents: Optional[int]
    pool_fee_cents: Optional[int]
    settlement_cents: Optional[int]
    pending_clawback_cents: int
    clawback_cents: int
    created_at: str
    updated_at: str
    version: int


class HolidayWindow(TypedDict, total=False):
    id: str
    holiday_name: str
    window_start: str
    window_end: str
    premium_pct: float
    min_head: int
    created_at: str
    updated_at: str
    version: int


class LivestockSale(TypedDict, total=False):
    id: str
    flock_id: str
    sale_type: str
    channel: str
    head_count: int
    avg_weight_lbs: Optional[float]
    base_price_per_cwt_cents: Optional[int]
    per_head_price_cents: Optional[int]
    shrink_pct: float
    scheduled_date: str
    payment_status: str
    delivery_status: str
    booked_price_cents: int
    applied_holiday_name: Optional[str]
    premium_pct_applied: float
    actual_total_weight_lbs: Optional[float]
    actual_head_delivered: Optional[int]
    settled_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LossReport(TypedDict, total=False):
    id: str
    flock_id: str
    loss_date: str
    head_lost: int
    predator_type: str
    guardian_on_duty: bool
    report_status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrazingContract(TypedDict, total=False):
    id: str
    flock_id: str
    client_org_name: str
    parcel_name: str
    service_window_start: str
    service_window_end: str
    rate_per_head_day_cents: int
    min_head: int
    max_head: int
    target_cover_reduction_pct: float
    terms_version: int
    contract_status: str
    breach_flag: bool
    achieved_cover_reduction_pct: Optional[float]
    head_days: Optional[int]
    invoice_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PoolStatement(TypedDict, total=False):
    pool_ref: str
    consignment_count: int
    total_sale_gross_cents: int
    total_pool_fee_cents: int
    total_advance_cents: int
    total_settlement_cents: int
