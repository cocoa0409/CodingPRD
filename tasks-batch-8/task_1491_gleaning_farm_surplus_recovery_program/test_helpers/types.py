"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    CREW_LEADER = "CrewLeader"
    VOLUNTEER = "Volunteer"
    FOOD_SAFETY_OFFICER = "FoodSafetyOfficer"
    GRANT_REVIEWER = "GrantReviewer"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    SCHEDULED = "SCHEDULED"
    GLEANED = "GLEANED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    FULL = "FULL"
    IN_PROGRESS = "IN_PROGRESS"
    HARVESTED = "HARVESTED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"


class LotStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class DistributionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    SHORTFALL = "SHORTFALL"
    CANCELLED = "CANCELLED"


class VolunteerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ContainerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    RETIRED = "RETIRED"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_COMPOST = "RESOLVED_COMPOST"
    RESOLVED_ANIMAL_FEED = "RESOLVED_ANIMAL_FEED"
    RESOLVED_LANDFILL = "RESOLVED_LANDFILL"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    CRITICAL = "CRITICAL"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class PerishabilityClass(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


# --- Entity payloads -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# Waiver, TempLog and DonationReceipt are immutable records: id + created_at only.


class Farm(TypedDict, total=False):
    id: str
    farm_name: str
    contact_email: str
    county_code: str
    donor_tin: str
    active_flag: bool
    lifetime_donated_lbs: float
    created_at: str
    updated_at: str
    version: int


class SurplusOffer(TypedDict, total=False):
    id: str
    farm_id: str
    crop_code: str
    estimated_lbs: float
    window_start: str
    window_end: str
    perishability_class: str
    requires_refrigeration: bool
    status: str
    actual_lbs: float
    salvage_ratio: float
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    crew_leader_certified: bool
    status: str
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict, total=False):
    # Immutable record: no updated_at, no version (PRD §2.4)
    id: str
    volunteer_id: str
    glean_event_id: str
    signed_at: str
    signature_payload: str
    witness_volunteer_id: str
    created_at: str


class Agency(TypedDict, total=False):
    id: str
    agency_name: str
    county_code: str
    weekly_capacity_lbs: float
    refrigeration_capable: bool
    active_flag: bool
    current_week_committed_lbs: float
    created_at: str
    updated_at: str
    version: int


class GleanEvent(TypedDict, total=False):
    id: str
    surplus_offer_id: str
    scheduled_start: str
    scheduled_end: str
    crew_leader_volunteer_id: str
    assigned_vehicle_id: str
    crew_capacity: int
    status: str
    crew_confirmed_count: int
    total_harvested_lbs: float
    total_distributed_lbs: float
    undistributed_lbs: float
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    glean_event_id: str
    volunteer_id: str
    status: str
    confirmed_at: str
    hours_worked: float
    created_at: str
    updated_at: str
    version: int


class HarvestLot(TypedDict, total=False):
    id: str
    glean_event_id: str
    container_id: str
    gross_lbs: float
    tare_lbs: float
    cull_lbs: float
    net_lbs: float
    recorded_by_volunteer_id: str
    verified_by_coordinator_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict, total=False):
    id: str
    glean_event_id: str
    agency_id: str
    planned_lbs: float
    delivery_date: str
    delivered_lbs: float
    status: str
    cold_chain_intact: bool
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict, total=False):
    id: str
    label: str
    tare_lbs: float
    capacity_lbs: float
    refrigerated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    plate: str
    payload_capacity_lbs: float
    refrigerated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TempLog(TypedDict, total=False):
    # Immutable record: no updated_at, no version (PRD §2.4)
    id: str
    glean_event_id: str
    recorded_at: str
    temp_f: float
    breach_flag: bool
    created_at: str


class FoodSafetyIncident(TypedDict, total=False):
    id: str
    glean_event_id: str
    severity: str
    condemned_lbs: float
    reported_by_volunteer_id: str
    disposition: str
    created_at: str
    updated_at: str
    version: int


class DonationReceipt(TypedDict, total=False):
    # Immutable record: no updated_at, no version (PRD §2.4)
    id: str
    surplus_offer_id: str
    farm_id: str
    receipt_lbs: float
    fair_market_value_cents: int
    issued_at: str
    created_at: str


class GrantReport(TypedDict, total=False):
    id: str
    county_code: str
    period_start: str
    period_end: str
    status: str
    total_gleaned_lbs: float
    meals_equivalent: int
    agency_count: int
    created_at: str
    updated_at: str
    version: int
