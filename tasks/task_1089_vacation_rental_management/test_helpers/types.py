"""Domain types: entity TypedDicts, status enums, and the role enum.

All types describe the Vacation Rental Management API contract. Entities carry the
common fields id/created_at/updated_at/version, except StatementLine, which is an
immutable ledger entry carrying only id and created_at.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROPERTY_MANAGER = "PropertyManager"
    OWNER = "Owner"
    GUEST = "Guest"
    VENDOR = "Vendor"
    ANONYMOUS = "Anonymous"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class GuestStatus(str, Enum):
    UNSCREENED = "UNSCREENED"
    APPROVED = "APPROVED"
    BANNED = "BANNED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PropertyStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    LISTED = "LISTED"
    UNLISTED = "UNLISTED"
    OFFBOARDED = "OFFBOARDED"


class PermitStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ChannelListingStatus(str, Enum):
    DRAFT = "DRAFT"
    SYNCED = "SYNCED"
    PAUSED = "PAUSED"
    DELISTED = "DELISTED"


class BookingStayStatus(str, Enum):
    HOLD = "HOLD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class BookingScreeningStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class TurnoverTaskStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CLEANED = "CLEANED"
    INSPECTED = "INSPECTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InspectionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_INFO = "NEEDS_INFO"
    COMPLETED = "COMPLETED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class OwnerStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PUBLISHED = "PUBLISHED"
    SUPPRESSED = "SUPPRESSED"


# --------------------------------------------------------------------------- #
# Entity TypedDicts (common_fields: true carries version + updated_at)
# --------------------------------------------------------------------------- #
class Owner(TypedDict):
    id: str
    legal_name: str
    email: str
    payout_method: str
    default_management_fee_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    full_name: str
    email: str
    government_id_verified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    vendor_type: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    owner_id: str
    address: str
    city: str
    state_code: str
    jurisdiction_code: str
    base_nightly_rate_cents: int
    cleaning_fee_cents: int
    max_occupancy: int
    default_cancellation_policy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    property_id: str
    permit_number: str
    jurisdiction_code: str
    occupancy_tax_pct: float
    issued_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChannelListing(TypedDict):
    id: str
    property_id: str
    channel: str
    external_listing_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PricingRule(TypedDict):
    id: str
    property_id: str
    rule_type: str
    multiplier_bps: Optional[int]
    min_nights: Optional[int]
    start_date: Optional[str]
    end_date: Optional[str]
    priority: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    property_id: str
    guest_id: str
    check_in: str
    check_out: str
    nights: int
    cancellation_policy: str
    quoted_per_night_cents: int
    nightly_subtotal_cents: int
    quoted_cleaning_fee_cents: int
    occupancy_tax_cents: int
    total_cents: int
    refund_cents: int
    stay_status: str
    screening_status: str
    messages: List[dict]
    created_at: str
    updated_at: str
    version: int


class TurnoverTask(TypedDict):
    id: str
    booking_id: str
    property_id: str
    assigned_vendor_id: str
    scheduled_window_start: str
    scheduled_window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    turnover_task_id: str
    inspector_vendor_id: str
    result: str
    notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    property_id: str
    vendor_id: Optional[str]
    owner_statement_id: Optional[str]
    description: str
    cost_cents: int
    billable_to: str
    requires_owner_approval: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class OwnerStatement(TypedDict):
    id: str
    owner_id: str
    period_year: int
    period_month: int
    gross_rental_cents: int
    mgmt_fee_cents: int
    cleaning_pass_through_cents: int
    work_order_owner_charges_cents: int
    tax_remitted_cents: int
    owner_payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable ledger entry, NO updated_at, NO version
class StatementLine(TypedDict):
    id: str
    statement_id: str
    line_type: str
    amount_cents: int
    source_ref: Optional[str]
    created_at: str


class Review(TypedDict):
    id: str
    booking_id: str
    property_id: str
    rating: int
    comment: Optional[str]
    author_role: str
    status: str
    created_at: str
    updated_at: str
    version: int
