"""Domain types: entity TypedDicts, status enums, role enum.

All types are derived from the Farmers Market & Vendor Booth Management PRD.
Every primary resource carries id/created_at/updated_at/version (PRD 2.4), so
every entity TypedDict below lists those four common fields.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum (PRD 2.1: exactly three roles)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    MARKET_ADMIN = "MarketAdmin"
    MARKET_MANAGER = "MarketManager"
    VENDOR = "Vendor"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class VendorStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"


class PermitStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class PermitType(str, Enum):
    HEALTH = "HEALTH"
    FIRE = "FIRE"
    COTTAGE_FOOD = "COTTAGE_FOOD"
    RESALE = "RESALE"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProductCategory(str, Enum):
    PRODUCE = "PRODUCE"
    DAIRY = "DAIRY"
    MEAT = "MEAT"
    BAKED_GOODS = "BAKED_GOODS"
    PREPARED_FOOD = "PREPARED_FOOD"
    CRAFTS = "CRAFTS"
    FLOWERS = "FLOWERS"


class BoothStatus(str, Enum):
    OPEN = "OPEN"
    SEASON_HELD = "SEASON_HELD"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class SizeClass(str, Enum):
    SINGLE = "SINGLE"
    DOUBLE = "DOUBLE"
    CORNER = "CORNER"


class MarketDayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CancellationReason(str, Enum):
    WEATHER = "WEATHER"
    SAFETY = "SAFETY"
    LOW_TURNOUT = "LOW_TURNOUT"


class AssignmentType(str, Enum):
    SEASON = "SEASON"
    DAILY = "DAILY"


class BoothAssignmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    WAITLISTED = "WAITLISTED"
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CheckInStatus(str, Enum):
    EXPECTED = "EXPECTED"
    PRESENT = "PRESENT"
    NO_SHOW = "NO_SHOW"


class SalesReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class VoucherBatchStatus(str, Enum):
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"


class VoucherRedemptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all common_fields: true)
# ---------------------------------------------------------------------------
class Market(TypedDict):
    id: str
    name: str
    season_start_date: str
    season_end_date: str
    season_fee_cents: int
    daily_fee_cents: int
    commission_bps: int
    voucher_face_value_cents: int
    booth_count: int
    total_commission_accrued_cents: int
    total_fees_collected_cents: int
    voucher_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    market_id: str
    legal_name: str
    contact_email: str
    status: str
    permit_ok: bool
    no_show_strikes: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    vendor_id: str
    permit_type: str
    permit_number: str
    issue_date: str
    expiry_date: str
    status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    vendor_id: str
    product_category: str
    requires_health_permit: bool
    status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booth(TypedDict):
    id: str
    market_id: str
    label: str
    grid_row: int
    grid_col: int
    size_class: str
    allowed_categories: List[str]
    status: str
    season_holder_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MarketDay(TypedDict):
    id: str
    market_id: str
    market_date: str
    status: str
    opened_at: Optional[str]
    cancellation_reason: Optional[str]
    daily_fee_refundable: bool
    attendance_count: int
    created_at: str
    updated_at: str
    version: int


class BoothAssignment(TypedDict):
    id: str
    market_id: str
    booth_id: str
    vendor_id: str
    assignment_type: str
    market_day_id: Optional[str]
    status: str
    waitlist_rank: Optional[int]
    fee_charged_cents: int
    fee_refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class CheckIn(TypedDict):
    id: str
    market_id: str
    booth_assignment_id: str
    market_day_id: str
    status: str
    arrived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesReport(TypedDict):
    id: str
    market_id: str
    check_in_id: str
    gross_sales_cents: int
    tokens_accepted: int
    status: str
    commission_cents: int
    reconciled_token_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class VoucherBatch(TypedDict):
    id: str
    market_id: str
    market_day_id: str
    tokens_issued: int
    tokens_redeemed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VoucherRedemption(TypedDict):
    id: str
    market_id: str
    voucher_batch_id: str
    vendor_id: str
    market_day_id: str
    token_count: int
    status: str
    reimbursed_cents: int
    created_at: str
    updated_at: str
    version: int
