"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class Modality(str, Enum):
    ASL_ONSITE = "ASL_ONSITE"
    CART_ONSITE = "CART_ONSITE"
    VRI = "VRI"


class AdaContext(str, Enum):
    MEDICAL = "MEDICAL"
    LEGAL = "LEGAL"
    EDUCATION = "EDUCATION"
    GENERAL = "GENERAL"


class CredentialLevel(str, Enum):
    SCREENED = "SCREENED"
    CERTIFIED = "CERTIFIED"
    SPECIALIST = "SPECIALIST"


class OrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RateCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class InterpreterStatus(str, Enum):
    PENDING_ONBOARD = "PENDING_ONBOARD"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RequestStatus(str, Enum):
    DRAFT = "DRAFT"
    MATCHING = "MATCHING"
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    UNFILLED = "UNFILLED"
    CLOSED = "CLOSED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    CONFIRMED = "CONFIRMED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CancelledBy(str, Enum):
    REQUESTER = "REQUESTER"
    PLATFORM = "PLATFORM"
    INTERPRETER = "INTERPRETER"
    SYSTEM = "SYSTEM"


class IssueStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    VOID = "VOID"


class DisputeStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_OVERTURNED = "RESOLVED_OVERTURNED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class CreditMemoStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    VOID = "VOID"


class StrikeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESCINDED = "RESCINDED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ORG_REQUESTER = "OrgRequester"
    INTERPRETER = "Interpreter"
    QUALITY_REVIEWER = "QualityReviewer"
    BILLING_CLERK = "BillingClerk"
    ANY = "Any"


class RequestingOrg(TypedDict, total=False):
    id: str
    name: str
    org_type: str
    status: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict, total=False):
    id: str
    modality: str
    ada_context: str
    credential_level: str
    hourly_rate_cents: int
    minimum_billable_minutes: int
    travel_rate_cents_per_hour: int
    mileage_rate_cents_per_mile: int
    vri_platform_fee_cents_per_min: int
    cancel_full_refund_notice_hours: int
    cancel_partial_notice_hours: int
    late_cancel_fee_pct: float
    effective_from: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Interpreter(TypedDict, total=False):
    id: str
    full_name: str
    modalities_offered: List[str]
    home_zip: str
    vri_platform_certified: bool
    status: str
    active_strike_count: int
    quality_score: int
    quality_score_provisional: int
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    interpreter_id: str
    credential: str
    level: str
    issued_on: str
    expires_on: str
    verified: bool
    created_at: str
    updated_at: str
    version: int


class AvailabilityWindow(TypedDict, total=False):
    id: str
    interpreter_id: str
    start_at: str
    end_at: str
    modalities: List[str]
    created_at: str
    updated_at: str
    version: int


class InterpretingRequest(TypedDict, total=False):
    id: str
    org_id: str
    consumer_name: str
    modality: str
    ada_context: str
    scheduled_start: str
    scheduled_end: str
    onsite_address: Optional[str]
    estimated_mileage: float
    required_credential_level: str
    status: str
    offer_attempt_count: int
    cancellation_fee_cents: Optional[int]
    cancelled_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    request_id: str
    interpreter_id: str
    rate_card_id: str
    rate_card_version: int
    status: str
    offered_at: str
    response_deadline: str
    accepted_at: Optional[str]
    pinned_hourly_rate_cents: int
    pinned_minimum_billable_minutes: int
    pinned_travel_rate_cents_per_hour: int
    pinned_mileage_rate_cents_per_mile: int
    pinned_vri_platform_fee_cents_per_min: int
    pinned_cancel_full_refund_notice_hours: int
    pinned_cancel_partial_notice_hours: int
    pinned_late_cancel_fee_pct: float
    estimated_cost_cents: int
    cancelled_by: Optional[str]
    cancel_notice_hours: Optional[float]
    cancellation_fee_cents: Optional[int]
    no_show_marked_at: Optional[str]
    travel_minutes_claimed: int
    mileage_claimed: float
    created_at: str
    updated_at: str
    version: int


class Encounter(TypedDict, total=False):
    id: str
    assignment_id: str
    modality_delivered: str
    actual_start: str
    actual_end: Optional[str]
    actual_minutes: Optional[int]
    billable_minutes: Optional[int]
    verified: bool
    verify_deadline: Optional[str]
    verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict, total=False):
    kind: str
    quantity: float
    unit_rate_cents: int
    amount_cents: int


class Invoice(TypedDict, total=False):
    id: str
    org_id: str
    assignment_id: str
    encounter_id: Optional[str]
    issue_status: str
    dispute_status: str
    payment_status: str
    line_items: List[LineItem]
    subtotal_cents: int
    credits_applied_cents: int
    payments_applied_cents: int
    amount_due_cents: int
    issued_at: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    org_id: str
    assignment_id: str
    interpreter_id: str
    category: str
    severity: str
    narrative: str
    status: str
    penalty_points: Optional[int]
    credit_pct: Optional[float]
    credit_amount_cents: Optional[int]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class CreditMemo(TypedDict, total=False):
    id: str
    org_id: str
    complaint_id: Optional[str]
    amount_cents: int
    remaining_cents: int
    status: str
    applications: List[dict]
    created_at: str
    updated_at: str
    version: int


# StrikeRecord is append-only: carries ONLY id + created_at as common fields.
# No updated_at, no version.
class StrikeRecord(TypedDict, total=False):
    id: str
    interpreter_id: str
    assignment_id: Optional[str]
    occurred_at: str
    status: str
    rescinded_at: Optional[str]
    created_at: str


class ReportingSnapshot(TypedDict, total=False):
    id: str
    org_id: Optional[str]
    window_start: str
    window_end: str
    generated_at: str
    total_requests: int
    filled_count: int
    unfilled_count: int
    cancelled_count: int
    fulfillment_rate: float
    no_show_count: int
    avg_response_minutes: float
    total_billed_cents: int
    complaint_count: int
    substantiated_count: int
    ada_context_mix: dict
    created_at: str
    updated_at: str
    version: int
