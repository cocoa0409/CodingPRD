"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Pet Licensing & Animal Control PRD (§2.4, §3.1–§3.8).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    OWNER = "Owner"
    LICENSING_CLERK = "LicensingClerk"
    ANIMAL_CONTROL_OFFICER = "AnimalControlOfficer"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"


class PetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECEASED = "DECEASED"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"


class VaccineType(str, Enum):
    RABIES = "RABIES"
    DHPP = "DHPP"
    FVRCP = "FVRCP"


class KennelStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class LicenseKind(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    KENNEL = "KENNEL"


class LicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_VACCINATION_PROOF = "NEEDS_VACCINATION_PROOF"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class TagStatus(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class DangerousDogSeverity(str, Enum):
    BITE = "BITE"
    ATTACK = "ATTACK"
    NUISANCE = "NUISANCE"


class DangerousDogStatus(str, Enum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    DESIGNATED = "DESIGNATED"
    APPEALED = "APPEALED"
    OVERTURNED = "OVERTURNED"
    DISMISSED = "DISMISSED"


class ReportType(str, Enum):
    LOST = "LOST"
    FOUND = "FOUND"


class LostFoundStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Records carrying the full system-managed set (id + created_at + updated_at +
# version), per PRD §2.4: owner, pet, kennel, license, tag, dangerous-dog case,
# lost-and-found report.
# ---------------------------------------------------------------------------
class Owner(TypedDict):
    id: str
    full_name: str
    email: str
    address_zip: str
    status: str
    active_license_count: int
    outstanding_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class Pet(TypedDict):
    id: str
    owner_id: str
    name: str
    species: str
    breed: str
    is_altered: bool
    birth_date: str
    is_dangerous: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Kennel(TypedDict):
    id: str
    owner_id: str
    facility_name: str
    slot_capacity: int
    occupied_slots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    owner_id: str
    pet_id: str
    kennel_id: Optional[str]
    license_kind: str
    term_years: int
    vaccination_record_id: Optional[str]
    status: str
    provisional_fee_cents: int
    final_fee_cents: int
    late_penalty_cents: int
    penalty_paid: bool
    issued_on: Optional[str]
    expires_on: Optional[str]
    tag_serial: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tag(TypedDict):
    id: str
    license_id: str
    serial: str
    status: str
    issued_on: str
    created_at: str
    updated_at: str
    version: int


class DangerousDogCase(TypedDict):
    id: str
    pet_id: str
    incident_summary: str
    severity: str
    status: str
    surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class LostFoundReport(TypedDict):
    id: str
    report_type: str
    pet_id: Optional[str]
    tag_serial_seen: Optional[str]
    species: str
    zip_seen: str
    reported_at: str
    status: str
    matched_report_id: Optional[str]
    match_score: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable records (PRD §2.4): only id + created_at — NO updated_at, NO version.
# ---------------------------------------------------------------------------
class VaccinationRecord(TypedDict):
    id: str
    pet_id: str
    vaccine_type: str
    administered_on: str
    expires_on: str
    vet_license_no: str
    created_at: str


class AuditEvent(TypedDict):
    id: str
    subject_entity: str
    subject_id: str
    action: str
    actor_role: str
    created_at: str
