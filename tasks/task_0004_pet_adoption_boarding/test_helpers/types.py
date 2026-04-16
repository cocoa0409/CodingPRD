"""Domain types derived from scaffold Tables 1, 2, 7."""
from enum import Enum


# ---------------------------------------------------------------------------
# Status enums (Table 2 — state machines)
# ---------------------------------------------------------------------------

class ShelterStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class AnimalStatus(str, Enum):
    INTAKE = "INTAKE"
    AVAILABLE = "AVAILABLE"
    ADOPTION_PENDING = "ADOPTION_PENDING"
    ADOPTED = "ADOPTED"
    BOARDING = "BOARDING"
    UNAVAILABLE = "UNAVAILABLE"


class AdopterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLACKLISTED = "BLACKLISTED"


class AdoptionApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    HOME_VISIT_REQUIRED = "HOME_VISIT_REQUIRED"
    HOME_VISIT_SCHEDULED = "HOME_VISIT_SCHEDULED"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class HomeVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class HomeVisitResult(str, Enum):
    PASS_ = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class BoardingReservationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class FeeInvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class ComplianceHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class SettlementBatchStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"


# ---------------------------------------------------------------------------
# Domain enums
# ---------------------------------------------------------------------------

class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    RABBIT = "RABBIT"
    BIRD = "BIRD"
    OTHER = "OTHER"
    ALL = "ALL"


class Temperament(str, Enum):
    CALM = "CALM"
    MODERATE = "MODERATE"
    ENERGETIC = "ENERGETIC"
    AGGRESSIVE = "AGGRESSIVE"


class VaccineName(str, Enum):
    RABIES = "RABIES"
    DHPP = "DHPP"
    FVRCP = "FVRCP"
    BORDETELLA = "BORDETELLA"
    RHDV = "RHDV"
    OTHER = "OTHER"


class HomeType(str, Enum):
    HOUSE = "HOUSE"
    APARTMENT = "APARTMENT"
    FARM = "FARM"
    OTHER = "OTHER"


class FeeType(str, Enum):
    ADOPTION_BASE = "ADOPTION_BASE"
    BOARDING_DAILY = "BOARDING_DAILY"
    SPECIAL_NEEDS_SURCHARGE = "SPECIAL_NEEDS_SURCHARGE"
    LOYALTY_DISCOUNT_PCT = "LOYALTY_DISCOUNT_PCT"


class ReferenceType(str, Enum):
    ADOPTION = "ADOPTION"
    BOARDING = "BOARDING"


class HoldType(str, Enum):
    VACCINATION_OVERDUE = "VACCINATION_OVERDUE"
    HEALTH_CONCERN = "HEALTH_CONCERN"
    BEHAVIOR_INCIDENT = "BEHAVIOR_INCIDENT"
    QUARANTINE = "QUARANTINE"


class HoldSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ImposedRole(str, Enum):
    VETERINARIAN = "VETERINARIAN"
    SHELTER_MANAGER = "SHELTER_MANAGER"


class BoardingZone(str, Enum):
    GENERAL = "GENERAL"
    ACTIVE = "ACTIVE"
    SMALL_ANIMAL = "SMALL_ANIMAL"
    ISOLATION = "ISOLATION"


class UserRole(str, Enum):
    SHELTER_MANAGER = "ShelterManager"
    CASE_WORKER = "CaseWorker"
    VETERINARIAN = "Veterinarian"
