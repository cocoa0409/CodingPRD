"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    SHELTER_ADMIN = "ShelterAdmin"
    INTAKE_OFFICER = "IntakeOfficer"
    VETERINARIAN = "Veterinarian"
    ADOPTION_COUNSELOR = "AdoptionCounselor"
    FOSTER_COORDINATOR = "FosterCoordinator"
    ADOPTER = "Adopter"


# ─── Status enums ─────────────────────────────────────
class AnimalLifecycleStatus(str, Enum):
    INTAKE_PENDING = "INTAKE_PENDING"
    IN_CUSTODY = "IN_CUSTODY"
    AVAILABLE = "AVAILABLE"
    FOSTERED = "FOSTERED"
    ADOPTED = "ADOPTED"
    RECLAIMED = "RECLAIMED"
    EUTHANIZED = "EUTHANIZED"


class AnimalMedicalStatus(str, Enum):
    UNEXAMINED = "UNEXAMINED"
    EXAM_PENDING = "EXAM_PENDING"
    NEEDS_TREATMENT = "NEEDS_TREATMENT"
    CLEARED = "CLEARED"


class KennelStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class KennelAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class IntakeSource(str, Enum):
    STRAY = "STRAY"
    SURRENDER = "SURRENDER"
    TRANSFER = "TRANSFER"


class MedicalRecordType(str, Enum):
    EXAM = "EXAM"
    SPAY_NEUTER = "SPAY_NEUTER"
    VACCINATION = "VACCINATION"


class MedicalOutcome(str, Enum):
    CLEAR = "CLEAR"
    HOLD = "HOLD"


class OwnerClaimStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AdoptionApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FINALIZED = "FINALIZED"
    REFUNDED = "REFUNDED"


class FosterPlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"


class EuthanasiaReason(str, Enum):
    MEDICAL_UNTREATABLE = "MEDICAL_UNTREATABLE"
    BEHAVIORAL = "BEHAVIORAL"
    COURT_ORDER = "COURT_ORDER"


class EuthanasiaDecisionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"


# ─── Entity TypedDicts ────────────────────────────────
# Entities below carry the full common-field quartet:
#   id, created_at, updated_at, version
# except Microchip, which is immutable (id + created_at only).

class Shelter(TypedDict):
    id: str
    name: str
    stray_hold_days: int
    promo_active: bool
    collected_fee_cents: int
    dog_daily_board_cents: int
    cat_daily_board_cents: int
    created_at: str
    updated_at: str
    version: int


class Kennel(TypedDict):
    id: str
    label: str
    capacity: int
    occupied_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Animal(TypedDict):
    id: str
    name: str
    species: str
    age_months: int
    lifecycle_status: str
    medical_status: str
    microchipped: bool
    stray_hold_release_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IntakeRecord(TypedDict):
    id: str
    animal_id: str
    source: str
    intake_at: str
    surrendering_party: Optional[str]
    stray_hold_release_at: str
    created_at: str
    updated_at: str
    version: int


class KennelAssignment(TypedDict):
    id: str
    kennel_id: str
    animal_id: str
    start_at: str
    end_at: Optional[str]
    status: str
    actual_board_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MedicalRecord(TypedDict):
    id: str
    animal_id: str
    record_type: str
    outcome: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Microchip — common_fields: false. Immutable registry row.
# Carries ONLY id + created_at; NO updated_at, NO version.
class Microchip(TypedDict):
    id: str
    animal_id: str
    chip_number: str
    owner_name: Optional[str]
    owner_phone: Optional[str]
    created_at: str


class OwnerClaim(TypedDict):
    id: str
    animal_id: str
    claimant_name: str
    proof_chip_number: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AdopterAccount(TypedDict):
    id: str
    full_name: str
    email: str
    phone: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdoptionApplication(TypedDict):
    id: str
    animal_id: str
    adopter_id: str
    status: str
    estimated_fee_cents: int
    final_fee_cents: Optional[int]
    refunded: bool
    created_at: str
    updated_at: str
    version: int


class FosterHome(TypedDict):
    id: str
    contact_name: str
    max_concurrent: int
    cooldown_days: int
    active_placement_count: int
    created_at: str
    updated_at: str
    version: int


class FosterPlacement(TypedDict):
    id: str
    foster_home_id: str
    animal_id: str
    start_at: str
    end_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EuthanasiaDecision(TypedDict):
    id: str
    animal_id: str
    requested_by_user_id: str
    reason: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
