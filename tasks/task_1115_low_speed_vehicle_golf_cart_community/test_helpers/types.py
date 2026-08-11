"""Domain types: entity TypedDicts, status enums, role enum for the
Low-Speed Vehicle & Golf Cart Community Program API (PRD §3)."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"
    COMMUNITY_ADMIN = "CommunityAdmin"
    INSPECTOR = "Inspector"
    ENFORCEMENT_OFFICER = "EnforcementOfficer"
    PERMIT_HOLDER = "PermitHolder"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class EligibilityStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ComplianceStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    BARRED = "BARRED"


class DriverLicenseClass(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    MOTORCYCLE = "MOTORCYCLE"


class VehicleType(str, Enum):
    GOLF_CART = "GOLF_CART"
    LSV = "LSV"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class InsuranceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class RouteType(str, Enum):
    STREET = "STREET"
    PATH = "PATH"


class AllowedVehicleClass(str, Enum):
    GOLF_CART_ONLY = "GOLF_CART_ONLY"
    LSV_ALLOWED = "LSV_ALLOWED"


class DesignationStatus(str, Enum):
    DESIGNATED = "DESIGNATED"
    DECOMMISSIONED = "DECOMMISSIONED"


class RoutePassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    REVOKED = "REVOKED"
    COMPLETED = "COMPLETED"


class StationStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class FleetVehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHECKED_OUT = "CHECKED_OUT"
    MAINTENANCE = "MAINTENANCE"


class DispatchStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_OUT = "CHECKED_OUT"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class ViolationCode(str, Enum):
    UNDERAGE_DRIVER = "UNDERAGE_DRIVER"
    UNREGISTERED_VEHICLE = "UNREGISTERED_VEHICLE"
    EQUIPMENT_MISSING = "EQUIPMENT_MISSING"
    OFF_ROUTE = "OFF_ROUTE"
    PARKING_VIOLATION = "PARKING_VIOLATION"
    UNINSURED_OPERATION = "UNINSURED_OPERATION"


class ViolationStatus(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry the standard system-managed fields
# id / created_at / updated_at / version per PRD §2.5)
# ---------------------------------------------------------------------------

class Community(TypedDict, total=False):
    id: str
    name: str
    min_driver_age: int
    insurance_required: bool
    fleet_program_enabled: bool
    min_liability_coverage_cents: int
    renewal_window_days: int
    late_grace_days: int
    checked_out_count: int
    created_at: str
    updated_at: str
    version: int


class PermitHolder(TypedDict, total=False):
    id: str
    community_id: str
    full_name: str
    birth_date: str
    driver_license_class: str
    eligibility_status: str
    compliance_status: str
    points_balance: int
    wallet_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    holder_id: str
    vehicle_type: str
    seat_count: int
    has_headlights: bool
    has_brake_lights: bool
    has_turn_signals: bool
    has_horn: bool
    has_windshield: bool
    has_seatbelts: bool
    has_reflectors: bool
    mirror_count: int
    equipment_count: int
    vehicle_status: str
    created_at: str
    updated_at: str
    version: int


class VehicleRegistration(TypedDict, total=False):
    id: str
    vehicle_id: str
    holder_id: str
    registration_year: int
    status: str
    provisional_fee_cents: int
    finalized_fee_cents: Optional[int]
    late_fee_cents: int
    total_due_cents: int
    paid_cents: int
    renewal_score_provisional: Optional[float]
    renewal_score_audited: Optional[float]
    valid_from: Optional[str]
    expiry_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    registration_id: str
    scheduled_at: str
    status: str
    headlights_score: Optional[int]
    brake_lights_score: Optional[int]
    turn_signals_score: Optional[int]
    horn_score: Optional[int]
    mirrors_score: Optional[int]
    windshield_score: Optional[int]
    seatbelts_score: Optional[int]
    reflectors_score: Optional[int]
    total_score: Optional[float]
    passed: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict, total=False):
    id: str
    holder_id: str
    vehicle_id: str
    provider_name: str
    policy_number: str
    liability_coverage_cents: int
    effective_date: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    community_id: str
    name: str
    route_type: str
    allowed_vehicle_class: str
    designation_status: str
    created_at: str
    updated_at: str
    version: int


class RoutePass(TypedDict, total=False):
    id: str
    route_id: str
    registration_id: str
    holder_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargingStation(TypedDict, total=False):
    id: str
    community_id: str
    name: str
    slot_count: int
    rate_cents_per_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargingReservation(TypedDict, total=False):
    id: str
    station_id: str
    holder_id: str
    slot_index: int
    start_at: str
    end_at: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FleetVehicle(TypedDict, total=False):
    id: str
    community_id: str
    station_id: str
    label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FleetDispatch(TypedDict, total=False):
    id: str
    vehicle_id: str
    holder_id: str
    shift_start: str
    shift_end: str
    status: str
    returned_at: Optional[str]
    late_fine_cents: int
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    holder_id: str
    registration_id: Optional[str]
    violation_code: str
    points_assessed: int
    fine_cents: int
    occurred_at: str
    status: str
    created_at: str
    updated_at: str
    version: int
