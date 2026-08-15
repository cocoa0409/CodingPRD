"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class SeasonStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    HARVEST_CLOSED = "HARVEST_CLOSED"
    SETTLED = "SETTLED"


class MemberStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class QuotaPosture(str, Enum):
    WITHIN_QUOTA = "WITHIN_QUOTA"
    OVER_QUOTA = "OVER_QUOTA"


class BogStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENOVATION_PLANNED = "RENOVATION_PLANNED"
    UNDER_RENOVATION = "UNDER_RENOVATION"
    REPLANTED = "REPLANTED"


class BogVariety(str, Enum):
    STEVENS = "STEVENS"
    BEN_LEAR = "BEN_LEAR"
    MULICA_QUEEN = "MULICA_QUEEN"
    EARLY_BLACK = "EARLY_BLACK"


class EstimateStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    FLAGGED = "FLAGGED"


class TicketMethod(str, Enum):
    WET = "WET"
    DRY = "DRY"


class TicketStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class FrostEventStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PoolCode(str, Enum):
    MAIN = "MAIN"
    OVER_QUOTA = "OVER_QUOTA"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECEIVED = "RECEIVED"
    GRADED = "GRADED"
    DISPUTED = "DISPUTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class Grade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    REJECT = "REJECT"


class DistributionStatus(str, Enum):
    COMPUTED = "COMPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class UserRole(str, Enum):
    COOP_ADMIN = "CoopAdmin"
    GROWER_MEMBER = "GrowerMember"
    FIELD_OFFICER = "FieldOfficer"
    STATION_OPERATOR = "StationOperator"
    POOL_MANAGER = "PoolManager"


# All resources carry the four system-managed properties of PRD §2.4:
# id, created_at, updated_at, version.

class Season(TypedDict):
    id: str
    year: int
    harvest_window_start: str
    harvest_window_end: str
    baseline_barrels_per_acre: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    member_code: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MemberQuota(TypedDict):
    id: str
    member_id: str
    season_id: str
    base_quota_barrels: float
    baseline_quota_barrels: float
    base_quota_override: Optional[float]
    delivered_barrels: float
    over_quota_barrels: float
    posture: str
    quota_locked: bool
    created_at: str
    updated_at: str
    version: int


class Bog(TypedDict):
    id: str
    member_id: str
    name: str
    acres: float
    variety: str
    sprinkler_demand_gpm: int
    frost_damage_threshold_c: float
    status: str
    created_at: str
    updated_at: str
    version: int


class YieldEstimate(TypedDict):
    id: str
    bog_id: str
    season_id: str
    member_id: str
    estimated_barrels: float
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReceivingStation(TypedDict):
    id: str
    name: str
    daily_capacity_barrels: int
    created_at: str
    updated_at: str
    version: int


class HarvestTicket(TypedDict):
    id: str
    bog_id: str
    season_id: str
    member_id: str
    method: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FrostEvent(TypedDict):
    id: str
    bog_id: str
    season_id: str
    window_start: str
    window_end: str
    forecast_min_temp_c: float
    actual_min_temp_c: Optional[float]
    damage_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Pool(TypedDict):
    id: str
    season_id: str
    code: str
    provisional_advance_rate_per_barrel: float
    retain_pct: float
    status: str
    accepted_net_barrels: float
    weighted_barrels_total: float
    advances_outstanding: float
    realized_revenue: Optional[float]
    operating_costs: Optional[float]
    final_rate_per_weighted_barrel: Optional[float]
    coop_equity_residual: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict):
    id: str
    member_id: str
    season_id: str
    bog_id: str
    receiving_station_id: str
    harvest_ticket_id: Optional[str]
    scheduled_date: str
    expected_barrels: float
    gross_barrels: Optional[float]
    tare_barrels: Optional[float]
    net_barrels: Optional[float]
    color_score: Optional[float]
    firmness_score: Optional[float]
    foreign_matter_pct: Optional[float]
    grade: Optional[str]
    premium_multiplier: Optional[float]
    weighted_barrels: Optional[float]
    quota_applied_barrels: Optional[float]
    over_quota_barrels: Optional[float]
    main_pool_id: Optional[str]
    over_quota_pool_id: Optional[str]
    advance_amount: Optional[float]
    dispute_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PatronageDistribution(TypedDict):
    id: str
    pool_id: str
    member_id: str
    weighted_barrels: float
    advance_paid: float
    gross_amount: float
    retain_amount: float
    cash_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int
