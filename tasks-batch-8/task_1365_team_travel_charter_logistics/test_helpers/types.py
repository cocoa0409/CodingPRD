"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    TRAVEL_OPS_ADMIN = "TravelOpsAdmin"
    TRAVEL_MANAGER = "TravelManager"
    TRAVEL_COORDINATOR = "TravelCoordinator"
    TRAVEL_FINANCE_LEAD = "TravelFinanceLead"
    EQUIPMENT_MANAGER = "EquipmentManager"
    SECURITY_OFFICER = "SecurityOfficer"
    VENUE_CREDENTIAL_APPROVER = "VenueCredentialApprover"
    VENDOR_REP = "VendorRep"
    TEAM_MEMBER = "TeamMember"
    ANY = "Any"


class SeasonStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TripPosture(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    DISRUPTED = "DISRUPTED"
    IN_FLIGHT = "IN_FLIGHT"
    RECOVERING = "RECOVERING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class MemberStatus(str, Enum):
    IN = "IN"
    OUT = "OUT"
    SCRATCHED = "SCRATCHED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VENDOR_COUNTERSIGNED = "VENDOR_COUNTERSIGNED"
    TEAM_EXECUTED = "TEAM_EXECUTED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class LegStatus(str, Enum):
    PLANNED = "PLANNED"
    BOOKED = "BOOKED"
    DELAYED = "DELAYED"
    REBOOKING = "REBOOKING"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class ManifestStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    BUMPED = "BUMPED"
    NO_SHOW = "NO_SHOW"
    FLOWN = "FLOWN"


class BlockPosture(str, Enum):
    HOLDING = "HOLDING"
    NAME_LIST_DUE = "NAME_LIST_DUE"
    LOCKED = "LOCKED"
    ATTRITION_EXPOSED = "ATTRITION_EXPOSED"
    CLOSED = "CLOSED"


class RoomStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class LedgerStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"


class ShipmentStatus(str, Enum):
    STAGED = "STAGED"
    LOADED = "LOADED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    DELAYED = "DELAYED"
    LOST = "LOST"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    MITIGATING = "MITIGATING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class CredentialStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


# All resources carry the common system-managed fields of PRD §2.4
# (id, created_at, updated_at, version).

class Team(TypedDict, total=False):
    id: str
    team_code: str
    display_name: str
    league_rest_policy: str
    active_season_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Season(TypedDict, total=False):
    id: str
    team_id: str
    label: str
    travel_budget_cents: int
    committed_cost_cents: int
    projected_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict, total=False):
    id: str
    team_id: str
    season_id: str
    destination_code: str
    game_tipoff_utc: str
    return_arrival_utc: str
    party_size: int
    estimated_cost_cents: int
    actual_cost_cents: int
    posture: str
    disruption_seq: int
    created_at: str
    updated_at: str
    version: int


class TravelPartyMember(TypedDict, total=False):
    id: str
    trip_id: str
    member_ref: str
    party_role: str
    travel_class: str
    per_diem_tier: str
    requires_single_room: bool
    requires_ground_transport: bool
    status: str
    weight_class: str
    created_at: str
    updated_at: str
    version: int


class CharterContract(TypedDict, total=False):
    id: str
    trip_id: str
    vendor_code: str
    base_price_cents: int
    fuel_surcharge_cap_cents: int
    seat_capacity: int
    cargo_capacity_lb: int
    penalty_bands: List[dict]
    status: str
    executed_at: Optional[str]
    cancelled_at: Optional[str]
    cancellation_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class FlightLeg(TypedDict, total=False):
    id: str
    trip_id: str
    leg_seq: int
    origin_code: str
    destination_code: str
    scheduled_depart_utc: str
    scheduled_arrive_utc: str
    is_charter: bool
    contract_id: Optional[str]
    status: str
    actual_depart_utc: Optional[str]
    actual_arrive_utc: Optional[str]
    delay_minutes: int
    rebook_generation: int
    created_at: str
    updated_at: str
    version: int


class ManifestEntry(TypedDict, total=False):
    id: str
    flight_leg_id: str
    member_id: str
    seat_assignment: Optional[str]
    is_ticketed: bool
    status: str
    bump_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HotelBlock(TypedDict, total=False):
    id: str
    trip_id: str
    hotel_code: str
    room_count: int
    rate_cents_per_night: int
    check_in_date: str
    night_count: int
    cutoff_date: str
    rooms_released: int
    posture: str
    attrition_allowance_pct: int
    created_at: str
    updated_at: str
    version: int


class RoomAssignment(TypedDict, total=False):
    id: str
    hotel_block_id: str
    member_id: str
    roommate_member_id: Optional[str]
    room_label: str
    smoking_pref: bool
    status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerDiemLedger(TypedDict, total=False):
    id: str
    member_id: str
    service_date: str
    day_kind: str
    meals_provided_count: int
    base_amount_cents: int
    deduction_cents: int
    net_amount_cents: int
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentShipment(TypedDict, total=False):
    id: str
    trip_id: str
    shipment_kind: str
    gross_weight_lb: int
    piece_count: int
    declared_value_cents: int
    assigned_contract_id: Optional[str]
    status: str
    chargeback_cents: int
    created_at: str
    updated_at: str
    version: int


class ContingencyEvent(TypedDict, total=False):
    id: str
    trip_id: str
    kind: str
    detected_at: str
    affected_leg_id: str
    severity: str
    status: str
    resolution_action: Optional[str]
    recovery_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class CredentialRequest(TypedDict, total=False):
    id: str
    trip_id: str
    member_id: str
    venue_code: str
    access_level: str
    submitted_by_user_id: str
    reviewed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
