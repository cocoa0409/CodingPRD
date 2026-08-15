"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-3).

All twelve resources carry the common system-managed properties of PRD section
2.5: `id`, `created_at`, `updated_at`, and `version`.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class SitePosture(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    ESCALATED = "ESCALATED"


class StallStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class StallClass(str, Enum):
    STANDARD = "STANDARD"
    OVERSIZED = "OVERSIZED"


class RatePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class AmenityCode(str, Enum):
    SHOWER = "SHOWER"
    FUEL = "FUEL"
    WIFI = "WIFI"
    POWER = "POWER"


class AmenityProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class DriverStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class FleetAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class DriverAuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"
    REJECTED = "REJECTED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    OVERSTAY = "OVERSTAY"
    CHECKED_OUT = "CHECKED_OUT"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    EVICTED = "EVICTED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    INVOICED = "INVOICED"
    WAIVED = "WAIVED"


class BookingKind(str, Enum):
    RESERVED = "RESERVED"
    WALK_IN = "WALK_IN"


class PaymentMode(str, Enum):
    DRIVER_DIRECT = "DRIVER_DIRECT"
    FLEET_BILL = "FLEET_BILL"


class BookingAmenityStatus(str, Enum):
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class WaitlistEntryStatus(str, Enum):
    QUEUED = "QUEUED"
    OFFERED = "OFFERED"
    PROMOTED = "PROMOTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class IncidentCategory(str, Enum):
    SECURITY = "SECURITY"
    LIGHTING = "LIGHTING"
    FACILITY = "FACILITY"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
    REOPENED = "REOPENED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    DRIVER = "Driver"
    FLEET_MANAGER = "FleetManager"
    SITE_OPERATOR = "SiteOperator"
    NETWORK_ADMIN = "NetworkAdmin"


# --- Entity TypedDicts ---
# Every resource carries id + created_at + updated_at + version (PRD 2.5).


class Site(TypedDict, total=False):
    id: str
    name: str
    base_nightly_rate_cents: int
    no_show_grace_minutes: int
    overstay_grace_minutes: int
    cancellation_free_window_hours: int
    posture: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Stall(TypedDict, total=False):
    id: str
    site_id: str
    stall_number: str
    stall_class: str
    is_reservable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RatePlan(TypedDict, total=False):
    id: str
    site_id: str
    tier2_pct: int
    tier3_pct: int
    tier4_pct: int
    mult_low: float
    mult_mid: float
    mult_high: float
    mult_max: float
    peak_multiplier: float
    peak_days: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AmenityProduct(TypedDict, total=False):
    id: str
    site_id: str
    code: str
    name: str
    price_cents: int
    nightly_capacity: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    cdl_number: str
    full_name: str
    strike_events: List[Dict[str, Any]]
    strikes_90d: int
    standing: str
    settled_nights_90d: int
    loyalty_tier: str
    loyalty_points_balance: int
    created_at: str
    updated_at: str
    version: int


class FleetAccount(TypedDict, total=False):
    id: str
    company_name: str
    credit_limit_cents: int
    payment_terms_days: int
    status: str
    auto_suspended: bool
    current_balance_cents: int
    credit_cents: int
    created_at: str
    updated_at: str
    version: int


class DriverAuthorization(TypedDict, total=False):
    id: str
    driver_id: str
    fleet_account_id: str
    spend_cap_per_night_cents: Optional[int]
    status: str
    auto_suspended: bool
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    driver_id: str
    site_id: str
    stall_id: str
    waitlist_entry_id: Optional[str]
    booking_kind: str
    payment_mode: str
    fleet_account_id: Optional[str]
    arrival_date: str
    night_count: int
    checkin_open_at: str
    checkout_due_at: str
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    overstayed_at: Optional[str]
    status: str
    billing_status: str
    per_night_rates: List[Dict[str, Any]]
    quoted_total_cents: int
    parking_subtotal_cents: int
    amenity_net_cents: int
    discount_cents: int
    fee_cents: int
    final_total_cents: Optional[int]
    paid_cents: int
    incident_escalated: bool
    created_at: str
    updated_at: str
    version: int


class BookingAmenity(TypedDict, total=False):
    id: str
    booking_id: str
    amenity_product_id: str
    quantity: int
    unit_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    site_id: str
    driver_id: str
    arrival_date: str
    night_count: int
    stall_class: str
    payment_mode: str
    fleet_account_id: Optional[str]
    status: str
    offered_stall_id: Optional[str]
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict, total=False):
    id: str
    site_id: str
    reporter_driver_id: Optional[str]
    booking_id: Optional[str]
    category: str
    severity: str
    description: str
    status: str
    acknowledged_by_user_id: Optional[str]
    resolved_by_user_id: Optional[str]
    resolved_at: Optional[str]
    reopened_count: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    fleet_account_id: str
    period: str
    status: str
    gross_cents: int
    discount_pct: int
    discount_cents: int
    net_cents: int
    paid_cents: int
    due_date: str
    booking_ids: List[str]
    created_at: str
    updated_at: str
    version: int
