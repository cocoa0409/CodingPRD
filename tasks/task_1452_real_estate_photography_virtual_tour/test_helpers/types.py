"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Dict


class MarketStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PhotographerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class BookingState(str, Enum):
    DRAFT = "DRAFT"
    AWAITING_READINESS = "AWAITING_READINESS"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    AUTHORIZATION_PENDING = "AUTHORIZATION_PENDING"
    CONFIRMED = "CONFIRMED"
    SHOT = "SHOT"
    IN_EDIT = "IN_EDIT"
    DELIVERED = "DELIVERED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    CANCELLED_BY_CLIENT = "CANCELLED_BY_CLIENT"
    CANCELLED_WEATHER = "CANCELLED_WEATHER"
    EXPIRED = "EXPIRED"


class EquipmentPackage(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    LUXURY = "LUXURY"


class TourVariant(str, Enum):
    BRANDED = "BRANDED"
    UNBRANDED = "UNBRANDED"


class LicenseTier(str, Enum):
    MLS_COMPLIANT = "MLS_COMPLIANT"
    STANDARD_MARKETING = "STANDARD_MARKETING"
    EXTENDED = "EXTENDED"


class AddOnKind(str, Enum):
    TWILIGHT_UPGRADE = "TWILIGHT_UPGRADE"
    DRONE_STILLS = "DRONE_STILLS"
    DRONE_VIDEO = "DRONE_VIDEO"
    RUSH_EDIT = "RUSH_EDIT"
    VIRTUAL_STAGING = "VIRTUAL_STAGING"


class AddOnState(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    REFUSED = "REFUSED"


class AuthorizationState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class BundleState(str, Enum):
    EDITING = "EDITING"
    DELIVERED = "DELIVERED"
    SUPERSEDED = "SUPERSEDED"
    FINALIZED = "FINALIZED"


class RevisionState(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    REJECTED_LATE = "REJECTED_LATE"
    REJECTED_EXHAUSTED = "REJECTED_EXHAUSTED"


class TourState(str, Enum):
    HOSTED = "HOSTED"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    UNPUBLISHED = "UNPUBLISHED"


class LicenseState(str, Enum):
    DORMANT = "DORMANT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class RescheduleKind(str, Enum):
    WEATHER = "WEATHER"
    CLIENT = "CLIENT"


class UserRole(str, Enum):
    CLIENT_AGENT = "ClientAgent"
    PHOTOGRAPHER = "Photographer"
    COORDINATOR = "Coordinator"
    OPS_ADMIN = "OpsAdmin"


# --- Entity TypedDicts (common_fields: true unless noted) ---

class Market(TypedDict, total=False):
    id: str
    market_code: str
    display_name: str
    pricing_multiplier_bps: int
    standard_turnaround_hours: int
    twilight_slot_minutes: int
    travel_buffer_minutes: int
    weather_reschedule_credit_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Photographer(TypedDict, total=False):
    id: str
    market_id: str
    full_name: str
    email: str
    equipment_packages: List[str]
    drone_certified: bool
    max_shoot_minutes_per_day: int
    committed_minutes_by_day: Dict[str, int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShootBooking(TypedDict, total=False):
    id: str
    order_ref: str
    client_agent_id: str
    market_id: str
    property_address: str
    equipment_package: str
    photo_count: int
    wants_virtual_tour: bool
    tour_variant: Optional[str]
    license_tier: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    shoot_duration_minutes: int
    is_twilight: bool
    state: str
    assigned_photographer_id: Optional[str]
    provisional_quote_cents: Optional[int]
    final_invoice_cents: Optional[int]
    weather_credit_cents: int
    reschedule_count: int
    delivery_due_utc: Optional[str]
    delivered_at_utc: Optional[str]
    revision_window_closes_utc: Optional[str]
    revisions_used: int
    created_at: str
    updated_at: str
    version: int


class ClientAgent(TypedDict, total=False):
    id: str
    brokerage_name: str
    full_name: str
    email: str
    home_market_id: str
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ReadinessChecklistItem(TypedDict, total=False):
    id: str
    booking_id: str
    item_key: str
    required: bool
    checked: bool
    checked_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict, total=False):
    id: str
    booking_id: str
    kind: str
    state: str
    price_cents: int
    extra_minutes: int
    created_at: str
    updated_at: str
    version: int


class AirspaceAuthorization(TypedDict, total=False):
    id: str
    booking_id: str
    addon_id: str
    window_start_utc: str
    window_end_utc: str
    state: str
    attempt_number: int
    decided_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssetBundle(TypedDict, total=False):
    id: str
    booking_id: str
    state: str
    photo_asset_count: int
    tour_asset_url: Optional[str]
    delivered_at_utc: Optional[str]
    round_number: int
    created_at: str
    updated_at: str
    version: int


class RevisionRequest(TypedDict, total=False):
    id: str
    booking_id: str
    bundle_id: str
    notes: str
    state: str
    is_free: bool
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


class VirtualTour(TypedDict, total=False):
    id: str
    booking_id: str
    variant: str
    state: str
    hosted_url: str
    published_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicenseGrant(TypedDict, total=False):
    id: str
    booking_id: str
    tier: str
    state: str
    activated_at_utc: Optional[str]
    fee_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only audit record: id + created_at ONLY
class RescheduleEvent(TypedDict, total=False):
    id: str
    booking_id: str
    kind: str
    old_start_utc: str
    new_start_utc: str
    reason_code: str
    credit_applied_cents: int
    created_at: str
