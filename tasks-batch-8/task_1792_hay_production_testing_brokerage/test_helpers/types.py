"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BROKER_OPS = "BrokerOps"
    GROWER = "Grower"
    BUYER = "Buyer"
    LAB_TECHNICIAN = "LabTechnician"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class GrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BuyerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CuttingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    WINDOW_OPEN = "WINDOW_OPEN"
    CUT = "CUT"
    HARVESTED = "HARVESTED"
    ABANDONED = "ABANDONED"


class BaleLotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    CONDEMNED = "CONDEMNED"


class QualityTier(str, Enum):
    UNGRADED = "UNGRADED"
    SUPREME = "SUPREME"
    PREMIUM = "PREMIUM"
    GOOD = "GOOD"
    FAIR = "FAIR"


class ForageTestStatus(str, Enum):
    COLLECTED = "COLLECTED"
    SUBMITTED = "SUBMITTED"
    RESULTED = "RESULTED"
    CERTIFIED = "CERTIFIED"
    INVALIDATED = "INVALIDATED"


class DroughtRegime(str, Enum):
    STABLE = "STABLE"
    VOLATILE = "VOLATILE"
    DROUGHT = "DROUGHT"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    FULFILLED = "FULFILLED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class LogisticsStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


class LoadAllocationStatus(str, Enum):
    OPEN = "OPEN"
    DELIVERED = "DELIVERED"
    RELEASED = "RELEASED"
    SETTLED = "SETTLED"


class BalingServiceOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class ForageType(str, Enum):
    ALFALFA = "ALFALFA"
    GRASS = "GRASS"
    MIXED = "MIXED"


class BaleType(str, Enum):
    SMALL_SQUARE = "SMALL_SQUARE"
    LARGE_SQUARE = "LARGE_SQUARE"
    ROUND = "ROUND"


class SpoilageReason(str, Enum):
    MOLD = "MOLD"
    MOISTURE = "MOISTURE"
    PEST = "PEST"
    FIRE = "FIRE"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5: full bookkeeping resources carry
# id + created_at + updated_at + version; weather reports, spoilage events
# and market indices are append-only and carry ONLY id + created_at).
# ---------------------------------------------------------------------------

class Grower(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    status: str
    settled_tons_ytd: float
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict, total=False):
    id: str
    grower_id: str
    name: str
    acres: float
    forage_type: str
    irrigated: bool
    created_at: str
    updated_at: str
    version: int


class Cutting(TypedDict, total=False):
    id: str
    field_id: str
    cutting_number: int
    season_year: int
    planned_window_start: str
    planned_window_end: str
    actual_cut_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherReport(TypedDict, total=False):
    # Append-only (PRD §2.5): id + created_at ONLY — no updated_at, no version.
    id: str
    created_at: str
    region_code: str
    report_date: str
    precipitation_mm: float
    drying_index: int


class StorageSite(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    capacity_tons: float
    moisture_controlled: bool
    created_at: str
    updated_at: str
    version: int


class BaleLot(TypedDict, total=False):
    id: str
    cutting_id: str
    storage_site_id: str
    bale_type: str
    bale_count: int
    harvested_tonnage: float
    harvested_date: str
    quality_tier: str
    certified_protein_pct: Optional[float]
    shipped_tonnage: float
    spoilage_tonnage: float
    open_allocated_tonnage: float
    allocatable_tonnage: float
    physical_tonnage: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SpoilageEvent(TypedDict, total=False):
    # Append-only (PRD §2.5): id + created_at ONLY.
    id: str
    created_at: str
    bale_lot_id: str
    event_date: str
    tons_lost: float
    reason: str


class ForageTest(TypedDict, total=False):
    id: str
    bale_lot_id: str
    sample_date: str
    lab_reference: str
    rfv: Optional[float]
    protein_pct: Optional[float]
    moisture_pct: Optional[float]
    resulted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketIndex(TypedDict, total=False):
    # Append-only (PRD §2.5): id + created_at ONLY.
    id: str
    created_at: str
    region_code: str
    forage_type: str
    effective_date: str
    price_per_ton_cents: int
    drought_regime: str


class Buyer(TypedDict, total=False):
    id: str
    name: str
    region_code: str
    credit_limit_cents: int
    credit_used_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FreightLane(TypedDict, total=False):
    id: str
    origin_region_code: str
    dest_region_code: str
    distance_miles: int
    rate_per_mile_cents: int
    min_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    buyer_id: str
    forage_type: str
    quality_tier: str
    tons: float
    origin_region_code: str
    dest_region_code: str
    requested_delivery_by: str
    pinned_market_index_id: Optional[str]
    unit_price_cents: int
    commodity_cents: int
    freight_cents: int
    total_cents: int
    issued_at: Optional[str]
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    quote_id: str
    buyer_id: str
    quality_tier: str
    forage_type: str
    committed_tons: float
    unit_price_cents: int
    total_reserved_cents: int
    delivery_deadline: str
    delivered_tons: float
    open_allocated_tons: float
    remaining_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryLoad(TypedDict, total=False):
    id: str
    carrier_name: str
    capacity_tons: float
    planned_ship_date: str
    loaded_tons: float
    logistics_status: str
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class LoadAllocation(TypedDict, total=False):
    id: str
    delivery_load_id: str
    contract_id: str
    bale_lot_id: str
    tons: float
    settled_gross_cents: Optional[int]
    settled_commission_cents: Optional[int]
    settled_net_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BalingServiceOrder(TypedDict, total=False):
    id: str
    grower_id: str
    cutting_id: str
    scheduled_date: Optional[str]
    equipment_unit: Optional[str]
    actual_bale_count: Optional[int]
    baled_moisture_pct: Optional[float]
    invoice_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
