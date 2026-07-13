"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror the Oversize/Overweight Permit PRD exactly.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CARRIER = "Carrier"
    PERMIT_OFFICER = "PermitOfficer"
    BRIDGE_ENGINEER = "BridgeEngineer"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    DOT_ADMIN = "DOTAdmin"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class CarrierStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class PermitType(str, Enum):
    SINGLE_TRIP = "SINGLE_TRIP"
    ANNUAL = "ANNUAL"


class Classification(str, Enum):
    LEGAL = "LEGAL"
    OVERSIZE = "OVERSIZE"
    OVERWEIGHT = "OVERWEIGHT"
    OVERSIZE_OVERWEIGHT = "OVERSIZE_OVERWEIGHT"
    SUPERLOAD = "SUPERLOAD"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_STANDARD_REVIEW = "UNDER_STANDARD_REVIEW"
    UNDER_SUPERLOAD_REVIEW = "UNDER_SUPERLOAD_REVIEW"
    RETURNED_FOR_CORRECTION = "RETURNED_FOR_CORRECTION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ReservationStatus(str, Enum):
    PLANNED = "PLANNED"
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class StructurePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class BridgeMethod(str, Enum):
    LFR = "LFR"
    LRFR = "LRFR"


class BridgeAnalysisStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CLEARED = "CLEARED"
    CONDITIONAL = "CONDITIONAL"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PilotCarStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class EscortRole(str, Enum):
    FRONT = "FRONT"
    REAR = "REAR"
    POLICE = "POLICE"


class EscortStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class BondStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"


class ViolationType(str, Enum):
    OVER_DIMENSION = "OVER_DIMENSION"
    OFF_ROUTE = "OFF_ROUTE"
    OFF_SCHEDULE = "OFF_SCHEDULE"
    NO_ESCORT = "NO_ESCORT"
    EXPIRED_PERMIT = "EXPIRED_PERMIT"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    CONTESTED = "CONTESTED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class RestrictionType(str, Enum):
    CURFEW = "CURFEW"
    HOLIDAY = "HOLIDAY"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Entities with common_fields carry id + created_at + updated_at + version.
class Carrier(TypedDict):
    id: str
    legal_name: str
    usdot_number: str
    total_escrow_deposited_cents: int
    escrow_balance_cents: int
    active_bond_amount_cents: int
    unpaid_fee_balance_cents: int
    compliance_standing: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    carrier_id: str
    permit_type: str
    length_in: int
    width_in: int
    height_in: int
    front_overhang_in: int
    rear_overhang_in: int
    gross_weight_lbs: int
    num_axles: int
    valid_from: str
    valid_until: str
    classification: str
    requires_superload_review: bool
    fee_cents: int
    required_escort_count: int
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteSegment(TypedDict):
    id: str
    permit_id: str
    sequence_index: int
    highway_id: str
    from_milepost: float
    to_milepost: float
    structure_id: Optional[str]
    planned_cross_start_utc: Optional[str]
    planned_cross_end_utc: Optional[str]
    miles: float
    load_tonnage: float
    reservation_status: str
    created_at: str
    updated_at: str
    version: int


class Structure(TypedDict):
    id: str
    name: str
    highway_id: str
    milepost: float
    rated_capacity_tonnage: float
    dead_load_tonnage: float
    committed_tonnage: float
    available_tonnage: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class BridgeAnalysis(TypedDict):
    id: str
    permit_id: str
    structure_id: str
    method: Optional[str]
    rating_factor: Optional[float]
    status: str
    conditions_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PilotCar(TypedDict):
    id: str
    company_name: str
    cert_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EscortAssignment(TypedDict):
    id: str
    permit_id: str
    pilot_car_id: str
    role: str
    window_start_utc: str
    window_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Bond(TypedDict):
    id: str
    permit_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict):
    id: str
    permit_id: str
    carrier_id: str
    violation_type: str
    severity: str
    penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable, carries ONLY id + created_at.
class TravelRestriction(TypedDict):
    id: str
    restriction_type: str
    start_utc: str
    end_utc: str
    applies_to_classification: str
    created_at: str
