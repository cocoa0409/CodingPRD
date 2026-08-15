"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class TraumaLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    COMMUNITY = "COMMUNITY"
    CRITICAL_ACCESS = "CRITICAL_ACCESS"


class DiversionStatus(str, Enum):
    OPEN = "OPEN"
    SOFT_DIVERSION = "SOFT_DIVERSION"
    HARD_DIVERSION = "HARD_DIVERSION"


class UnitType(str, Enum):
    ICU = "ICU"
    CVICU = "CVICU"
    NICU = "NICU"
    PICU = "PICU"
    TELEMETRY = "TELEMETRY"
    MED_SURG = "MED_SURG"
    BURN = "BURN"
    ED_HOLD = "ED_HOLD"


class BedStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class Specialty(str, Enum):
    EMERGENCY = "EMERGENCY"
    CARDIOLOGY = "CARDIOLOGY"
    NEUROLOGY = "NEUROLOGY"
    SURGERY = "SURGERY"
    INTENSIVIST = "INTENSIVIST"
    PEDIATRICS = "PEDIATRICS"
    GENERAL = "GENERAL"


class AcuityLevel(str, Enum):
    CRITICAL = "CRITICAL"
    EMERGENT = "EMERGENT"
    URGENT = "URGENT"
    STABLE = "STABLE"


class TransferCaseStatus(str, Enum):
    INTAKE = "INTAKE"
    EMTALA_DETERMINED = "EMTALA_DETERMINED"
    AWAITING_ACCEPTANCE = "AWAITING_ACCEPTANCE"
    ACCEPTED = "ACCEPTED"
    TRANSPORT_ARRANGED = "TRANSPORT_ARRANGED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"


