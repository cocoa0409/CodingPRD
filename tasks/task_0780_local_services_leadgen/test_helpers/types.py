"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    PRO = "Pro"
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER_SERVICE = "CustomerService"


class ProVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"


class BillingMode(str, Enum):
    PAY_PER_LEAD = "PAY_PER_LEAD"
    SUBSCRIPTION = "SUBSCRIPTION"


class ServiceRequestStatus(str, Enum):
    OPEN = "OPEN"
    DISTRIBUTED = "DISTRIBUTED"
    BOOKED = "BOOKED"
    CLOSED = "CLOSED"


class LeadContactStatus(str, Enum):
    DISTRIBUTED = "DISTRIBUTED"
    CONTACTED = "CONTACTED"
    QUOTED = "QUOTED"
    CONVERTED = "CONVERTED"
    CLOSED = "CLOSED"


class LeadBillingStatus(str, Enum):
    CHARGED = "CHARGED"
    REFUNDED = "REFUNDED"
    DISPUTED = "DISPUTED"


class QuoteStatus(str, Enum):
    SENT = "SENT"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    PUBLISHED = "PUBLISHED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_REFUNDED = "RESOLVED_REFUNDED"
    RESOLVED_DENIED = "RESOLVED_DENIED"


class AvailabilitySlotStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"


# --- Versioned entities (carry id + created_at + updated_at + version) ---

class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    phone: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Pro(TypedDict):
    id: str
    email: str
    business_name: str
    phone: Optional[str]
    verification_status: str
    billing_mode: str
    subscription_plan_id: Optional[str]
    credit_balance_cents: int
    remaining_lead_credits: int
    service_zip_codes: List[str]
    covered_category_ids: List[str]
    rating_avg: float
    rating_count: int
    provisional_rating: float
    dispute_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceRequest(TypedDict):
    id: str
    customer_id: str
    category_id: str
    zip_code: str
    description: str
    budget_cents: int
    status: str
    distributed_lead_count: int
    created_at: str
    updated_at: str
    version: int


class Lead(TypedDict):
    id: str
    request_id: str
    pro_id: str
    category_id: str
    billing_mode: str
    charge_cents: int
    credits_consumed: int
    contact_status: str
    billing_status: str
    distributed_at: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    lead_id: str
    pro_id: str
    customer_id: str
    amount_cents: int
    message: str
    status: str
    revision_count: int
    valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    quote_id: str
    customer_id: str
    pro_id: str
    availability_slot_id: str
    scheduled_start: str
    scheduled_end: str
    price_cents: int
    payout_cents: int
    status: str
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict):
    id: str
    booking_id: str
    customer_id: str
    pro_id: str
    rating: int
    text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    lead_id: str
    raised_by_pro_id: str
    reason: str
    status: str
    refund_cents: int
    resolution_note: Optional[str]
    assigned_cs_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AvailabilitySlot(TypedDict):
    id: str
    pro_id: str
    start_utc: str
    end_utc: str
    status: str
    booking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Configuration reference data (immutable: carry ONLY id + created_at) ---

class ServiceCategory(TypedDict):
    id: str
    name: str
    base_lead_price_cents: int
    max_leads_per_request: int
    demand_high_threshold: int
    demand_multiplier_high: float
    refund_window_hours: int
    min_rating_to_receive_leads: float
    created_at: str


class SubscriptionPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    included_lead_credits: int
    overage_price_cents: int
    created_at: str
