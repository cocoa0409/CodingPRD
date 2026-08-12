"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCTION_MANAGER = "ProductionManager"
    CASTING_DIRECTOR = "CastingDirector"
    CONTRACTS_OFFICER = "ContractsOfficer"
    TECHNICAL_DIRECTOR = "TechnicalDirector"
    BOX_OFFICE_MANAGER = "BoxOfficeManager"
    PARTNER_REPRESENTATIVE = "PartnerRepresentative"
    ANY = "Any"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class PartnerKind(str, Enum):
    CO_PRODUCER = "CO_PRODUCER"
    RENTER = "RENTER"


class PartnerStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    BARRED = "BARRED"


class ProductionStatus(str, Enum):
    DESIGN = "DESIGN"
    BUILD = "BUILD"
    REHEARSAL = "REHEARSAL"
    IN_REPERTORY = "IN_REPERTORY"
    ARCHIVED = "ARCHIVED"


class WorkType(str, Enum):
    OPERA = "OPERA"
    BALLET = "BALLET"


class BuildItemStatus(str, Enum):
    ORDERED = "ORDERED"
    BUILT = "BUILT"
    DELIVERED = "DELIVERED"
    IN_USE = "IN_USE"
    CANCELLED = "CANCELLED"


class ItemKind(str, Enum):
    SET = "SET"
    COSTUME = "COSTUME"
    PROP = "PROP"


class ShareStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RATIFIED = "RATIFIED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class CostSplitMethod(str, Enum):
    GROSS_COST = "GROSS_COST"
    NET_REVENUE_SHARE = "NET_REVENUE_SHARE"


class Discipline(str, Enum):
    PRINCIPAL_DANCER = "PRINCIPAL_DANCER"
    CORPS_DANCER = "CORPS_DANCER"
    SOPRANO = "SOPRANO"
    TENOR = "TENOR"
    CHORUS = "CHORUS"
    ORCHESTRA = "ORCHESTRA"


class UnionCode(str, Enum):
    AGMA = "AGMA"
    AFM = "AFM"
    EQUITY = "EQUITY"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"
    TERMINATED = "TERMINATED"