class EmtalaObligation(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    EMTALA_APPLIES = "EMTALA_APPLIES"
    EMTALA_NOT_APPLIES = "EMTALA_NOT_APPLIES"
    EMERGENCY_EXCEPTION = "EMERGENCY_EXCEPTION"


class ScreeningDetermination(str, Enum):
    EMTALA_NOT_APPLIES = "EMTALA_NOT_APPLIES"
    EMTALA_APPLIES = "EMTALA_APPLIES"
    EMERGENCY_EXCEPTION = "EMERGENCY_EXCEPTION"


class ScreeningStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    AMENDED = "AMENDED"


class ContactMethod(str, Enum):
    PHONE = "PHONE"
    SECURE_MESSAGE = "SECURE_MESSAGE"
    TELEMEDICINE = "TELEMEDICINE"


class CommunicationOutcome(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REFUSED = "REFUSED"
    VOIDED = "VOIDED"


class BedHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class HoldReleaseReason(str, Enum):
    MANUAL = "MANUAL"
    SUPERSEDED = "SUPERSEDED"
    CASE_CANCELLED = "CASE_CANCELLED"
    ARRIVAL_CONFIRMED = "ARRIVAL_CONFIRMED"
    EXPIRED = "EXPIRED"


class TransportMode(str, Enum):
    GROUND_BLS = "GROUND_BLS"
    GROUND_ALS = "GROUND_ALS"
    AIR_ROTOR = "AIR_ROTOR"
    AIR_FIXED_WING = "AIR_FIXED_WING"


class CrewCapability(str, Enum):
    BLS = "BLS"
    ALS = "ALS"
    CCT = "CCT"
    CRITICAL_CARE = "CRITICAL_CARE"


class DispatchStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class NotificationChannel(str, Enum):
    PORTAL = "PORTAL"
    PHONE = "PHONE"
    FAX = "FAX"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    NOTIFIED = "NOTIFIED"
    EXCEPTION_CLAIMED = "EXCEPTION_CLAIMED"
    VOIDED = "VOIDED"


class ExceptionReason(str, Enum):
    UNSTABLE_EMC = "UNSTABLE_EMC"
    NO_PAYER_IDENTIFIABLE = "NO_PAYER_IDENTIFIABLE"
    CLINICAL_URGENCY = "CLINICAL_URGENCY"


class DocumentCode(str, Enum):
    H_AND_P = "H_AND_P"
    LABS = "LABS"
    MED_RECONCILIATION = "MED_RECONCILIATION"
    CODE_STATUS = "CODE_STATUS"
    CONSENT = "CONSENT"
    TRANSFER_CERT = "TRANSFER_CERT"


class DocumentStatus(str, Enum):
    DOCUMENTS_COMPLETE = "DOCUMENTS_COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class ImagingStatus(str, Enum):
    IMAGING_COMPLETE = "IMAGING_COMPLETE"
    IMAGING_PENDING = "IMAGING_PENDING"


class PacketOverallStatus(str, Enum):
    READY = "READY"
    INCOMPLETE = "INCOMPLETE"


class RefusalCategory(str, Enum):
    NO_BED_AVAILABLE = "NO_BED_AVAILABLE"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    DIVERSION_ACTIVE = "DIVERSION_ACTIVE"
    UNSTABLE_FOR_TRANSFER = "UNSTABLE_FOR_TRANSFER"
    CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"


class RiskFlag(str, Enum):
    HIGH = "HIGH"
    ELEVATED = "ELEVATED"
    LOW = "LOW"


class ArrivalCondition(str, Enum):
    STABLE = "STABLE"
    DETERIORATED = "DETERIORATED"
    CRITICAL_DECLINE = "CRITICAL_DECLINE"


class ReviewTrigger(str, Enum):
    ROUTINE = "ROUTINE"
    REFUSAL_RISK = "REFUSAL_RISK"
    DETERIORATION = "DETERIORATION"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class ReviewOutcome(str, Enum):
    CONCURRENCE = "CONCURRENCE"
    MINOR_VARIANCE = "MINOR_VARIANCE"
    MAJOR_VARIANCE = "MAJOR_VARIANCE"
    SENTINEL_EVENT = "SENTINEL_EVENT"


class DiversionScope(str, Enum):
    ALL_UNITS = "ALL_UNITS"
    SPECIFIC_UNIT = "SPECIFIC_UNIT"


class DiversionEffectiveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    LIFTED = "LIFTED"


class UserRole(str, Enum):
    TRANSFER_COORDINATOR = "TransferCoordinator"
    SENDING_PHYSICIAN = "SendingPhysician"
    RECEIVING_PHYSICIAN = "ReceivingPhysician"
    BED_MANAGER = "BedManager"
    QUALITY_REVIEWER = "QualityReviewer"
    ANY = "Any"


class Facility(TypedDict, total=False):
    id: str
    name: str
    facility_code: str
    trauma_level: str
    capabilities: List[str]
    diversion_status: str
    operational_bed_count: int
    unavailable_bed_count: int
    occupancy_pct: float
    created_at: str
    updated_at: str
    version: int


class Bed(TypedDict, total=False):
    id: str
    facility_id: str
    bed_code: str
    unit_type: str
    isolation_capable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict, total=False):
    id: str
    full_name: str
    facility_id: str
    specialty: str
    is_on_call: bool
    created_at: str
    updated_at: str
    version: int


class TransferCase(TypedDict, total=False):
    id: str
    patient_ref: str
    sending_facility_id: str
    sending_physician_id: str
    receiving_facility_id: Optional[str]
    receiving_physician_id: Optional[str]
    acuity_level: str
    required_unit_type: str
    requires_isolation: bool
    required_capability: str
    status: str
    emtala_obligation: str
    emtala_determined_at: Optional[str]
    active_bed_hold_id: Optional[str]
    negotiation_round: int
    refusal_count: int
    created_at: str
    updated_at: str
    version: int


class EmtalaScreening(TypedDict, total=False):
    id: str
    transfer_case_id: str
    has_emergency_medical_condition: bool
    is_stabilized: bool
    benefits_outweigh_risks: bool
    physician_certification: str
    determination: str
    status: str
    certified_at: Optional[str]
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class PhysicianCommunication(TypedDict, total=False):
    # Append-only record: carries only id + created_at from the shared envelope.
    id: str
    created_at: str
    transfer_case_id: str
    from_physician_id: str
    to_physician_id: str
    round: int
    contact_method: str
    notes: str
    outcome: str
    responded_at: Optional[str]


class BedHold(TypedDict, total=False):
    id: str
    bed_id: str
    transfer_case_id: str
    status: str
    hold_started_at: str
    hold_expires_at: str
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransportDispatch(TypedDict, total=False):
    id: str
    transfer_case_id: str
    mode: str
    crew_capability: str
    distance_miles: float
    estimated_minutes_optimistic: int
    estimated_minutes_conservative: int
    actual_duration_minutes: Optional[int]
    status: str
    dispatched_at: str
    departed_at: Optional[str]
    arrived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InsuranceNotification(TypedDict, total=False):
    id: str
    transfer_case_id: str
    payer_id: str
    channel: str
    sla_due_at: str
    notified_at: Optional[str]
    status: str
    is_late: bool
    exception_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClinicalPacket(TypedDict, total=False):
    id: str
    transfer_case_id: str
    required_documents: List[str]
    received_documents: List[str]
    imaging_studies: List[dict]
    exchanged_study_refs: List[str]
    document_status: str
    imaging_status: str
    overall_status: str
    created_at: str
    updated_at: str
    version: int


class RefusalRecord(TypedDict, total=False):
    # Append-only record: carries only id + created_at from the shared envelope.
    id: str
    created_at: str
    transfer_case_id: str
    facility_id: str
    refusing_physician_id: str
    refusal_category: str
    narrative: str
    emtala_risk_score: int
    emtala_risk_flag: str
    round: int


class TransferOutcome(TypedDict, total=False):
    # Append-only record: carries only id + created_at from the shared envelope.
    id: str
    created_at: str
    transfer_case_id: str
    arrival_condition: str
    deterioration_en_route: bool
    receiving_physician_confirmed: bool
    door_to_arrival_minutes: int
    recorded_at: str


class QualityReview(TypedDict, total=False):
    id: str
    transfer_case_id: str
    trigger: str
    status: str
    reviewer_physician_id: Optional[str]
    timeliness_score: Optional[float]
    documentation_score: Optional[float]
    protocol_score: Optional[float]
    composite_score: Optional[float]
    outcome: Optional[str]
    findings: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiversionEvent(TypedDict, total=False):
    id: str
    facility_id: str
    scope: str
    unit_type: Optional[str]
    starts_at: str
    ends_at: str
    reason: str
    auto_created: bool
    lifted_at: Optional[str]
    effective_status: str
    created_at: str
    updated_at: str
    version: int
