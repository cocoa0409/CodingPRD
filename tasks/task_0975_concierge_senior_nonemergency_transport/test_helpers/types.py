"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEACTIVATED = "DEACTIVATED"


class MobilityAid(str, Enum):
    NONE = "NONE"
    WALKER = "WALKER"
    FOLDING_WHEELCHAIR = "FOLDING_WHEELCHAIR"
    POWER_WHEELCHAIR = "POWER_WHEELCHAIR"


class AssistLevel(str, Enum):
    DOOR_TO_DOOR = "DOOR_TO_DOOR"
    DOOR_THROUGH_DOOR = "DOOR_THROUGH_DOOR"


class AssistCertification(str, Enum):
    NONE = "NONE"
    DOOR_TO_DOOR = "DOOR_TO_DOOR"
    DOOR_THROUGH_DOOR = "DOOR_THROUGH_DOOR"


class FamilyAccessLevel(str, Enum):
    VIEW_ONLY = "VIEW_ONLY"
    BOOK_FOR_CLIENT = "BOOK_FOR_CLIENT"
    BILLING_PAYER = "BILLING_PAYER"


class FamilyMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class DriverStatus(str, Enum):
    APPLICANT = "APPLICANT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class VehicleClass(str, Enum):
    SEDAN = "SEDAN"
    WAV = "WAV"


class ComplianceDocType(str, Enum):
    BACKGROUND_CHECK = "BACKGROUND_CHECK"
    BONDING = "BONDING"
    INSURANCE = "INSURANCE"
    MOTOR_VEHICLE_RECORD = "MOTOR_VEHICLE_RECORD"


class ComplianceDocStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ServiceClass(str, Enum):
    STANDARD = "STANDARD"
    WAV = "WAV"


class RateCardStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StandingRideStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class RideKind(str, Enum):
    GROCERY = "GROCERY"
    APPOINTMENT = "APPOINTMENT"
    COMPANION_OUTING = "COMPANION_OUTING"


class RideStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHING = "DISPATCHING"
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CancelReason(str, Enum):
    CUSTOMER = "CUSTOMER"
    CLIENT_SUSPENDED = "CLIENT_SUSPENDED"
    SERIES_PAUSED = "SERIES_PAUSED"
    SERIES_ENDED = "SERIES_ENDED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


class ReleaseReason(str, Enum):
    DRIVER_RELEASE = "DRIVER_RELEASE"
    RIDE_CANCELLED = "RIDE_CANCELLED"
    DRIVER_SUSPENDED = "DRIVER_SUSPENDED"


class RideEventType(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    WAIT_STARTED = "WAIT_STARTED"
    WAIT_ENDED = "WAIT_ENDED"
    SERVICE_STARTED = "SERVICE_STARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW_RECORDED = "NO_SHOW_RECORDED"


class InvoiceIssuanceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOIDED = "VOIDED"


class InvoiceDisputeStatus(str, Enum):
    NONE = "NONE"
    DISPUTED = "DISPUTED"
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"


class InvoiceLineKind(str, Enum):
    HOURLY = "HOURLY"
    MILEAGE = "MILEAGE"
    WAIT = "WAIT"
    WAV_SURCHARGE = "WAV_SURCHARGE"
    MINIMUM_ADJUSTMENT = "MINIMUM_ADJUSTMENT"
    CANCELLATION_FEE = "CANCELLATION_FEE"
    NO_SHOW_FEE = "NO_SHOW_FEE"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    CHECK = "CHECK"


class PaymentStatus(str, Enum):
    SETTLED = "SETTLED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COORDINATOR = "Coordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    BILLING_ADMIN = "BillingAdmin"
    CLIENT = "Client"
    FAMILY_MEMBER = "FamilyMember"
    DRIVER = "Driver"


class Client(TypedDict, total=False):
    id: str
    full_name: str
    status: str
    mobility_aid: str
    assist_level_default: str
    home_zone: str
    address: str
    credit_balance_cents: int
    billing_hold_limit_cents: int
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class FamilyMember(TypedDict, total=False):
    id: str
    client_id: str
    full_name: str
    relation: str
    access_level: str
    notify_on_ride_events: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    full_name: str
    status: str
    vehicle_class: str
    assist_certification: str
    home_zone: str
    max_daily_service_minutes: int
    current_load_minutes: int
    day_worked_minutes: int
    created_at: str
    updated_at: str
    version: int


class ComplianceDoc(TypedDict, total=False):
    id: str
    driver_id: str
    doc_type: str
    status: str
    valid_from: str
    valid_until: str
    renewal_of_doc_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict, total=False):
    id: str
    service_class: str
    effective_from: str
    effective_to: str
    hourly_rate_cents: int
    per_mile_cents: int
    wait_per_minute_cents: int
    included_wait_minutes: int
    minimum_charge_cents: int
    after_hours_multiplier_bp: int
    after_hours_start_minute: int
    wav_surcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StandingRide(TypedDict, total=False):
    id: str
    client_id: str
    booked_by_family_member_id: Optional[str]
    weekday: str
    pickup_time_of_day_minutes: int
    kind: str
    estimated_duration_minutes: int
    estimated_distance_miles: int
    origin_zone: str
    starts_on: str
    ends_on: str
    status: str
    next_occurrence_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ride(TypedDict, total=False):
    id: str
    client_id: str
    standing_ride_id: Optional[str]
    booked_by_family_member_id: Optional[str]
    linked_return_ride_id: Optional[str]
    kind: str
    origin_zone: str
    scheduled_pickup_at: str
    estimated_duration_minutes: int
    estimated_distance_miles: int
    requires_wav: bool
    service_class: str
    assist_level: str
    status: str
    dispatch_round: int
    excluded_driver_ids: List[str]
    assigned_driver_id: Optional[str]
    en_route_at: Optional[str]
    arrived_at: Optional[str]
    wait_minutes: int
    service_minutes: Optional[int]
    actual_distance_miles: Optional[int]
    quoted_fare_cents: int
    final_fare_cents: Optional[int]
    cancellation_fee_cents: int
    cancel_reason: Optional[str]
    cancelled_by_role: Optional[str]
    no_show_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    ride_id: str
    driver_id: str
    round: int
    status: str
    offered_at: str
    offer_expires_at: str
    responded_at: Optional[str]
    decline_reason: Optional[str]
    release_reason: Optional[str]
    matched_by: str
    matched_by_user_id: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entry: carries ONLY id + created_at (no updated_at, no version).
class RideEvent(TypedDict, total=False):
    id: str
    ride_id: str
    event_type: str
    actor_role: str
    actor_user_id: str
    occurred_at: str
    note: Optional[str]
    created_at: str


class Invoice(TypedDict, total=False):
    id: str
    client_id: str
    period_start: str
    period_end: str
    issuance_status: str
    dispute_status: str
    charges_cents: int
    credit_applied_cents: int
    total_due_cents: int
    paid_cents: int
    due_date: str
    past_due: bool
    resolved_by_user_id: Optional[str]
    resolution_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    id: str
    invoice_id: str
    ride_id: str
    line_kind: str
    quantity: int
    unit_rate_cents: int
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    client_id: str
    amount_cents: int
    method: str
    status: str
    refunded_cents: int
    applications: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int
