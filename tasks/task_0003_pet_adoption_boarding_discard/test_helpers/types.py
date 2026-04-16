"""Domain types derived from scaffold Tables 1, 2, 7."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums (Table 2)
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


class AdoptionApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    HOME_VISIT_REQUIRED = "HOME_VISIT_REQUIRED"
    HOME_VISIT_SCHEDULED = "HOME_VISIT_SCHEDULED"
    REVIEWED = "REVIEWED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class HomeVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class HomeVisitResult(str, Enum):
    PASS = "PASS"
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
    PAID = "PAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class ComplianceHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class AdopterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLACKLISTED = "BLACKLISTED"


# ---------------------------------------------------------------------------
# Enum value sets from Table 1
# ---------------------------------------------------------------------------

class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    RABBIT = "RABBIT"
    BIRD = "BIRD"
    OTHER = "OTHER"


class Temperament(str, Enum):
    CALM = "CALM"
    MODERATE = "MODERATE"
    ENERGETIC = "ENERGETIC"
    AGGRESSIVE = "AGGRESSIVE"


class HomeType(str, Enum):
    HOUSE = "HOUSE"
    APARTMENT = "APARTMENT"
    FARM = "FARM"
    OTHER = "OTHER"


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


class FeeType(str, Enum):
    ADOPTION_BASE = "ADOPTION_BASE"
    BOARDING_DAILY = "BOARDING_DAILY"
    SPECIAL_NEEDS_SURCHARGE = "SPECIAL_NEEDS_SURCHARGE"
    VACCINATION_FEE = "VACCINATION_FEE"
    LOYALTY_DISCOUNT = "LOYALTY_DISCOUNT"


class ReferenceType(str, Enum):
    ADOPTION = "ADOPTION"
    BOARDING = "BOARDING"


# ---------------------------------------------------------------------------
# Role enum (Table 7)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ShelterManager = "ShelterManager"
    CaseWorker = "CaseWorker"
    Veterinarian = "Veterinarian"