class EngagementType(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    COVER = "COVER"
    CHORUS = "CHORUS"
    ORCHESTRA = "ORCHESTRA"


class VoiceType(str, Enum):
    SOPRANO = "SOPRANO"
    MEZZO = "MEZZO"
    TENOR = "TENOR"
    BARITONE = "BARITONE"
    BASS = "BASS"
    DANCER_M = "DANCER_M"
    DANCER_F = "DANCER_F"
    NON_SINGING = "NON_SINGING"


class CastingStatus(str, Enum):
    UNFILLED = "UNFILLED"
    PRINCIPAL_SET = "PRINCIPAL_SET"
    FULLY_CAST = "FULLY_CAST"


class CastSlot(str, Enum):
    PRINCIPAL = "PRINCIPAL"
    COVER_1 = "COVER_1"
    COVER_2 = "COVER_2"


class CastAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class RoomKind(str, Enum):
    STUDIO = "STUDIO"
    STAGE = "STAGE"
    ORCHESTRA_PIT = "ORCHESTRA_PIT"


class CallType(str, Enum):
    BLOCKING = "BLOCKING"
    STAGING = "STAGING"
    ORCHESTRA_READ = "ORCHESTRA_READ"
    DANCE_CALL = "DANCE_CALL"
    TECH = "TECH"
    DRESS = "DRESS"


class RehearsalCallStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ParticipantStatus(str, Enum):
    INVITED = "INVITED"
    WAIVER_PENDING = "WAIVER_PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    DECLINED = "DECLINED"
    REMOVED = "REMOVED"


class SlotType(str, Enum):
    LOAD_IN = "LOAD_IN"
    LOAD_OUT = "LOAD_OUT"
    TECH = "TECH"
    PERFORMANCE_SLOT = "PERFORMANCE_SLOT"
    DRESS_ON_STAGE = "DRESS_ON_STAGE"


class StageSlotStatus(str, Enum):
    PLANNED = "PLANNED"
    LOCKED = "LOCKED"
    DONE = "DONE"
    CANCELLED = "CANCELLED"


class LifecycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SalesStatus(str, Enum):
    NOT_ON_SALE = "NOT_ON_SALE"
    ON_SALE = "ON_SALE"
    SALES_CLOSED = "SALES_CLOSED"


class ReadinessStatus(str, Enum):
    AWAITING_TECH = "AWAITING_TECH"
    TECH_READY = "TECH_READY"
    CLEARED_FOR_AUDIENCE = "CLEARED_FOR_AUDIENCE"


class Section(str, Enum):
    STALLS = "STALLS"
    BALCONY = "BALCONY"
    BOX = "BOX"
    GALLERY = "GALLERY"


class SurtitleStatus(str, Enum):
    DRAFT = "DRAFT"
    TRANSLATED = "TRANSLATED"
    CUES_LOCKED = "CUES_LOCKED"
    LIVE = "LIVE"


class RentalOfferStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class PayQuoteMode(str, Enum):
    PROJECTED = "PROJECTED"
    FINAL = "FINAL"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all sixteen resource types share the four
# system-managed properties of PRD §2.4 (id, created_at, updated_at, version).
# ---------------------------------------------------------------------------
class PartnerCompany(TypedDict, total=False):
    id: str
    name: str
    partner_kind: str
    standing: str
    created_at: str
    updated_at: str
    version: int


class Production(TypedDict, total=False):
    id: str
    title: str
    work_type: str
    build_budget_cents: int
    default_surtitle_language: str
    build_cost_balance_cents: int
    season_revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildItem(TypedDict, total=False):
    id: str
    production_id: str
    item_kind: str
    name: str
    quoted_cost_cents: int
    actual_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoProductionShare(TypedDict, total=False):
    id: str
    production_id: str
    company_id: str
    share_percentage: float
    cost_split_method: str
    accrued_revenue_share_cents: int
    settlement_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict, total=False):
    id: str
    full_name: str
    discipline: str
    union_code: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    production_id: str
    artist_id: str
    engagement_type: str
    hourly_rate_cents: int
    weekly_hours_cap: int
    rest_floor_hours: int
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Role(TypedDict, total=False):
    id: str
    production_id: str
    role_name: str
    voice_type: str
    is_title_role: bool
    casting_status: str
    created_at: str
    updated_at: str
    version: int


class CastAssignment(TypedDict, total=False):
    id: str
    production_id: str
    role_id: str
    contract_id: str
    slot: str
    covers_assignment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RehearsalRoom(TypedDict, total=False):
    id: str
    name: str
    kind: str
    capacity: int
    hourly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class RehearsalCall(TypedDict, total=False):
    id: str
    production_id: str
    room_id: str
    call_type: str
    starts_at: str
    ends_at: str
    required_headcount: int
    confirmed_headcount: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CallParticipant(TypedDict, total=False):
    id: str
    call_id: str
    contract_id: str
    waive_rest_floor: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StageSlot(TypedDict, total=False):
    id: str
    production_id: str
    slot_type: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Performance(TypedDict, total=False):
    id: str
    production_id: str
    starts_at: str
    ends_at: str
    lifecycle_status: str
    sales_status: str
    readiness_status: str
    realized_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class SeatInventory(TypedDict, total=False):
    id: str
    performance_id: str
    section: str
    total_seats: int
    seats_held: int
    seats_sold: int
    base_price_cents: int
    current_price_cents: int
    created_at: str
    updated_at: str
    version: int


class SurtitleTrack(TypedDict, total=False):
    id: str
    production_id: str
    language: str
    cue_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalOffer(TypedDict, total=False):
    id: str
    production_id: str
    renter_company_id: str
    window_start: str
    window_end: str
    performances_count: int
    per_performance_fee_cents: int
    fee_base_cents: int
    surcharge_pct: int
    total_fee_cents: int
    countered_fee_cents: Optional[int]
    final_settlement_cents: Optional[int]
    negotiation_rounds: int
    created_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PayQuote(TypedDict, total=False):
    projected_hours: float
    final_hours: float
    projected_pay_cents: int
    final_pay_cents: int


class PriceQuote(TypedDict, total=False):
    unit_price_cents: int
    demand_multiplier: float
    group_discount_applied: bool
    total_price_cents: int
