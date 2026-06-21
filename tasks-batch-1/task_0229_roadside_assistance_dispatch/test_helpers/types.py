"""Domain types: entity TypedDicts, status enums, role enum (Roadside Assistance Dispatch)."""
from enum import Enum
from typing import TypedDict, List, Optional


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DISPATCH_OPERATOR = "DispatchOperator"
    MEMBER = "Member"
    SERVICE_PROVIDER = "ServiceProvider"


# ---------------------------------------------------------------------------
# Service type enum
# ---------------------------------------------------------------------------
class ServiceType(str, Enum):
    TOW = "TOW"
    JUMP = "JUMP"
    LOCKOUT = "LOCKOUT"
    FUEL = "FUEL"
    TIRE = "TIRE"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class MembershipTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProviderStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_JOB = "ON_JOB"
    OFFLINE = "OFFLINE"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class BayReservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ServiceCallStatus(str, Enum):
    DISPATCHING = "DISPATCHING"
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    UNFULFILLED = "UNFULFILLED"


class DispatchOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class ReimbursementClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every primary resource carries id/created_at/updated_at/version.
# ---------------------------------------------------------------------------
class MembershipPlan(TypedDict):
    id: str
    tier: str
    annual_service_limit: int
    per_incident_mileage_cap_miles: float
    overage_rate_cents_per_mile: int
    priority_weight: int
    covered_service_types: List[str]
    base_service_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    plan_id: str
    full_name: str
    status: str
    home_lat: float
    home_lng: float
    annual_period_start: str
    services_used_this_year: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ServiceProvider(TypedDict):
    id: str
    company_name: str
    status: str
    current_lat: float
    current_lng: float
    capabilities: List[str]
    rating: float
    active_call_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProviderShift(TypedDict):
    id: str
    provider_id: str
    shift_start: str
    shift_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Depot(TypedDict):
    id: str
    name: str
    lat: float
    lng: float
    bay_count: int
    cleanup_buffer_minutes: int
    occupied_bays: int
    created_at: str
    updated_at: str
    version: int


class BayReservation(TypedDict):
    id: str
    depot_id: str
    service_call_id: str
    reserved_from: str
    reserved_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceCall(TypedDict):
    id: str
    member_id: str
    service_type: str
    breakdown_lat: float
    breakdown_lng: float
    dropoff_lat: Optional[float]
    dropoff_lng: Optional[float]
    status: str
    assigned_provider_id: Optional[str]
    tow_distance_miles: float
    estimated_cost_cents: int
    final_cost_cents: int
    member_out_of_pocket_cents: int
    final_towed_miles: float
    dispatch_attempts: int
    created_at: str
    updated_at: str
    version: int


class DispatchOffer(TypedDict):
    id: str
    service_call_id: str
    provider_id: str
    status: str
    eta_minutes: int
    offer_distance_miles: float
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict):
    id: str
    member_id: str
    service_call_id: str
    claimed_amount_cents: int
    status: str
    approved_amount_cents: int
    created_at: str
    updated_at: str
    version: int
