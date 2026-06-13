"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the full common-field set
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────────────

class QueueEntryStatus(str, Enum):
    RESERVED = "RESERVED"
    WAITING = "WAITING"
    TRIAGED = "TRIAGED"
    IN_REGISTRATION = "IN_REGISTRATION"
    READY_FOR_PROVIDER = "READY_FOR_PROVIDER"
    ROOMED = "ROOMED"
    LEFT_WITHOUT_SEEN = "LEFT_WITHOUT_SEEN"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class ClinicPosture(str, Enum):
    OPEN = "OPEN"
    SURGE = "SURGE"
    DIVERSION = "DIVERSION"


class ExamRoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    CLEANING = "CLEANING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ExamRoomType(str, Enum):
    STANDARD = "STANDARD"
    ISOLATION = "ISOLATION"
    PROCEDURE = "PROCEDURE"


class ProviderCredential(str, Enum):
    MD = "MD"
    DO = "DO"
    NP = "NP"
    PA = "PA"


class VisitClinicalStatus(str, Enum):
    IN_EXAM = "IN_EXAM"
    CHARTING = "CHARTING"
    PENDING_DISCHARGE = "PENDING_DISCHARGE"
    DISCHARGED = "DISCHARGED"
    TRANSFERRED = "TRANSFERRED"


class VisitBillingStatus(str, Enum):
    OPEN = "OPEN"
    CHARGES_POSTED = "CHARGES_POSTED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class VisitDisposition(str, Enum):
    HOME = "HOME"
    ER_TRANSFER = "ER_TRANSFER"
    LWBS = "LWBS"


class CoverageType(str, Enum):
    INSURANCE = "INSURANCE"
    SELF_PAY = "SELF_PAY"


class EligibilityStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class ChargeSourceType(str, Enum):
    VISIT = "VISIT"
    OCC_HEALTH = "OCC_HEALTH"


class OccOrderType(str, Enum):
    DRUG_SCREEN = "DRUG_SCREEN"
    PHYSICAL = "PHYSICAL"
    RESPIRATOR_FIT = "RESPIRATOR_FIT"


class OccResult(str, Enum):
    PENDING = "PENDING"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    PASS = "PASS"
    FAIL = "FAIL"


class OccOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TransferReason(str, Enum):
    ACUITY_ESCALATION = "ACUITY_ESCALATION"
    CAPABILITY_GAP = "CAPABILITY_GAP"
    PATIENT_REQUEST = "PATIENT_REQUEST"


class TransferMode(str, Enum):
    AMBULANCE = "AMBULANCE"
    PRIVATE_VEHICLE = "PRIVATE_VEHICLE"


class ReferralStatus(str, Enum):
    INITIATED = "INITIATED"
    ACCEPTED = "ACCEPTED"
    CANCELLED = "CANCELLED"


class FollowUpStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    DUE = "DUE"
    OVERDUE = "OVERDUE"


class UserRole(str, Enum):
    CLINIC_MANAGER = "ClinicManager"
    FRONT_DESK_CLERK = "FrontDeskClerk"
    TRIAGE_NURSE = "TriageNurse"
    PROVIDER = "Provider"
    PATIENT = "Patient"
    ANONYMOUS = "Anonymous"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ────

class Clinic(TypedDict):
    id: str
    name: str
    exam_room_capacity: int
    surge_threshold: int
    diversion_threshold: int
    avg_provider_minutes_per_esi: dict
    self_pay_discount_pct: float
    posture: str
    active_queue_depth: int
    rooms_occupied: int
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class ExamRoom(TypedDict):
    id: str
    clinic_id: str
    room_label: str
    room_type: str
    status: str
    current_visit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    clinic_id: str
    full_name: str
    credential: str
    on_shift: bool
    active_visit_count: int
    max_concurrent_visits: int
    created_at: str
    updated_at: str
    version: int


class QueueEntry(TypedDict):
    id: str
    clinic_id: str
    patient_id: Optional[str]
    arrival_channel: str
    chief_complaint: str
    reserved_at: Optional[str]
    hold_expires_at: Optional[str]
    esi_level: Optional[int]
    airborne_precaution: bool
    priority_rank: Optional[int]
    estimated_wait_minutes: Optional[int]
    triaged_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    queue_entry_id: str
    legal_name: str
    date_of_birth: str
    is_minor: bool
    guarantor_name: Optional[str]
    consent_signed: bool
    created_at: str
    updated_at: str
    version: int


class Coverage(TypedDict):
    id: str
    patient_id: str
    coverage_type: str
    payer_name: Optional[str]
    member_id: Optional[str]
    copay_cents: int
    eligibility_status: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    queue_entry_id: str
    patient_id: str
    exam_room_id: Optional[str]
    provider_id: str
    clinical_status: str
    billing_status: str
    chart_note: Optional[str]
    acuity_at_rooming: int
    charges_subtotal_cents: int
    patient_responsibility_cents: int
    disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    visit_id: str
    cpt_code: str
    amount_cents: int
    source_type: str
    voided: bool
    created_at: str
    updated_at: str
    version: int


class OccHealthOrder(TypedDict):
    id: str
    queue_entry_id: str
    order_type: str
    employer_name: str
    scheduled_start: str
    duration_minutes: int
    collector_id: str
    room_id: Optional[str]
    result: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    visit_id: str
    destination_facility: str
    transfer_reason: str
    mode: str
    accepted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DischargeInstruction(TypedDict):
    id: str
    visit_id: str
    instructions_text: str
    follow_up_within_days: Optional[int]
    follow_up_due_at: Optional[str]
    follow_up_status: str
    created_at: str
    updated_at: str
    version: int
