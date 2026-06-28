"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this system carries the full common-field set (id, created_at,
updated_at, version) per PRD §2.4, so every TypedDict below includes them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ────────────────────────────────────────────────────
class UserRole(str, Enum):
    GALLERY_ADMIN = "GalleryAdmin"
    REGISTRAR = "Registrar"
    SALES_ASSOCIATE = "SalesAssociate"
    ARTIST = "Artist"


# ─── Status enums ────────────────────────────────────────────────────────────
class ArtistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ArtworkStatus(str, Enum):
    CONSIGNED = "CONSIGNED"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    ON_LOAN = "ON_LOAN"
    RETURNED = "RETURNED"


class ExhibitionStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class WallSlotStatus(str, Enum):
    PLACED = "PLACED"
    RELEASED = "RELEASED"


class SaleSettlementStatus(str, Enum):
    RESERVED = "RESERVED"
    INVOICED = "INVOICED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    SETTLED = "SETTLED"
    VOID = "VOID"


class SaleShippingStatus(str, Enum):
    PENDING = "PENDING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class PaymentPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class LeaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONVERTED = "CONVERTED"
    RETURNED = "RETURNED"
    TERMINATED = "TERMINATED"


class OpeningEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RsvpStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    PROMOTED = "PROMOTED"


class LoanStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REVERSED = "REVERSED"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
class Gallery(TypedDict):
    id: str
    name: str
    home_state_code: str
    sales_tax_rate_bps: int
    resale_exempt_threshold_cents: int
    default_consignment_split_bps: int
    clock_utc: str
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict):
    id: str
    gallery_id: str
    full_name: str
    split_override_bps: Optional[int]
    status: str
    ledger_accrued_cents: int
    ledger_paid_cents: int
    ledger_payable_cents: int
    created_at: str
    updated_at: str
    version: int


class Artwork(TypedDict):
    id: str
    gallery_id: str
    artist_id: str
    title: str
    list_price_cents: int
    insured_value_cents: int
    provenance_count: int
    provenance_log: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class Exhibition(TypedDict):
    id: str
    gallery_id: str
    title: str
    wall_capacity: int
    opens_utc: str
    closes_utc: str
    status: str
    slots_occupied: int
    slots_available: int
    created_at: str
    updated_at: str
    version: int


class WallSlot(TypedDict):
    id: str
    gallery_id: str
    exhibition_id: str
    artwork_id: str
    wall_label: str
    position_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    gallery_id: str
    artwork_id: str
    exhibition_id: Optional[str]
    buyer_name: str
    buyer_state_code: str
    gross_amount_cents: int
    discount_bps: int
    shipping_cents: int
    net_amount_cents: int
    tax_amount_cents: int
    buyer_total_cents: int
    artist_share_cents: int
    gallery_share_cents: int
    amount_collected_cents: int
    settlement_status: str
    shipping_status: str
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    gallery_id: str
    sale_id: str
    installment_count: int
    cadence_days: int
    first_due_utc: str
    installment_cents: int
    final_installment_cents: int
    posted_installment_count: int
    missed_installment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseAgreement(TypedDict):
    id: str
    gallery_id: str
    artwork_id: str
    lessee_name: str
    monthly_rate_cents: int
    term_months: int
    starts_utc: str
    purchase_credit_bps: int
    months_accrued: int
    rent_accrued_cents: int
    buyout_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OpeningEvent(TypedDict):
    id: str
    gallery_id: str
    exhibition_id: str
    capacity: int
    starts_utc: str
    rsvp_deadline_utc: str
    confirmed_count: int
    waitlist_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Rsvp(TypedDict):
    id: str
    gallery_id: str
    opening_event_id: str
    guest_name: str
    party_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    gallery_id: str
    artwork_id: str
    borrower_name: str
    coverage_value_cents: int
    out_utc: str
    due_utc: str
    returned_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    gallery_id: str
    artist_id: str
    requested_cents: int
    approved_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
