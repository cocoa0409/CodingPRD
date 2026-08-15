"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SUBSCRIBER = "Subscriber"
    SERVICE_REP = "ServiceRep"
    DISTRICT_MANAGER = "DistrictManager"
    CIRCULATION_DIRECTOR = "CirculationDirector"


class PlanType(str, Enum):
    PRINT = "PRINT"
    DIGITAL = "DIGITAL"
    BUNDLE = "BUNDLE"


class ProrationMethod(str, Enum):
    PER_DAY = "PER_DAY"
    PER_ISSUE = "PER_ISSUE"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SubscriberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CLOSED = "CLOSED"


class BillingStatus(str, Enum):
    PENDING_START = "PENDING_START"
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    SUSPENDED = "SUSPENDED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    LAPSED = "LAPSED"


class DeliveryStatus(str, Enum):
    NOT_DELIVERED = "NOT_DELIVERED"
    DELIVERING = "DELIVERING"
    HELD = "HELD"


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CompensationModel(str, Enum):
    PER_COPY_GROSS = "PER_COPY_GROSS"
    PER_COPY_NET_OF_COMPLAINTS = "PER_COPY_NET_OF_COMPLAINTS"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class HoldResolution(str, Enum):
    CREDIT = "CREDIT"
    REDELIVER = "REDELIVER"


class HoldStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ComplaintType(str, Enum):
    MISSED = "MISSED"
    DAMAGED = "DAMAGED"
    LATE = "LATE"
    OTHER = "OTHER"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    CREDITED = "CREDITED"
    DENIED = "DENIED"


class CreditMemoSource(str, Enum):
    GOODWILL = "GOODWILL"
    COMPLAINT = "COMPLAINT"
    PRORATION = "PRORATION"


class CreditMemoStatus(str, Enum):
    ISSUED = "ISSUED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class SaveOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class SaveOfferOrigin(str, Enum):
    CANCEL_FLOW = "CANCEL_FLOW"
    RETENTION_REP = "RETENTION_REP"


class RackLocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RackReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RECONCILED = "RECONCILED"
    DISPUTED = "DISPUTED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CHECK = "CHECK"
    CASH = "CASH"
    ACH = "ACH"


class PaymentStatus(str, Enum):
    INITIATED = "INITIATED"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class ChargeStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class AuditReportStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUBMITTED = "SUBMITTED"


# Every entity in this domain carries id + created_at + updated_at + version
# (PRD §2.4: "No entity in this domain omits `updated_at` or `version`.")

class SubscriptionPlan(TypedDict, total=False):
    id: str
    name: str
    plan_type: str
    issues_per_week: int
    base_weekly_rate_cents: int
    step_up_schedule: List[dict]
    proration_method: str
    min_weekly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscriber(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    service_address: Optional[str]
    status: str
    balance_due_cents: int
    unapplied_cash_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    subscriber_id: str
    plan_id: str
    start_date: str
    billing_status: str
    delivery_status: str
    next_charge_date: str
    pending_plan_id: Optional[str]
    pending_plan_effective_date: Optional[str]
    save_discount_pct: Optional[float]
    save_discount_until: Optional[str]
    cancel_reason: Optional[str]
    ended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict, total=False):
    id: str
    route_code: str
    carrier_id: Optional[str]
    max_stops: int
    assigned_stop_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict, total=False):
    id: str
    display_name: str
    compensation_model: str
    per_copy_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteAssignment(TypedDict, total=False):
    id: str
    subscription_id: str
    route_id: str
    start_date: str
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class VacationHold(TypedDict, total=False):
    id: str
    subscription_id: str
    start_date: str
    end_date: str
    resolution: str
    status: str
    weekly_rate_snapshot_cents: Optional[int]
    credit_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DeliveryComplaint(TypedDict, total=False):
    id: str
    subscription_id: str
    service_date: str
    complaint_type: str
    route_id: Optional[str]
    status: str
    credit_amount_cents: Optional[int]
    deny_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditMemo(TypedDict, total=False):
    id: str
    subscriber_id: str
    source: str
    complaint_id: Optional[str]
    hold_id: Optional[str]
    amount_cents: int
    applied_cents: int
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SaveOffer(TypedDict, total=False):
    id: str
    subscription_id: str
    offer_type: str
    discount_pct: float
    duration_weeks: int
    origin: str
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class RackLocation(TypedDict, total=False):
    id: str
    location_name: str
    address: str
    price_per_copy_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RackSalesReport(TypedDict, total=False):
    id: str
    rack_location_id: str
    week_start_date: str
    copies_delivered: int
    copies_returned: int
    reported_sold_copies: Optional[int]
    copies_sold: int
    amount_due_cents: int
    variance_copies: int
    variance_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    subscriber_id: str
    amount_cents: int
    method: str
    status: str
    allocations: List[dict]
    created_at: str
    updated_at: str
    version: int


class BillingCharge(TypedDict, total=False):
    id: str
    subscription_id: str
    subscriber_id: str
    period_start: str
    period_end: str
    due_date: str
    amount_cents: int
    paid_amount_cents: int
    credit_applied_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    paid_print_subscribers: int
    paid_digital_subscribers: int
    single_copy_copies: int
    status: str
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
