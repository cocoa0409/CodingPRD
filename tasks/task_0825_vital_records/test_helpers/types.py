"""Domain types: entity TypedDicts, status enums, role enum (Vital Records API)."""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---
class UserRole(str, Enum):
    STATE_REGISTRAR = "StateRegistrar"
    FACILITY_FILER = "FacilityFiler"
    MEDICAL_CERTIFIER = "MedicalCertifier"
    APPLICANT = "Applicant"


# --- Status enums ---
class VitalEventStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    RETURNED = "RETURNED"
    REGISTERED = "REGISTERED"
    AMENDED = "AMENDED"
    VOIDED = "VOIDED"


class RegistrationType(str, Enum):
    TIMELY = "TIMELY"
    DELAYED = "DELAYED"
    FOREIGN = "FOREIGN"


class MedicalCertificationStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    LOCKED = "LOCKED"
    AMENDED = "AMENDED"


class AmendmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PaternityStatus(str, Enum):
    DRAFT = "DRAFT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESCINDED = "RESCINDED"
    FINALIZED = "FINALIZED"


class CopyRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ID_VERIFIED = "ID_VERIFIED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"


class CopyClass(str, Enum):
    CERTIFIED = "CERTIFIED"
    INFORMATIONAL = "INFORMATIONAL"


class ApostilleStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AUTHENTICATED = "AUTHENTICATED"
    REJECTED = "REJECTED"


class PacketStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


# --- Entity TypedDicts (all entities carry common fields id/created_at/updated_at/version) ---
class Facility(TypedDict):
    id: str
    name: str
    facility_type: str
    jurisdiction_code: str
    npi: str
    active: bool
    registered_count: int
    created_at: str
    updated_at: str
    version: int


class Certifier(TypedDict):
    id: str
    name: str
    certifier_type: str
    license_number: str
    jurisdiction_code: str
    active: bool
    locked_certification_count: int
    created_at: str
    updated_at: str
    version: int


class VitalEvent(TypedDict):
    id: str
    event_type: str
    event_date: str
    subject_last_name: str
    subject_first_name: str
    sex: str
    jurisdiction_code: str
    facility_id: str
    place_of_event: str
    foreign_born: bool
    status: str
    registration_type: Optional[str]
    days_late: int
    delayed_fee_cents: int
    certification_required: bool
    filed_at: Optional[str]
    registered_at: Optional[str]
    state_file_number: Optional[str]
    paternity_established: bool
    father_last_name: Optional[str]
    father_first_name: Optional[str]
    cause_of_death_amended: bool
    amendment_count: int
    copies_issued_count: int
    fees_collected_cents: int
    created_at: str
    updated_at: str
    version: int


class MedicalCertification(TypedDict):
    id: str
    vital_event_id: str
    certifier_id: str
    cause_of_death: str
    manner_of_death: str
    status: str
    certified_at: Optional[str]
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class Amendment(TypedDict):
    id: str
    vital_event_id: str
    amendment_type: str
    target_certification_id: Optional[str]
    field_name: str
    new_value: str
    reason: str
    evidence_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PaternityAcknowledgment(TypedDict):
    id: str
    vital_event_id: str
    father_last_name: str
    father_first_name: str
    mother_consent: bool
    filed_by_user_id: str
    status: str
    acknowledged_at: Optional[str]
    rescission_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertifiedCopyRequest(TypedDict):
    id: str
    vital_event_id: str
    requester_name: str
    requester_relationship: str
    requester_category: str
    id_document_type: str
    copy_count: int
    expedite: bool
    id_verified: bool
    copy_class: Optional[str]
    fee_total_cents: int
    status: str
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApostilleRequest(TypedDict):
    id: str
    certified_copy_request_id: str
    destination_country: str
    apostille_type: str
    status: str
    authenticated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DelayedRegistrationPacket(TypedDict):
    id: str
    vital_event_id: str
    packet_type: str
    documentary_evidence_count: int
    hearing_start: str
    hearing_end: str
    hearing_jurisdiction_code: str
    status: str
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StatisticsReport(TypedDict):
    id: str
    jurisdiction_code: str
    period_start: str
    period_end: str
    birth_count: int
    death_count: int
    fetal_death_count: int
    total_fees_collected_cents: int
    state_remittance_cents: int
    created_at: str
    updated_at: str
    version: int
