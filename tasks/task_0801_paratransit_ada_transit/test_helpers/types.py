"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    RIDER = "Rider"
    DISPATCHER = "Dispatcher"
    DRIVER = "Driver"
    ELIGIBILITY_SPECIALIST = "EligibilitySpecialist"
    ADMIN = "Admin"


class EligibilityStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CONDITIONAL = "CONDITIONAL"
    FULL = "FULL"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PenaltyTier(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    SUSPENDED = "SUSPENDED"


class MobilityDevice(str, Enum):
    NONE = "NONE"
    CANE = "CANE"
    WALKER = "WALKER"
    MANUAL_WHEELCHAIR = "MANUAL_WHEELCHAIR"
    POWER_WHEELCHAIR = "POWER_WHEELCHAIR"
    SCOOTER = "SCOOTER"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ASSESSMENT_SCHEDULED = "ASSESSMENT_SCHEDULED"
    ASSESSED = "ASSESSED"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"


class AssessmentOutcome(str, Enum):
    PENDING = "PENDING"
    PASS_UNCONDITIONAL = "PASS_UNCONDITIONAL"
    PASS_CONDITIONAL = "PASS_CONDITIONAL"
    FAIL = "FAIL"


class AssessmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class TripStatus(str, Enum):
    REQUESTED = "REQUESTED"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    PICKED_UP = "PICKED_UP"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    LATE_CANCELLED = "LATE_CANCELLED"
    NO_SHOW = "NO_SHOW"
    CANCELLED_BY_SYSTEM = "CANCELLED_BY_SYSTEM"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class PenaltyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class PenaltyEventType(str, Enum):
    NO_SHOW = "NO_SHOW"
    LATE_CANCEL = "LATE_CANCEL"


# --- Entity TypedDicts ---
# common_fields: true  -> id, created_at, updated_at, version
# common_fields: false -> id, created_at only


class Rider(TypedDict):
    id: str
    full_name: str
    phone: str
    email: str
    home_lat: float
    home_lng: float
    mobility_device: str
    requires_pca: bool
    eligibility_status: str
    certification_expires_at: Optional[str]
    account_status: str
    suspension_until: Optional[str]
    prior_suspension_count: int
    no_show_points_rolling: int
    no_show_points_lifetime: int
    penalty_tier: str
    created_at: str
    updated_at: str
    version: int


class ServiceZone(TypedDict):
    # common_fields: false — no updated_at, no version
    id: str
    zone_code: str
    name: str
    center_lat: float
    center_lng: float
    service_radius_miles: float
    base_fare_cents: int
    fixed_route_fare_cents: int
    created_at: str


class EligibilityApplication(TypedDict):
    id: str
    rider_id: str
    application_type: str
    status: str
    assessment_outcome: Optional[str]
    certified_category: Optional[str]
    certification_valid_until: Optional[str]
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class FunctionalAssessment(TypedDict):
    id: str
    application_id: str
    scheduled_at: str
    status: str
    outcome: str
    assessed_mobility_device: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TripReservation(TypedDict):
    id: str
    rider_id: str
    subscription_trip_id: Optional[str]
    pickup_zone_id: str
    dropoff_zone_id: str
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: float
    dropoff_lng: float
    requested_pickup_at: str
    needs_wheelchair: bool
    num_companions: int
    has_pca: bool
    status: str
    current_offer_pickup_at: Optional[str]
    offer_round: int
    assigned_run_id: Optional[str]
    scheduled_pickup_at: Optional[str]
    scheduled_dropoff_at: Optional[str]
    estimated_fare_cents: Optional[int]
    final_fare_cents: Optional[int]
    on_time: Optional[bool]
    late_cancel: bool
    created_at: str
    updated_at: str
    version: int


class NegotiationOffer(TypedDict):
    # common_fields: false — no updated_at, no version
    id: str
    trip_id: str
    offered_by: str
    proposed_pickup_at: str
    round_number: int
    created_at: str


class SubscriptionTrip(TypedDict):
    id: str
    rider_id: str
    pickup_zone_id: str
    dropoff_zone_id: str
    pickup_lat: float
    pickup_lng: float
    dropoff_lat: float
    dropoff_lng: float
    day_of_week: str
    pickup_time_utc: str
    needs_wheelchair: bool
    num_companions: int
    has_pca: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class VehicleRun(TypedDict):
    id: str
    service_zone_id: str
    service_date: str
    total_ambulatory_seats: int
    total_wheelchair_positions: int
    available_ambulatory_seats: int
    available_wheelchair_positions: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PenaltyEvent(TypedDict):
    id: str
    rider_id: str
    trip_id: str
    event_type: str
    points: int
    status: str
    occurred_at: str
    created_at: str
    updated_at: str
    version: int
