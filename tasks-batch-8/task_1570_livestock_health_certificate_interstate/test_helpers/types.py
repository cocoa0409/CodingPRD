"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import Optional, TypedDict


class SpeciesCode(str, Enum):
    CATTLE = "CATTLE"
    SWINE = "SWINE"
    POULTRY = "POULTRY"
    SHEEP_GOAT = "SHEEP_GOAT"
    EQUINE = "EQUINE"


class TestType(str, Enum):
    BRUCELLOSIS = "BRUCELLOSIS"
    TUBERCULOSIS = "TUBERCULOSIS"
    EIA = "EIA"
    PULLORUM = "PULLORUM"
    NONE = "NONE"


class DiseaseCode(str, Enum):
    AVIAN_INFLUENZA = "AVIAN_INFLUENZA"
    BRUCELLOSIS = "BRUCELLOSIS"
    TUBERCULOSIS = "TUBERCULOSIS"
    EIA = "EIA"
    PULLORUM = "PULLORUM"
    VESICULAR_STOMATITIS = "VESICULAR_STOMATITIS"
    PSEUDORABIES = "PSEUDORABIES"


class DiseaseStatus(str, Enum):
    ACCREDITED_FREE = "ACCREDITED_FREE"
    MONITORED = "MONITORED"
    QUARANTINE_HOLD = "QUARANTINE_HOLD"
    INFECTED = "INFECTED"


class VetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RequirementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TestResult(str, Enum):
    RESULT_PENDING = "RESULT_PENDING"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class CertificateStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"
    ISSUED = "ISSUED"
    TRANSMITTED = "TRANSMITTED"
    ENTRY_BLOCKED = "ENTRY_BLOCKED"
    LAPSED = "LAPSED"
    VOID = "VOID"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    SUSPENDED = "SUSPENDED"
    VOIDED = "VOIDED"


class MovementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ZoneStatus(str, Enum):
    MONITORING = "MONITORING"
    ACTIVE = "ACTIVE"
    CONTAINED = "CONTAINED"
    RESOLVED = "RESOLVED"


class ZoneSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class QuarantineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"
    EXPIRED = "EXPIRED"


class TransmissionStatus(str, Enum):
    QUEUED = "QUEUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"


class TransmissionChannel(str, Enum):
    XML_GATEWAY = "XML_GATEWAY"
    EMAIL = "EMAIL"
    PORTAL = "PORTAL"


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    STATE_VET_OFFICER = "StateVetOfficer"
    ACCREDITED_VET = "AccreditedVet"
    LAB_TECHNICIAN = "LabTechnician"
    STATE_AUDITOR = "StateAuditor"


# All entities carry the full common set: id, created_at, updated_at, version
# (PRD §2.6: "All entities in this program ... carry the full common set").


class Premises(TypedDict, total=False):
    id: str
    name: str
    county: str
    state_code: str
    species_code: str
    initial_head_count: int
    current_head_count: int
    disease_status: str
    created_at: str
    updated_at: str
    version: int


class Veterinarian(TypedDict, total=False):
    id: str
    full_name: str
    accreditation_number: str
    accreditation_expires_at: str
    status: str
    is_credential_current: bool
    created_at: str
    updated_at: str
    version: int


class EntryRequirement(TypedDict, total=False):
    id: str
    destination_state_code: str
    species_code: str
    test_type: str
    test_validity_days: int
    vaccination_required: bool
    vaccination_min_days_before_inspection: int
    permit_required: bool
    effective_from: str
    effective_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TestRecord(TypedDict, total=False):
    id: str
    premises_id: str
    species_code: str
    test_type: str
    test_date: str
    lab_reference: str
    result: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    origin_premises_id: str
    vet_id: str
    destination_state_code: str
    species_code: str
    head_count: int
    inspection_date: str
    test_record_id: Optional[str]
    vaccination_date: Optional[str]
    consignment_description: Optional[str]
    status: str
    pre_block_status: Optional[str]
    reject_reason: Optional[str]
    void_reason: Optional[str]
    cvi_number: Optional[str]
    issued_at: Optional[str]
    valid_until: Optional[str]
    provisional_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MovementPermit(TypedDict, total=False):
    id: str
    certificate_id: str
    allocated_head_count: int
    valid_from: str
    valid_until: str
    status: str
    permit_number: Optional[str]
    committed_headroom: int
    projected_headroom: int
    total_movement_fees_cents: int
    created_at: str
    updated_at: str
    version: int


class MovementRecord(TypedDict, total=False):
    id: str
    permit_id: str
    head_count: int
    destination_name: str
    destination_county: Optional[str]
    planned_ship_date: str
    status: str
    departed_at: Optional[str]
    arrived_at: Optional[str]
    movement_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class OutbreakZone(TypedDict, total=False):
    id: str
    county: str
    state_code: str
    disease_code: str
    species_code: str
    severity: str
    effective_from: str
    effective_until: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QuarantineOrder(TypedDict, total=False):
    id: str
    premises_id: str
    species_code: str
    disease_code: str
    start_at: str
    end_at: str
    reason: str
    issued_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TransmissionAudit(TypedDict, total=False):
    id: str
    certificate_id: str
    destination_state_code: str
    channel: str
    payload_digest: str
    status: str
    failure_reason: Optional[str]
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
