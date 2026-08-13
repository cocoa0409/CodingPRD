"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    MARKET_OPERATOR = "MarketOperator"
    VENDOR = "VendorRole"
    JURY_MEMBER = "JuryMember"
    JURY_CHAIR = "JuryChair"
    UTILITY_CREW = "UtilityCrew"
    FINANCE_OFFICER = "FinanceOfficer"


class MarketPosture(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    WEATHER_ALERT = "WEATHER_ALERT"
    CLOSED_SEASON = "CLOSED_SEASON"
    CANCELLED = "CANCELLED"


class VendorStatus(str, Enum):
    PROSPECT = "PROSPECT"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class Category(str, Enum):
    FOOD_BEVERAGE = "FOOD_BEVERAGE"
    CRAFT = "CRAFT"
    APPAREL = "APPAREL"
    HOME_GOODS = "HOME_GOODS"
    EXPERIENCE = "EXPERIENCE"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_JURY = "UNDER_JURY"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WAITLISTED = "WAITLISTED"
    WITHDRAWN = "WITHDRAWN"


class BoothType(str, Enum):
    STANDARD = "STANDARD"
    CHALET = "CHALET"


class Zone(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


class BoothStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"
    OFFLINE = "OFFLINE"


class AssignmentStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class PermitType(str, Enum):
    TEMP_STRUCTURE = "TEMP_STRUCTURE"
    FOOD_SERVICE = "FOOD_SERVICE"
    PROPANE_HEAT = "PROPANE_HEAT"
    GENERATOR = "GENERATOR"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class HookupType(str, Enum):
    ELECTRIC_15A = "ELECTRIC_15A"
    ELECTRIC_30A = "ELECTRIC_30A"
    WATER = "WATER"
    PROPANE = "PROPANE"


class HookupStatus(str, Enum):
    REQUESTED = "REQUESTED"
    INSTALLED = "INSTALLED"
    ENERGIZED = "ENERGIZED"
    DECOMMISSIONED = "DECOMMISSIONED"


class PosDeviceStatus(str, Enum):
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETURNED = "RETURNED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class SlotKind(str, Enum):
    MUSIC = "MUSIC"
    DEMO = "DEMO"
    SANTA_PHOTOS = "SANTA_PHOTOS"
    WORKSHOP = "WORKSHOP"
    PARADE = "PARADE"


class ProgrammingSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LoadDirection(str, Enum):
    LOAD_IN = "LOAD_IN"
    LOAD_OUT = "LOAD_OUT"


class LoadSlotStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class Precipitation(str, Enum):
    NONE = "NONE"
    RAIN = "RAIN"
    SNOW = "SNOW"
    ICE = "ICE"


class WeatherSource(str, Enum):
    NWS = "NWS"
    ON_SITE_SENSOR = "ON_SITE_SENSOR"
    OPERATOR = "OPERATOR"


class RenewalOfferStatus(str, Enum):
    EXTENDED = "EXTENDED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class Decision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WAITLISTED = "WAITLISTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts. Per PRD §2.4, every entity carries the full common field
# set: id, created_at, updated_at, version.
# ---------------------------------------------------------------------------

class Market(TypedDict, total=False):
    id: str
    name: str
    season_code: str
    opens_at: str
    closes_at: str
    application_opens_at: str
    application_closes_at: str
    jury_quorum: int
    category_caps: dict
    chalet_count: int
    standard_booth_count: int
    shared_pos_enabled: bool
    shared_pos_fee_bps: int
    weather_alert_threshold_wind_mph: int
    posture: str
    total_accepted_vendors: int
    total_booths_committed: int
    run_ops_index: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    category: str
    status: str
    no_show_strikes: int
    lifetime_gross_sales_cents: int
    renewal_score: float
    created_at: str
    updated_at: str
    version: int


class VendorApplication(TypedDict, total=False):
    id: str
    market_id: str
    vendor_id: str
    requested_booth_type: str
    requested_pos: bool
    heating_requested: bool
    status: str
    jury_scores: List[dict]
    jury_average: Optional[float]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booth(TypedDict, total=False):
    id: str
    market_id: str
    booth_code: str
    booth_type: str
    zone: str
    square_feet: int
    has_power: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BoothAssignment(TypedDict, total=False):
    id: str
    market_id: str
    booth_id: str
    application_id: str
    base_rent_cents: int
    heating_surcharge_cents: int
    total_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    market_id: str
    assignment_id: str
    permit_type: str
    issued_by: str
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilityHookup(TypedDict, total=False):
    id: str
    market_id: str
    booth_id: str
    hookup_type: str
    amps_drawn: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PosDevice(TypedDict, total=False):
    id: str
    market_id: str
    assignment_id: str
    device_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesSettlement(TypedDict, total=False):
    id: str
    market_id: str
    assignment_id: str
    business_date: str
    gross_card_cents: int
    gross_cash_cents: int
    pos_fee_cents: int
    refund_cents: int
    net_payable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgrammingSlot(TypedDict, total=False):
    id: str
    market_id: str
    title: str
    slot_kind: str
    starts_at: str
    ends_at: str
    vendor_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadSlot(TypedDict, total=False):
    id: str
    market_id: str
    assignment_id: str
    direction: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherEvent(TypedDict, total=False):
    id: str
    market_id: str
    observed_at: str
    wind_mph: int
    temp_f: int
    precipitation: str
    source: str
    triggers_alert: bool
    created_at: str
    updated_at: str
    version: int


class RenewalOffer(TypedDict, total=False):
    id: str
    market_id: str
    vendor_id: str
    prior_assignment_id: str
    offered_booth_id: str
    offer_expires_at: str
    discount_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int
