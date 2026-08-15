"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2 and 3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    FLIGHT_COORDINATOR = "FlightCoordinator"
    REMOTE_PILOT = "RemotePilot"
    AGRONOMIST = "Agronomist"
    GROWER = "Grower"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PROCESSING_ENGINE = "ProcessingEngine"


class GrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PilotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AirspaceClass(str, Enum):
    G = "G"
    E = "E"
    D = "D"
    C = "C"
    B = "B"


class AuthorizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class MissionType(str, Enum):
    SCOUT = "SCOUT"
    SPRAY = "SPRAY"


class MissionStatus(str, Enum):
    PLANNED = "PLANNED"
    AUTHORIZED = "AUTHORIZED"
    IN_FLIGHT = "IN_FLIGHT"
    CAPTURED = "CAPTURED"
    COMPLETED = "COMPLETED"
    WEATHER_ABORTED = "WEATHER_ABORTED"
    CANCELLED = "CANCELLED"


class DeliverableKind(str, Enum):
    NDVI = "NDVI"
    PLANT_COUNT = "PLANT_COUNT"


class DeliverableStatus(str, Enum):
    PROCESSING = "PROCESSING"
    READY = "READY"
    DELIVERED = "DELIVERED"
    EXPIRED = "EXPIRED"


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVIEWED = "REVIEWED"


class ReviewOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"
    NEEDS_REFLIGHT = "NEEDS_REFLIGHT"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"


class SubscriptionPlan(TypedDict, total=False):
    id: str
    plan_code: str
    included_acres_per_year: int
    base_fee_cents: int
    overage_rate_cents_per_acre: int
    spray_allowed: bool
    ndvi_turnaround_hours: int
    storage_retention_days: int
    created_at: str
    updated_at: str
    version: int


class Grower(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    subscription_plan_id: str
    subscription_started_on: str
    acres_included_ytd: int
    credit_balance_cents: int
    liability_coverage_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict, total=False):
    id: str
    grower_id: str
    field_name: str
    legal_acres: int
    surveyed_acres: int
    airspace_class: str
    laanc_required: bool
    health_score: int
    insurance_policy_no: str
    created_at: str
    updated_at: str
    version: int


class PilotProfile(TypedDict, total=False):
    id: str
    pilot_name: str
    part107_certificate_no: str
    part107_expires_on: str
    applicator_license_no: str
    applicator_license_expires_on: str
    night_waiver: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# AirspaceAuthorization carries ONLY id + created_at (PRD section 2.4):
# no updated_at, no version.
class AirspaceAuthorization(TypedDict, total=False):
    id: str
    field_id: str
    authorization_ref: str
    max_altitude_ft: int
    effective_from: str
    effective_until: str
    status: str
    created_at: str


class FlightMission(TypedDict, total=False):
    id: str
    field_id: str
    mission_type: str
    pilot_id: str
    authorization_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    acres_planned: int
    acres_flown: int
    wind_kt_max_observed: int
    chemical_product_label: str
    gallons_dispensed: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ImageryDeliverable(TypedDict, total=False):
    id: str
    mission_id: str
    kind: str
    ndvi_mean: float
    plant_count_per_acre: int
    anomaly_count: int
    storage_uri: str
    accessible_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoutingAlert(TypedDict, total=False):
    id: str
    field_id: str
    deliverable_id: str
    severity: str
    reviewing_agronomist_id: Optional[str]
    review_notes: str
    review_outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# SprayMissionRecord carries ONLY id + created_at (PRD section 2.4):
# immutable compliance record, no updated_at, no version.
class SprayMissionRecord(TypedDict, total=False):
    id: str
    mission_id: str
    applicator_license_no: str
    chemical_product_label: str
    gallons_dispensed: float
    restricted_entry_interval_hours: int
    record_locked: bool
    created_at: str


class InsuranceClaim(TypedDict, total=False):
    id: str
    grower_id: str
    mission_id: str
    claim_amount_cents: int
    approved_amount_cents: int
    adjuster_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
