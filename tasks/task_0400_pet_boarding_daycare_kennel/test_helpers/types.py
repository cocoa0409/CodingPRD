"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model. Two entity types are deliberately leaner —
VaccinationRecord and PackageRedemption are append-only audit rows carrying only
``id`` and ``created_at`` (no ``updated_at``, no ``version``); every other entity
carries the full common-field set.
"""
from enum import Enum
from typing import TypedDict, List


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    FACILITY_MANAGER = "FacilityManager"
    FACILITY_STAFF = "FacilityStaff"
    OWNER = "Owner"


# --------------------------------------------------------------------------- enums
class DepositPolicy(str, Enum):
    STANDARD = "STANDARD"
    STRICT = "STRICT"
    NONE = "NONE"


class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"


class Temperament(str, Enum):
    CALM = "CALM"
    PLAYFUL = "PLAYFUL"
    REACTIVE = "REACTIVE"


class SizeClass(str, Enum):
    TOY = "TOY"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class VaccinationStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    MISSING = "MISSING"


class TemperamentClearance(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class Vaccine(str, Enum):
    RABIES = "RABIES"
    DHPP = "DHPP"
    BORDETELLA = "BORDETELLA"
    FVRCP = "FVRCP"


class RunKind(str, Enum):
    OVERNIGHT_SUITE = "OVERNIGHT_SUITE"
    DAYCARE_PEN = "DAYCARE_PEN"


class RunStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RETIRED = "RETIRED"


class ServiceType(str, Enum):
    DAYCARE = "DAYCARE"
    OVERNIGHT = "OVERNIGHT"


class ReservationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class RunAssignmentStatus(str, Enum):
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"


class AddOnKind(str, Enum):
    BATH = "BATH"
    PLAYTIME = "PLAYTIME"


class AddOnStatus(str, Enum):
    BOOKED = "BOOKED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PackageTier(str, Enum):
    DAYCARE_10 = "DAYCARE_10"
    DAYCARE_20 = "DAYCARE_20"


class PackageStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


# --------------------------------------------------------------- entity TypedDicts
# common_fields: true — id + created_at + updated_at + version
class Facility(TypedDict):
    id: str
    name: str
    daycare_cutoff_time: str
    deposit_policy: str
    overbook_grace: int
    current_date: str
    created_at: str
    updated_at: str
    version: int


class Owner(TypedDict):
    id: str
    facility_id: str
    full_name: str
    email: str
    phone: str
    status: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Pet(TypedDict):
    id: str
    owner_id: str
    facility_id: str
    name: str
    species: str
    weight_kg: float
    temperament: str
    size_class: str
    vaccination_status: str
    temperament_clearance: str
    created_at: str
    updated_at: str
    version: int


class Run(TypedDict):
    id: str
    facility_id: str
    label: str
    kind: str
    size_class: str
    daycare_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    facility_id: str
    pet_id: str
    owner_id: str
    package_id: str
    service_type: str
    start_date: str
    end_date: str
    nights: int
    care_plan: List[dict]
    belongings: List[dict]
    deposit_cents: int
    deposit_paid_cents: int
    total_cents: int
    refund_cents: int
    redeemed_credit: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RunAssignment(TypedDict):
    id: str
    reservation_id: str
    run_id: str
    window_start_date: str
    window_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    reservation_id: str
    kind: str
    scheduled_date: str
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    owner_id: str
    facility_id: str
    tier: str
    credits_total: int
    credits_remaining: int
    cycle_start_date: str
    auto_renew: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only audit rows: only id + created_at
class VaccinationRecord(TypedDict):
    id: str
    pet_id: str
    vaccine: str
    administered_on: str
    expires_on: str
    superseded: bool
    created_at: str


class PackageRedemption(TypedDict):
    id: str
    package_id: str
    reservation_id: str
    credits_used: int
    redeemed_on: str
    reversed: bool
    created_at: str
