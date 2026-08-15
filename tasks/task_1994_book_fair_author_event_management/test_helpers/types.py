"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class PartyKind(str, Enum):
    SCHOOL = "SCHOOL"
    PUBLISHER = "PUBLISHER"
    AUTHOR = "AUTHOR"


class FairStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    STOCKING = "STOCKING"
    OPEN = "OPEN"
    RECONCILING = "RECONCILING"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class VenueSlotStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class VenueSlotPurpose(str, Enum):
    SETUP = "SETUP"
    FAIR_DAY = "FAIR_DAY"
    AUTHOR_EVENT = "AUTHOR_EVENT"
    TEARDOWN = "TEARDOWN"


class AgreementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class StockLineStatus(str, Enum):
    QUOTED = "QUOTED"
    COMMITTED = "COMMITTED"
    DELIVERED = "DELIVERED"
    RECONCILED = "RECONCILED"


class LineType(str, Enum):
    FRONTLIST = "FRONTLIST"
    BACKLIST = "BACKLIST"


class BookingStatus(str, Enum):
    INVITED = "INVITED"
    NEGOTIATING = "NEGOTIATING"
    CONFIRMED = "CONFIRMED"
    TRAVEL_BOOKED = "TRAVEL_BOOKED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    DECLINED = "DECLINED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN_FOR_SIGNING = "OPEN_FOR_SIGNING"
    CLOSED_FOR_SIGNING = "CLOSED_FOR_SIGNING"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class SessionMode(str, Enum):
    TICKETED = "TICKETED"
    FREE = "FREE"


class TicketStatus(str, Enum):
    ISSUED = "ISSUED"
    ADMITTED = "ADMITTED"
    REDEEMED = "REDEEMED"
    NO_SHOW = "NO_SHOW"
    VOIDED = "VOIDED"


class TicketKind(str, Enum):
    TICKET = "TICKET"
    WRISTBAND = "WRISTBAND"


class PreorderStatus(str, Enum):
    PLACED = "PLACED"
    ALLOCATED = "ALLOCATED"
    FULFILLED = "FULFILLED"
    CONVERTED_BACKLIST = "CONVERTED_BACKLIST"
    CANCELLED = "CANCELLED"


class SaleStatus(str, Enum):
    DRAFT = "DRAFT"
    TENDERED = "TENDERED"
    VOIDED = "VOIDED"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    VARIANCE_REVIEW = "VARIANCE_REVIEW"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    ACCEPTED = "ACCEPTED"


class ReturnAuthStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SHIPPED = "SHIPPED"
    CREDITED = "CREDITED"


class PayoutStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class PayoutMode(str, Enum):
    CASH = "CASH"
    SCRIP = "SCRIP"


class BlastChannel(str, Enum):
    LOCAL_PAPER = "LOCAL_PAPER"
    RADIO = "RADIO"
    SOCIAL = "SOCIAL"
    SCHOOL_NEWSLETTER = "SCHOOL_NEWSLETTER"


class BlastStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"


class OfferedBy(str, Enum):
    ORGANIZER = "ORGANIZER"
    PUBLISHER = "PUBLISHER"
    AUTHOR = "AUTHOR"


class FreightResponsibility(str, Enum):
    PUBLISHER = "PUBLISHER"
    ORGANIZER = "ORGANIZER"


class UserRole(str, Enum):
    ORGANIZER = "Organizer"
    SCHOOL_COORDINATOR = "SchoolCoordinator"
    PUBLISHER_REP = "PublisherRep"
    AUTHOR_REP = "AuthorRep"
    CASHIER = "Cashier"
    LINE_STAFF = "LineStaff"


# --- Entity TypedDicts (common_fields: true unless noted) ---

class Party(TypedDict, total=False):
    id: str
    kind: str
    name: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Fair(TypedDict, total=False):
    id: str
    school_party_id: str
    title: str
    venue_key: str
    planned_start_date: str
    planned_end_date: str
    signing_floor_capacity_units: int
    promo_budget_cents: int
    status: str
    gross_sales_cents: int
    firm_purchases_cents: int
    publisher_remittance_cents: int
    return_credits_cents: int
    honorarium_total_cents: int
    preorder_allocation_run: bool
    created_at: str
    updated_at: str
    version: int


class VenueSlot(TypedDict, total=False):
    id: str
    fair_id: str
    venue_key: str
    purpose: str
    start_at: str
    end_at: str
    setup_buffer_minutes: int
    teardown_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentAgreement(TypedDict, total=False):
    id: str
    fair_id: str
    publisher_party_id: str
    discount_pct: float
    return_cap_pct: float
    restocking_fee_pct: float
    markdown_allowance_pct: float
    freight_responsibility: str
    offer_expiry_hours: int
    offered_by: str
    offer_expires_at: str
    negotiation_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StockLine(TypedDict, total=False):
    id: str
    fair_id: str
    agreement_id: str
    isbn: str
    title: str
    list_price_cents: int
    line_type: str
    qty_committed: int
    qty_delivered: int
    qty_held_preorder: int
    qty_sold: int
    qty_damaged: int
    qty_returned_shipped: int
    qty_returned_credited: int
    qty_on_hand_counted: Optional[int]
    qty_available_for_sale: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuthorBooking(TypedDict, total=False):
    id: str
    fair_id: str
    author_party_id: str
    base_honorarium_cents: int
    travel_cap_cents: int
    bonus_threshold_attendees: int
    bonus_base_cents: int
    bonus_per_attendee_cents: int
    offer_expiry_hours: int
    offered_by: str
    offer_expires_at: str
    negotiation_round: int
    travel_actual_cents: Optional[int]
    accrued_bonus_cents: int
    kill_fee_cents: int
    settled_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SigningSession(TypedDict, total=False):
    id: str
    booking_id: str
    fair_id: str
    mode: str
    start_at: str
    end_at: str
    line_space_units: int
    capacity_seats: int
    admit_concurrent_cap: int
    attendance_count: Optional[int]
    bonus_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; carries ONLY id + created_at
class SigningTicket(TypedDict, total=False):
    id: str
    session_id: str
    kind: str
    holder_name: str
    status: str
    created_at: str


class Preorder(TypedDict, total=False):
    id: str
    fair_id: str
    stock_line_id: str
    customer_name: str
    qty: int
    fulfillment_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SaleTransaction(TypedDict, total=False):
    id: str
    fair_id: str
    lines: list
    total_cents: int
    tendered_amount_cents: Optional[int]
    change_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Reconciliation(TypedDict, total=False):
    id: str
    fair_id: str
    created_by_user_id: str
    provisional_lines: list
    counted_lines: list
    variance_lines: list
    total_abs_variance: int
    remittance_cents: Optional[int]
    dispute_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict, total=False):
    id: str
    fair_id: str
    agreement_id: str
    lines: list
    credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProfitSharePayout(TypedDict, total=False):
    id: str
    fair_id: str
    school_party_id: str
    net_revenue_cents: Optional[int]
    share_cents: Optional[int]
    cash_amount_cents: Optional[int]
    scrip_amount_cents: Optional[int]
    mode: Optional[str]
    final_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class MediaBlast(TypedDict, total=False):
    id: str
    fair_id: str
    channel: str
    spend_cents: int
    embargo_until: str
    content_summary: str
    status: str
    created_at: str
    updated_at: str
    version: int
