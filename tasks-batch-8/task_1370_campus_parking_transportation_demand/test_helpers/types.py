"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    COMMUTER = "Commuter"
    PARKING_ADMIN = "ParkingAdmin"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    APPEALS_OFFICER = "AppealsOfficer"


class CampusRole(str, Enum):
    STUDENT = "STUDENT"
    STAFF = "STAFF"
    FACULTY = "FACULTY"


class Residency(str, Enum):
    ON_CAMPUS = "ON_CAMPUS"
    OFF_CAMPUS = "OFF_CAMPUS"


class CommuteMode(str, Enum):
    DRIVE_ALONE = "DRIVE_ALONE"
    CARPOOL = "CARPOOL"
    TRANSIT = "TRANSIT"
    BIKE = "BIKE"
    WALK = "WALK"


class PatronStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    BLOCKED = "BLOCKED"


class LotZone(str, Enum):
    CORE = "CORE"
    PERIMETER = "PERIMETER"
    REMOTE = "REMOTE"


class LotPosture(str, Enum):
    OPEN = "OPEN"
    CLOSED_EVENT = "CLOSED_EVENT"
    CLOSED_CONSTRUCTION = "CLOSED_CONSTRUCTION"


class ResidencyRule(str, Enum):
    ANY = "ANY"
    ON_CAMPUS_ONLY = "ON_CAMPUS_ONLY"
    OFF_CAMPUS_ONLY = "OFF_CAMPUS_ONLY"


class ProrationPolicy(str, Enum):
    PRORATED_WEEKLY = "PRORATED_WEEKLY"
    FLAT_HALF_TERM = "FLAT_HALF_TERM"


class AllocationStatus(str, Enum):
    OPEN = "OPEN"
    WAITLISTING = "WAITLISTING"


class WaitlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    CLAIMED = "CLAIMED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    UNDER_APPEAL = "UNDER_APPEAL"
    PAID = "PAID"
    VOIDED = "VOIDED"


class ViolationType(str, Enum):
    NO_VALID_PERMIT = "NO_VALID_PERMIT"
    EXPIRED_PERMIT = "EXPIRED_PERMIT"
    WRONG_ZONE = "WRONG_ZONE"
    CLOSED_LOT = "CLOSED_LOT"


class AppealOutcome(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    REDUCED = "REDUCED"
    VOIDED = "VOIDED"


class ClosureReason(str, Enum):
    EVENT = "EVENT"
    CONSTRUCTION = "CONSTRUCTION"


class ClosureStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"
    CANCELLED = "CANCELLED"


class ShuttleRouteStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Patron(TypedDict, total=False):
    id: str
    full_name: str
    campus_role: str
    residency: str
    primary_commute_mode: str
    outstanding_balance_cents: int
    standing: str
    created_at: str
    updated_at: str
    version: int


class ParkingLot(TypedDict, total=False):
    id: str
    lot_code: str
    name: str
    zone: str
    capacity_total: int
    posture: str
    reserved_spaces_total: int
    available_capacity: int
    created_at: str
    updated_at: str
    version: int


class LotAllocation(TypedDict, total=False):
    id: str
    lot_id: str
    permit_code: str
    eligible_roles: list
    residency_rule: str
    base_fee_cents: int
    proration_policy: str
    term_start: str
    term_end: str
    quota: int
    allocated_count: int
    offers_outstanding: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    allocation_id: str
    patron_id: str
    status: str
    waiting_since: str
    offered_at: Optional[str]
    offer_expires_at: Optional[str]
    decline_count: int
    requeue_count: int
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    patron_id: str
    allocation_id: str
    displaced_from_allocation_id: Optional[str]
    plate_number: str
    valid_from: str
    valid_to: str
    status: str
    fee_base_cents: int
    surcharge_cents: int
    fee_total_cents: int
    credit_applied_cents: int
    fee_paid_cents: int
    refund_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict, total=False):
    id: str
    lot_id: str
    plate_number: str
    permit_id: str
    patron_id: str
    violation_type: str
    fine_amount_cents: int
    status: str
    issued_by_officer_id: str
    issued_at: str
    appeal_reason: Optional[str]
    appeal_outcome: str
    appeal_decided_by: Optional[str]
    reduction_pct: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LotClosure(TypedDict, total=False):
    id: str
    lot_id: str
    reason: str
    event_name: Optional[str]
    expected_attendance: Optional[int]
    reserved_spaces: int
    fallback_lot_id: Optional[str]
    starts_at: str
    ends_at: str
    status: str
    displaced_permit_count: int
    created_at: str
    updated_at: str
    version: int


class ShuttleRoute(TypedDict, total=False):
    id: str
    fund_id: str
    route_code: str
    fleet_group: str
    service_window_start_minutes: int
    service_window_end_minutes: int
    headway_minutes: int
    vehicle_capacity: int
    projected_daily_ridership: int
    annual_operating_cost_cents: int
    status: str
    planned_daily_runs: int
    daily_capacity: int
    ridership_total: int
    created_at: str
    updated_at: str
    version: int


class IncentiveAccount(TypedDict, total=False):
    id: str
    patron_id: str
    points_balance: int
    lifetime_points: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class TransportationFund(TypedDict, total=False):
    id: str
    fund_code: str
    permit_revenue_cents: int
    citation_revenue_cents: int
    committed_shuttle_funding_cents: int
    available_balance_cents: int
    created_at: str
    updated_at: str
    version: int
