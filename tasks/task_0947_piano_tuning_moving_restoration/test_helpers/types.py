"""Domain types for the Piano Tuning, Moving & Restoration API.

Status enums, role enum and entity TypedDicts, all named exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SHOP_MANAGER = "ShopManager"
    TECHNICIAN = "Technician"
    CLIENT = "Client"
    MOVE_COORDINATOR = "MoveCoordinator"
    SHOWROOM_AGENT = "ShowroomAgent"


# --------------------------------------------------------------------------
# Shared value enums
# --------------------------------------------------------------------------
class ZoneCode(str, Enum):
    ZONE_A = "ZONE_A"
    ZONE_B = "ZONE_B"
    ZONE_C = "ZONE_C"


class ClientType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    INSTITUTION = "INSTITUTION"
    DEALER = "DEALER"


class InstrumentClass(str, Enum):
    UPRIGHT = "UPRIGHT"
    CONSOLE = "CONSOLE"
    BABY_GRAND = "BABY_GRAND"
    GRAND = "GRAND"
    CONCERT_GRAND = "CONCERT_GRAND"


class UsageTier(str, Enum):
    HOME = "HOME"
    STUDIO = "STUDIO"
    INSTITUTIONAL = "INSTITUTIONAL"
    PERFORMANCE = "PERFORMANCE"


class ServiceType(str, Enum):
    TUNE = "TUNE"
    PITCH_RAISE = "PITCH_RAISE"
    REGULATE = "REGULATE"
    VOICE = "VOICE"
    REBUILD = "REBUILD"


class PitchTier(str, Enum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class CertificationLevel(str, Enum):
    APPRENTICE = "APPRENTICE"
    JOURNEYMAN = "JOURNEYMAN"
    MASTER = "MASTER"


class PartType(str, Enum):
    HAMMER_SET = "HAMMER_SET"
    STRING_SET = "STRING_SET"
    ACTION_PARTS = "ACTION_PARTS"


class LedgerEntryType(str, Enum):
    DEPOSIT_CHARGE = "DEPOSIT_CHARGE"
    MILESTONE_CHARGE = "MILESTONE_CHARGE"
    WARRANTY_CREDIT = "WARRANTY_CREDIT"
    CONSIGNMENT_PROCEEDS = "CONSIGNMENT_PROCEEDS"
    DEPOSIT_REFUND = "DEPOSIT_REFUND"
    CANCELLATION_FEE = "CANCELLATION_FEE"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    REVERSAL = "REVERSAL"


# --------------------------------------------------------------------------
# Status axes
# --------------------------------------------------------------------------
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ConditionStatus(str, Enum):
    NEEDS_ASSESSMENT = "NEEDS_ASSESSMENT"
    SERVICEABLE = "SERVICEABLE"
    NEEDS_REGULATION = "NEEDS_REGULATION"
    NEEDS_VOICING = "NEEDS_VOICING"
    REBUILD_REQUIRED = "REBUILD_REQUIRED"
    RESTORED = "RESTORED"


class CustodyStatus(str, Enum):
    AT_CLIENT_SITE = "AT_CLIENT_SITE"
    IN_TRANSIT = "IN_TRANSIT"
    IN_SHOP = "IN_SHOP"
    SHOWROOM_FLOOR = "SHOWROOM_FLOOR"
    SOLD = "SOLD"


class TuningRecallStatus(str, Enum):
    PENDING = "PENDING"
    NOTIFIED = "NOTIFIED"
    SCHEDULED = "SCHEDULED"
    FULFILLED = "FULFILLED"
    LAPSED = "LAPSED"


class OverdueTier(str, Enum):
    ON_TIME = "ON_TIME"
    OVERDUE_T1 = "OVERDUE_T1"
    OVERDUE_T2 = "OVERDUE_T2"
    LAPSED_TIER = "LAPSED_TIER"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RouteDayStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    DISPATCHED = "DISPATCHED"


class SchedulingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    RESCHEDULED = "RESCHEDULED"
    CANCELLED = "CANCELLED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    EN_ROUTE = "EN_ROUTE"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    ABORTED = "ABORTED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class PricingVariant(str, Enum):
    RETAIL = "RETAIL"
    INSTITUTIONAL = "INSTITUTIONAL"
    DEALER_NET = "DEALER_NET"


class DepositVariant(str, Enum):
    PERCENT_OF_CONTRACT = "PERCENT_OF_CONTRACT"
    FLAT_MINIMUM = "FLAT_MINIMUM"
    NET_TERMS = "NET_TERMS"


class ServiceOrderStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    VOIDED_BY_REBUILD = "VOIDED_BY_REBUILD"


class VisitPlanVariant(str, Enum):
    SINGLE_VISIT = "SINGLE_VISIT"
    SPLIT_VISIT = "SPLIT_VISIT"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class MoveJobStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class DistanceBand(str, Enum):
    LOCAL = "LOCAL"
    REGIONAL = "REGIONAL"
    LONG_HAUL = "LONG_HAUL"


class DistanceVariant(str, Enum):
    FLAT_LOCAL = "FLAT_LOCAL"
    PER_MILE = "PER_MILE"
    LONG_HAUL_FLAT = "LONG_HAUL_FLAT"


class WarrantyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRANSFERRED = "TRANSFERRED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class VoidReason(str, Enum):
    MANUAL = "MANUAL"
    UNAUTHORIZED_MOVE = "UNAUTHORIZED_MOVE"
    TUNING_CYCLE_LAPSED = "TUNING_CYCLE_LAPSED"
    CLIMATE_OUT_OF_BAND = "CLIMATE_OUT_OF_BAND"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED_RESERVICE = "APPROVED_RESERVICE"
    APPROVED_CREDIT = "APPROVED_CREDIT"
    DENIED = "DENIED"


class ResolutionVariant(str, Enum):
    FREE_RESERVICE = "FREE_RESERVICE"
    PRORATED_CREDIT = "PRORATED_CREDIT"


class ConsignmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    LISTED = "LISTED"
    SOLD = "SOLD"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class SplitVariant(str, Enum):
    AT_OR_BELOW_RESERVE = "AT_OR_BELOW_RESERVE"
    ABOVE_RESERVE = "ABOVE_RESERVE"


class PartsLotStatus(str, Enum):
    OPEN = "OPEN"
    DEPLETED = "DEPLETED"


class PartsAllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    PARTIAL = "PARTIAL"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


# --------------------------------------------------------------------------
# Entity shapes.  Resources carrying id/created_at/updated_at/version, except
# ClimateReading and LedgerEntry which carry only id and created_at.
# --------------------------------------------------------------------------
class Client(TypedDict):
    id: str
    display_name: str
    email: str
    phone: str
    client_type: str
    home_zone_code: str
    account_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    client_id: str
    label: str
    zone_code: str
    address_key: str
    stair_flights: int
    has_service_elevator: bool
    climate_controlled: bool
    distance_miles_from_shop: float
    out_of_band_flag: bool
    readings_in_window: int
    out_of_band_count: int
    created_at: str
    updated_at: str
    version: int


class Instrument(TypedDict):
    id: str
    client_id: str
    current_location_id: str
    consignment_agreement_id: Optional[str]
    make: str
    model: str
    serial_number: str
    instrument_class: str
    usage_tier: str
    target_pitch_hz: float
    last_tuning_date: Optional[str]
    pitch_deviation_cents: Optional[float]
    raw_pitch_tier: Optional[str]
    pitch_raise_tier: Optional[str]
    planned_visit_count: int
    condition_status: str
    custody_status: str
    unauthorized_move_flag: bool
    tuning_cycle_interval_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ClimateReading(TypedDict):
    # Append-only: id and created_at only, no updated_at and no version.
    id: str
    location_id: str
    recorded_at_utc: str
    relative_humidity_pct: float
    temperature_f: float
    in_band: bool
    created_at: str


class LedgerEntry(TypedDict):
    # Append-only: id and created_at only, no updated_at and no version.
    id: str
    client_id: str
    service_order_id: Optional[str]
    warranty_claim_id: Optional[str]
    consignment_agreement_id: Optional[str]
    reverses_entry_id: Optional[str]
    entry_type: str
    amount_cents: int
    memo: Optional[str]
    posted_at_utc: str
    created_at: str


ENTITIES_WITHOUT_VERSION: List[str] = ["ClimateReading", "LedgerEntry"]
