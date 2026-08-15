"""Domain types for the Custom Harvesting Crew Operations API.

Entity TypedDicts mirror the resources described in the PRD. Every resource
kind carries the full common set (id, created_at, updated_at, version) per
the PRD's resource-identity rules.
"""
from enum import Enum
from typing import TypedDict


class UserRole(str, Enum):
    HARVEST_OPERATOR = "HarvestOperator"
    GROWER_LIAISON = "GrowerLiaison"
    CREW_BOSS = "CrewBoss"
    BILLING_CLERK = "BillingClerk"


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SETTLING = "SETTLING"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    HARVESTED = "HARVESTED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    CUTTING = "CUTTING"
    PAUSED_WEATHER = "PAUSED_WEATHER"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class MachineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    IN_FIELD = "IN_FIELD"
    DOWN = "DOWN"
    REPAIRING = "REPAIRING"
    RETIRED = "RETIRED"


class CrewMemberStatus(str, Enum):
    ONBOARDED = "ONBOARDED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class MachineAssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


class LodgingReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class Crop(str, Enum):
    WHEAT = "WHEAT"
    CORN = "CORN"
    SOYBEAN = "SOYBEAN"
    SORGHUM = "SORGHUM"


class RateBasis(str, Enum):
    PER_ACRE = "PER_ACRE"
    PER_BUSHEL = "PER_BUSHEL"


class MachineKind(str, Enum):
    COMBINE = "COMBINE"
    GRAIN_CART = "GRAIN_CART"
    TRUCK = "TRUCK"


class VisaType(str, Enum):
    US_CITIZEN = "US_CITIZEN"
    H2A = "H2A"
    TN = "TN"
    PERMANENT_RESIDENT = "PERMANENT_RESIDENT"


class HarvestSeason(TypedDict):
    id: str
    season_year: int
    diesel_baseline_per_gallon_cents: int
    current_diesel_per_gallon_cents: int
    committed_acres_total: float
    harvested_acres_total: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerContract(TypedDict):
    id: str
    season_id: str
    grower_name: str
    state_code: str
    crop: str
    rate_basis: str
    rate_cents_per_acre: int
    rate_cents_per_bushel: int
    committed_acres: float
    harvested_acres: float
    moisture_discount_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    contract_id: str
    season_id: str
    planned_start_date: str
    planned_end_date: str
    planned_acres: float
    actual_acres: float
    sequence_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict):
    id: str
    season_id: str
    machine_kind: str
    label: str
    daily_capacity_acres: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    season_id: str
    full_name: str
    visa_type: str
    visa_expiry_date: str
    hourly_rate_cents: int
    requires_housing: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class MachineAssignment(TypedDict):
    id: str
    route_stop_id: str
    machine_id: str
    assigned_start_date: str
    assigned_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryTicket(TypedDict):
    id: str
    route_stop_id: str
    contract_id: str
    delivered_at: str
    gross_bushels: float
    moisture_pct: float
    net_bushels: float
    hauling_add_on_cents: int
    used_our_trucks: bool
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    contract_id: str
    season_id: str
    base_amount_cents: int
    fuel_surcharge_cents: int
    hauling_add_on_total_cents: int
    moisture_discount_cents: int
    total_amount_cents: int
    issued_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LodgingReservation(TypedDict):
    id: str
    route_stop_id: str
    crew_member_id: str
    lodging_site_id: str
    stay_start_date: str
    stay_end_date: str
    bed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LodgingSite(TypedDict):
    id: str
    season_id: str
    site_name: str
    state_code: str
    total_beds: int
    created_at: str
    updated_at: str
    version: int
