"""Domain types derived from scaffold Tables 1, 2, 7."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# --- Status enums (Table 2) ---

class ShelterStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class AnimalStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    ADOPTED = "ADOPTED"
    BOARDING_ONLY = "BOARDING_ONLY"
    RETIRED = "RETIRED"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    RABBIT = "RABBIT"
    OTHER = "OTHER"


class SpecialCareLevel(str, Enum):
    NONE = "NONE"
    MEDICAL = "MEDICAL"
    BEHAVIORAL = "BEHAVIORAL"


class VaccineType(str, Enum):
    RABIES = "RABIES"
    DISTEMPER = "DISTEMPER"
    PARVO = "PARVO"
    BORDETELLA = "BORDETELLA"
    FELV = "FELV"


class HomeVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUBMITTED = "SUBMITTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AdopterHomeVisitStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class AdoptionApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    HOME_VISIT_REQUIRED = "HOME_VISIT_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FINALIZED = "FINALIZED"
    WITHDRAWN = "WITHDRAWN"


class BoardingReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class FeeSettlementStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class SettlementSubjectType(str, Enum):
    ADOPTION = "ADOPTION"
    BOARDING = "BOARDING"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    BANK_TRANSFER = "BANK_TRANSFER"
    CASH = "CASH"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


# --- User Roles (Table 7) ---

class UserRole(str, Enum):
    SHELTER_ADMIN = "ShelterAdmin"
    VETERINARIAN = "Veterinarian"
    ADOPTION_REVIEWER = "AdoptionReviewer"
    ADOPTION_APPROVER = "AdoptionApprover"
    HOME_VISIT_INSPECTOR = "HomeVisitInspector"
    BOARDING_COORDINATOR = "BoardingCoordinator"
    FINANCE_OFFICER = "FinanceOfficer"
    ADOPTER = "Adopter"


# --- Entity TypedDicts (Table 1) ---

class Shelter(TypedDict, total=False):
    id: str
    name: str
    boarding_capacity: int
    reserved_slots: int
    available_slots: int
    adoption_fee_base: int
    boarding_rate_per_night: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Animal(TypedDict, total=False):
    id: str
    shelter_id: str
    name: str
    species: str
    age_months: int
    temperament_tags: List[str]
    adoption_fee_override: Optional[int]
    special_care_level: str
    intake_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VaccinationRecord(TypedDict, total=False):
    id: str
    animal_id: str
    vaccine_type: str
    administered_date: str
    expires_date: str
    lot_number: str
    created_at: str


class Adopter(TypedDict, total=False):
    id: str
    full_name: str
    household_size: int
    has_yard: bool
    home_visit_status: str
    home_visit_expires_at: Optional[str]
    disqualified: bool
    created_at: str
    updated_at: str
    version: int


class HomeVisit(TypedDict, total=False):
    id: str
    adopter_id: str
    scheduled_for: str
    completed_at: Optional[str]
    safety_score: Optional[int]
    yard_verified: bool
    inspector_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AdoptionApplication(TypedDict, total=False):
    id: str
    adopter_id: str
    animal_id: str
    shelter_id: str
    pinned_animal_version: Optional[int]
    pinned_vaccination_snapshot: Optional[List[Any]]
    pinned_fee: Optional[int]
    review_notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardingReservation(TypedDict, total=False):
    id: str
    shelter_id: str
    animal_id: str
    owner_id: str
    check_in_date: str
    check_out_date: str
    nights: int
    quoted_total: int
    final_total: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeSettlement(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    amount: int
    method: str
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceIncident(TypedDict, total=False):
    id: str
    animal_id: str
    incident_type: str
    triggered_by: str
    detail: str
    created_at: str
