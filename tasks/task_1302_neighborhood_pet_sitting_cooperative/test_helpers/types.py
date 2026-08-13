"""Domain types: entity TypedDicts, status enums, role enum for the pet-sitting co-op."""
from enum import Enum
from typing import TypedDict, Optional


class VettingStatus(str, Enum):
    APPLIED = "APPLIED"
    REFERENCES_PENDING = "REFERENCES_PENDING"
    VETTED = "VETTED"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class ReferenceStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    BIRD = "BIRD"
    RABBIT = "RABBIT"
    OTHER = "OTHER"


class SittingRequestStatus(str, Enum):
    OPEN = "OPEN"
    CLAIMED = "CLAIMED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class ClaimStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AssignmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED_PENDING_REVIEW = "COMPLETED_PENDING_REVIEW"
    SETTLED = "SETTLED"
    CANCELLED_BY_OWNER = "CANCELLED_BY_OWNER"
    CANCELLED_BY_SITTER = "CANCELLED_BY_SITTER"
    DISPUTED = "DISPUTED"


class HandoffStatus(str, Enum):
    PENDING = "PENDING"
    HANDED_OFF = "HANDED_OFF"
    RETURNED = "RETURNED"
    LOST = "LOST"


class HandoffMethod(str, Enum):
    IN_PERSON = "IN_PERSON"
    LOCKBOX = "LOCKBOX"
    CONCIERGE = "CONCIERGE"
    SMART_LOCK = "SMART_LOCK"


class EntryEventType(str, Enum):
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"
    INCIDENT_NOTE = "INCIDENT_NOTE"
    PET_FED = "PET_FED"
    MEDICATION_GIVEN = "MEDICATION_GIVEN"
    VET_VISIT = "VET_VISIT"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    EMERGENCY = "EMERGENCY"


class IncidentStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_AT_FAULT = "RESOLVED_AT_FAULT"
    RESOLVED_NO_FAULT = "RESOLVED_NO_FAULT"
    DISMISSED = "DISMISSED"


class DisputeType(str, Enum):
    SITTING_QUALITY = "SITTING_QUALITY"
    CREDIT_BALANCE = "CREDIT_BALANCE"
    ACCESS_DAMAGE = "ACCESS_DAMAGE"
    BEHAVIOR = "BEHAVIOR"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    MEDIATION = "MEDIATION"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_DISMISSED = "RESOLVED_DISMISSED"
    ESCALATED_REMOVAL = "ESCALATED_REMOVAL"


class LedgerEntryType(str, Enum):
    SIT_EARNED = "SIT_EARNED"
    SIT_SPENT = "SIT_SPENT"
    CANCELLATION_PENALTY = "CANCELLATION_PENALTY"
    INCIDENT_PENALTY = "INCIDENT_PENALTY"
    MEDIATION_ADJUSTMENT = "MEDIATION_ADJUSTMENT"
    JOINING_GRANT = "JOINING_GRANT"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    COOP_ADMIN = "CoopAdmin"
    MEMBER = "Member"


class Member(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    address_block: str
    phone: str
    vetting_status: str
    mediator_flag: bool
    credit_balance_hours: float
    provisional_credit_hours: float
    reliability_score: int
    suspension_reason: Optional[str]
    removal_reason: Optional[str]
    accepted_liability_at: Optional[str]
    co_op_joined_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MemberReference(TypedDict, total=False):
    id: str
    subject_member_id: str
    referee_member_id: str
    relationship_years: int
    attestation_text: str
    reciprocal_reference_id: Optional[str]
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PetProfile(TypedDict, total=False):
    id: str
    owner_member_id: str
    pet_name: str
    species: str
    routine_notes: str
    medical_notes: str
    emergency_vet_name: str
    emergency_vet_phone: str
    emergency_vet_address: str
    liability_waiver_accepted: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class HolidayWindow(TypedDict, total=False):
    id: str
    name: str
    window_start: str
    window_end: str
    demand_multiplier: float
    enabled: bool
    created_at: str
    updated_at: str
    version: int


class SittingRequest(TypedDict, total=False):
    id: str
    owner_member_id: str
    pet_profile_id: str
    start_at: str
    end_at: str
    instructions: str
    credit_hours_offered: float
    status: str
    cancelled_reason: Optional[str]
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class SittingClaim(TypedDict, total=False):
    id: str
    sitting_request_id: str
    claimer_member_id: str
    message: str
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SittingAssignment(TypedDict, total=False):
    id: str
    sitting_request_id: str
    owner_member_id: str
    sitter_member_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    actual_start_at: Optional[str]
    actual_end_at: Optional[str]
    credit_hours_settled: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessHandoff(TypedDict, total=False):
    id: str
    sitting_assignment_id: str
    handoff_method: Optional[str]
    access_code_ciphertext: Optional[str]
    handed_off_at: Optional[str]
    returned_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only record (immutable once appended): id + created_at only.
class EntryLog(TypedDict, total=False):
    id: str
    sitting_assignment_id: str
    actor_member_id: str
    event_type: str
    occurred_at: str
    notes: Optional[str]
    created_at: str


class Incident(TypedDict, total=False):
    id: str
    sitting_assignment_id: str
    reporter_member_id: str
    severity: str
    description: str
    vet_involved: bool
    at_fault_member_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    initiator_member_id: str
    respondent_member_id: str
    sitting_assignment_id: Optional[str]
    dispute_type: str
    statement: str
    mediator_member_id: Optional[str]
    status: str
    resolution_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only record (immutable once appended): id + created_at only.
class CreditLedgerEntry(TypedDict, total=False):
    id: str
    member_id: str
    entry_type: str
    delta_hours: float
    sitting_assignment_id: Optional[str]
    dispute_id: Optional[str]
    memo: Optional[str]
    created_at: str
