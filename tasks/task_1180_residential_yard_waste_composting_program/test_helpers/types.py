"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    RESIDENT = "Resident"
    DRIVER = "Driver"
    FIELD_INSPECTOR = "FieldInspector"
    ROUTE_SUPERVISOR = "RouteSupervisor"
    BILLING_CLERK = "BillingClerk"
    PROGRAM_ADMIN = "ProgramAdmin"
    OUTREACH_COORDINATOR = "OutreachCoordinator"


class ServiceModel(str, Enum):
    OPT_IN = "OPT_IN"
    UNIVERSAL = "UNIVERSAL"


class ZoneStatus(str, Enum):
    OPEN_ENROLLMENT = "OPEN_ENROLLMENT"
    IN_SEASON = "IN_SEASON"
    OFF_SEASON = "OFF_SEASON"


class SubscriptionStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class SuspendedReason(str, Enum):
    CONTAMINATION_STRIKES = "CONTAMINATION_STRIKES"


class CartSize(int, Enum):
    GAL_35 = 35
    GAL_64 = 64
    GAL_96 = 96


class CartStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DELIVERED = "DELIVERED"
    RETRIEVAL_SCHEDULED = "RETRIEVAL_SCHEDULED"
    RETRIEVED = "RETRIEVED"


class Weekday(str, Enum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class TicketStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED_REPORTED = "MISSED_REPORTED"
    MISSED = "MISSED"
    REJECTED_CONTAMINATION = "REJECTED_CONTAMINATION"
    SKIPPED = "SKIPPED"


class InspectionResult(str, Enum):
    PASSED = "PASSED"
    TAGGED_WARNING = "TAGGED_WARNING"
    TAGGED_REJECTED = "TAGGED_REJECTED"


class ViolationCode(str, Enum):
    PLASTIC_BAG = "PLASTIC_BAG"
    FOOD_WASTE = "FOOD_WASTE"
    DIRT_ROCK = "DIRT_ROCK"
    HAZARDOUS = "HAZARDOUS"
    NON_YARD_MATERIAL = "NON_YARD_MATERIAL"


class SurgeEventType(str, Enum):
    LEAF_SURGE = "LEAF_SURGE"
    HOLIDAY_TREE = "HOLIDAY_TREE"


class SurgeEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    COMPLETED = "COMPLETED"


class SurgeBookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class FacilityStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class DeliveryOutcome(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class GivebackEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ClaimStatus(str, Enum):
    FULFILLED = "FULFILLED"
    VOIDED = "VOIDED"


class CreditStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    GRANTED = "GRANTED"
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class CampaignChannel(str, Enum):
    MAIL = "MAIL"
    DOOR_TAG = "DOOR_TAG"
    EMAIL = "EMAIL"
    SOCIAL = "SOCIAL"


class CampaignTopic(str, Enum):
    ACCEPTABLE_MATERIALS = "ACCEPTABLE_MATERIALS"
    SEASON_START = "SEASON_START"
    CONTAMINATION_PREVENTION = "CONTAMINATION_PREVENTION"
    COMPOST_GIVEBACK = "COMPOST_GIVEBACK"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# --- Entity payloads (response bodies) ---
# Common properties (id, created_at, updated_at, version) apply to every
# top-level resource except contamination inspections and service credits,
# which are immutable evidentiary records carrying only id and created_at.


class ServiceZone(TypedDict):
    id: str
    name: str
    service_model: str
    season_start_date: str
    season_end_date: str
    base_seasonal_fee_cents: int
    universal_flat_credit_cents: int
    max_strikes_per_season: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict):
    id: str
    address_line: str
    zone_id: str
    credit_balance_cents: int
    compost_entitlement_gallons: float
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    household_id: str
    season_year: int
    service_model: str
    status: str
    base_fee_cents: int
    cart_fees_cents: int
    surcharge_cents: int
    total_due_cents: int
    paid_cents: int
    strikes_this_season: int
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Cart(TypedDict):
    id: str
    household_id: str
    subscription_id: str
    size_gallons: int
    status: str
    delivered_at: Optional[str]
    surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class CollectionRoute(TypedDict):
    id: str
    zone_id: str
    weekday: str
    effective_start_date: str
    effective_end_date: str
    max_stops: int
    max_tonnage_lbs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupTicket(TypedDict):
    id: str
    subscription_id: str
    route_id: str
    service_date: str
    status: str
    weight_lbs: Optional[int]
    completed_at: Optional[str]
    missed_reported_by: Optional[str]
    missed_validated_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContaminationInspection(TypedDict):
    # Immutable evidentiary record: id + created_at only, no updated_at/version.
    id: str
    pickup_ticket_id: str
    result: str
    violation_codes: List[str]
    notes: Optional[str]
    inspector_user_id: str
    created_at: str


class SurgeEvent(TypedDict):
    id: str
    zone_id: str
    event_type: str
    service_date: str
    booking_window_start: str
    booking_window_end: str
    capacity_slots: int
    reserved_slots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SurgeBooking(TypedDict):
    id: str
    surge_event_id: str
    household_id: str
    quantity_bundles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProcessingFacility(TypedDict):
    id: str
    name: str
    daily_receiving_capacity_lbs: int
    safety_contamination_item_limit: int
    status: str
    season_accepted_lbs: int
    created_at: str
    updated_at: str
    version: int


class FacilityDelivery(TypedDict):
    id: str
    facility_id: str
    route_id: str
    delivery_date: str
    window_start: str
    window_end: str
    status: str
    gross_weight_lbs: Optional[int]
    contaminated_item_count: Optional[int]
    accepted_weight_lbs: int
    created_at: str
    updated_at: str
    version: int


class CompostGivebackEvent(TypedDict):
    id: str
    zone_id: str
    event_date: str
    per_household_cap_gallons: int
    initial_inventory_gallons: int
    remaining_gallons: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CompostClaim(TypedDict):
    id: str
    giveback_event_id: str
    household_id: str
    gallons: int
    status: str
    entitlement_snapshot_gallons: float
    created_at: str
    updated_at: str
    version: int


class ServiceCredit(TypedDict):
    # Immutable evidentiary record: id + created_at only, no updated_at/version.
    id: str
    household_id: str
    subscription_id: str
    missed_pickup_ticket_id: str
    amount_cents: int
    status: str
    validated_by: str
    approved_by: Optional[str]
    created_at: str


class OutreachCampaign(TypedDict):
    id: str
    zone_id: Optional[str]
    channel: str
    topic: str
    budget_cents: int
    audience_size: int
    cost_per_impression_cents: int
    end_date: str
    spent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
