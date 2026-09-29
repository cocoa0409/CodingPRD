"""Domain types for the Student Records Transfer API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    RECORDS_CLERK = "RecordsClerk"
    RECORDS_OFFICER = "RecordsOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    LEGAL_AFFAIRS_OFFICER = "LegalAffairsOfficer"
    RECEIVING_REGISTRAR = "ReceivingRegistrar"
    PARENT = "Parent"
    ELIGIBLE_STUDENT = "EligibleStudent"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WITHDRAWAL_PENDING = "WITHDRAWAL_PENDING"
    WITHDRAWN = "WITHDRAWN"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class WithdrawalStatus(str, Enum):
    CLEARED = "CLEARED"
    HOLD = "HOLD"
    COMPLETED = "COMPLETED"


class HoldType(str, Enum):
    UNRETURNED_PROPERTY = "UNRETURNED_PROPERTY"
    LIBRARY_FINE = "LIBRARY_FINE"
    MEAL_ACCOUNT = "MEAL_ACCOUNT"
    SPED_EXIT_MEETING = "SPED_EXIT_MEETING"


class WithdrawalReason(str, Enum):
    TRANSFER_OUT = "TRANSFER_OUT"
    MOVED = "MOVED"
    HOMESCHOOL = "HOMESCHOOL"
    OTHER = "OTHER"


class AssemblyStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_ASSEMBLY = "IN_ASSEMBLY"
    COMPLETE = "COMPLETE"


class ComponentType(str, Enum):
    ACADEMIC = "ACADEMIC"
    HEALTH = "HEALTH"
    DISCIPLINE = "DISCIPLINE"
    SPECIAL_EDUCATION = "SPECIAL_EDUCATION"


class ComponentStatus(str, Enum):
    PENDING = "PENDING"
    COLLECTED = "COLLECTED"
    CERTIFIED = "CERTIFIED"
    EXCLUDED = "EXCLUDED"


class ExclusionReason(str, Enum):
    OTHER_STUDENT_INFO = "OTHER_STUDENT_INFO"
    SEALED_BY_COURT = "SEALED_BY_COURT"
    DUPLICATE_OF_TRANSCRIPT = "DUPLICATE_OF_TRANSCRIPT"


class DisciplineActionType(str, Enum):
    SUSPENSION = "SUSPENSION"
    EXPULSION = "EXPULSION"
    DETENTION = "DETENTION"
    BEHAVIOR_PLAN = "BEHAVIOR_PLAN"


class IncidentStatus(str, Enum):
    SUSTAINED = "SUSTAINED"
    PENDING_INVESTIGATION = "PENDING_INVESTIGATION"
    DISMISSED = "DISMISSED"


class TransferInclusionState(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    INCLUDED = "INCLUDED"
    WITHHELD = "WITHHELD"


class DisciplineInclusionMode(str, Enum):
    ALL_INCIDENTS = "ALL_INCIDENTS"
    SUSPENSIONS_AND_EXPULSIONS = "SUSPENSIONS_AND_EXPULSIONS"
    EXPULSIONS_ONLY = "EXPULSIONS_ONLY"


class RecordsRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    ASSEMBLING = "ASSEMBLING"
    READY_FOR_RELEASE = "READY_FOR_RELEASE"
    RELEASED = "RELEASED"
    DENIED = "DENIED"


class PacketStatus(str, Enum):
    NONE = "NONE"
    SNAPSHOT = "SNAPSHOT"
    VOID = "VOID"


class RequestPriority(str, Enum):
    STANDARD = "STANDARD"
    UNACCOMPANIED_YOUTH = "UNACCOMPANIED_YOUTH"


class DenialReason(str, Enum):
    NO_ENROLLMENT_AUTHORIZATION = "NO_ENROLLMENT_AUTHORIZATION"
    STUDENT_NOT_IN_DISTRICT = "STUDENT_NOT_IN_DISTRICT"
    DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
    COURT_SEALED = "COURT_SEALED"


class TransmissionMethod(str, Enum):
    SECURE_PORTAL = "SECURE_PORTAL"
    ENCRYPTED_EMAIL = "ENCRYPTED_EMAIL"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"


class InspectionRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class RequesterRole(str, Enum):
    PARENT = "PARENT"
    ELIGIBLE_STUDENT = "ELIGIBLE_STUDENT"


class FeeTransactionType(str, Enum):
    PAYMENT = "PAYMENT"
    WAIVER = "WAIVER"
    REVERSAL = "REVERSAL"


class ReviewAppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ATTENDED = "ATTENDED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class RoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class HearingOfficerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class HearingOfficerCredential(str, Enum):
    ADMINISTRATIVE_LAW_JUDGE = "ADMINISTRATIVE_LAW_JUDGE"
    DISTRICT_DESIGNEE = "DISTRICT_DESIGNEE"
    EXTERNAL_CONTRACTOR = "EXTERNAL_CONTRACTOR"


class AmendmentRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DENIED = "DENIED"
    AMENDED = "AMENDED"
    HEARING_REQUESTED = "HEARING_REQUESTED"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    UPHELD = "UPHELD"
    STATEMENT_FILED = "STATEMENT_FILED"


class AmendmentOutcome(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class LegalDemandType(str, Enum):
    JUDICIAL_SUBPOENA = "JUDICIAL_SUBPOENA"
    GRAND_JURY_SUBPOENA = "GRAND_JURY_SUBPOENA"
    LAW_ENFORCEMENT_REQUEST = "LAW_ENFORCEMENT_REQUEST"
    EX_PARTE_ORDER = "EX_PARTE_ORDER"


class LegalDemandStatus(str, Enum):
    RECEIVED = "RECEIVED"
    NOTIFIED = "NOTIFIED"
    PRODUCED = "PRODUCED"


class WaiverBasis(str, Enum):
    GRAND_JURY_ORDER = "GRAND_JURY_ORDER"
    EX_PARTE_COURT_ORDER = "EX_PARTE_COURT_ORDER"
    LAW_ENFORCEMENT_DIRECTIVE = "LAW_ENFORCEMENT_DIRECTIVE"


class NotifiedParty(str, Enum):
    PARENT = "PARENT"
    ELIGIBLE_STUDENT = "ELIGIBLE_STUDENT"


class RetentionScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DESTRUCTION_ELIGIBLE = "DESTRUCTION_ELIGIBLE"
    DESTROYED = "DESTROYED"


class DestructionMethod(str, Enum):
    CROSS_CUT_SHRED = "CROSS_CUT_SHRED"
    INCINERATION = "INCINERATION"
    CERTIFIED_DIGITAL_WIPE = "CERTIFIED_DIGITAL_WIPE"


class DisclosureType(str, Enum):
    INTERDISTRICT_TRANSFER = "INTERDISTRICT_TRANSFER"
    DIRECTORY_INFORMATION = "DIRECTORY_INFORMATION"
    LEGAL_DEMAND = "LEGAL_DEMAND"
    PARENT_INSPECTION = "PARENT_INSPECTION"


class DisclosureSourceType(str, Enum):
    RECORDS_REQUEST = "RECORDS_REQUEST"
    LEGAL_DEMAND = "LEGAL_DEMAND"
    STUDENT_DIRECTORY = "STUDENT_DIRECTORY"
    INSPECTION_REQUEST = "INSPECTION_REQUEST"


class DirectoryCategory(str, Enum):
    NAME = "NAME"
    ADDRESS = "ADDRESS"
    PHONE = "PHONE"
    PHOTO = "PHOTO"
    HONORS = "HONORS"
    SPORTS_PARTICIPATION = "SPORTS_PARTICIPATION"


# --- Entity shapes -------------------------------------------------------


# A state records rule is immutable once registered: only id and created_at.
class StateRecordsRule(TypedDict):
    id: str
    state_code: str
    transfer_response_days: int
    discipline_inclusion_mode: str
    discipline_min_days_removed: int
    include_pending_investigations: bool
    sped_requires_consent: bool
    amendment_hearing_days: int
    destruction_min_age_years: int
    directory_optout_grace_days: int
    notification_wait_days: int
    created_at: str


class District(TypedDict):
    id: str
    name: str
    district_code: str
    state_code: str
    open_request_count: int
    created_at: str
    updated_at: str
    version: int


class InspectionRoom(TypedDict):
    id: str
    room_code: str
    site_name: str
    seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HearingOfficer(TypedDict):
    id: str
    full_name: str
    credential: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    district_id: str
    first_name: str
    last_name: str
    dob: str
    grade_level: int
    has_iep: bool
    guardian_user_id: str
    student_user_id: Optional[str]
    enrollment_status: str
    is_eligible_student: bool
    directory_optout_deadline_at: str
    directory_optout_effective: bool
    directory_optout_received_at: Optional[str]
    directory_optout_categories: List[str]
    exit_effective_date: Optional[str]
    records_disposition_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CumulativeFile(TypedDict):
    id: str
    student_id: str
    assembly_status: str
    required_component_types: List[str]
    total_page_count: int
    included_page_count: int
    excluded_page_count: int
    disclosable_page_count: int
    certified_component_count: int
    completeness_pct: float
    last_packet_snapshot_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FileComponent(TypedDict):
    id: str
    cumulative_file_id: str
    component_type: str
    status: str
    is_required: bool
    page_count: int
    redacted_page_count: int
    disclosable_page_count: int
    amendment_count: int
    statement_of_disagreement_present: bool
    exclusion_reason: Optional[str]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Withdrawal(TypedDict):
    id: str
    student_id: str
    effective_date: str
    destination_district_code: Optional[str]
    withdrawal_reason: str
    status: str
    hold_count: int
    active_hold_types: List[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisciplineIncident(TypedDict):
    id: str
    student_id: str
    incident_date: str
    action_type: str
    description: str
    days_removed: int
    incident_status: str
    adjudicated_by_court: bool
    transfer_inclusion_state: str
    created_at: str
    updated_at: str
    version: int


class RecordsRequest(TypedDict):
    id: str
    student_id: str
    requesting_district_id: str
    responding_district_id: str
    request_priority: str
    includes_special_education: bool
    sped_consent_on_file: bool
    authorization_reference: Optional[str]
    authorization_verified: bool
    status: str
    received_at: str
    statutory_days_allowed: int
    statutory_due_at: str
    is_overdue: bool
    reopen_count: int
    packet_status: str
    packet_page_count: Optional[int]
    included_incident_count: Optional[int]
    withheld_incident_count: Optional[int]
    receiving_state_inclusion_count: Optional[int]
    denial_reason: Optional[str]
    transmission_method: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionRequest(TypedDict):
    id: str
    student_id: str
    requester_user_id: str
    requester_role: str
    requested_categories: List[str]
    copies_requested: bool
    status: str
    statutory_inspection_due_at: str
    inspection_completed_at: Optional[str]
    base_copy_fee_cents: int
    certification_fee_cents: int
    fee_assessed_cents: int
    fee_collected_cents: int
    fee_waived_cents: int
    fee_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class ReviewAppointment(TypedDict):
    id: str
    inspection_request_id: str
    room_id: str
    start_at: str
    end_at: str
    duration_minutes: int
    status: str
    attended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AmendmentRequest(TypedDict):
    id: str
    student_id: str
    contested_component_id: str
    contested_field: str
    requested_change: str
    rationale: str
    requester_user_id: str
    status: str
    initial_decided_by_user_id: Optional[str]
    hearing_decided_by_user_id: Optional[str]
    denied_at: Optional[str]
    hearing_due_at: Optional[str]
    hearing_officer_id: Optional[str]
    hearing_start_at: Optional[str]
    hearing_end_at: Optional[str]
    hearing_duration_minutes: Optional[int]
    statement_text: Optional[str]
    statement_filed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LegalDemand(TypedDict):
    id: str
    student_id: str
    demand_type: str
    issuing_authority: str
    case_reference: str
    production_scope: List[str]
    notification_waived: bool
    waiver_basis: Optional[str]
    status: str
    received_at: str
    notified_party: Optional[str]
    notification_sent_at: Optional[str]
    production_allowed_at: Optional[str]
    produced_at: Optional[str]
    produced_page_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RetentionSchedule(TypedDict):
    id: str
    cumulative_file_id: str
    status: str
    exit_anchor_at: str
    last_activity_at: str
    destruction_min_age_years: int
    destruction_eligible_at: str
    exit_anchored_eligible_at: str
    destruction_method: Optional[str]
    certification_note: Optional[str]
    destroyed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# A disclosure log entry is append-only: only id and created_at.
class DisclosureLogEntry(TypedDict):
    id: str
    student_id: str
    disclosure_type: str
    source_type: str
    source_id: str
    recipient_name: Optional[str]
    legitimate_interest_note: Optional[str]
    disclosed_categories: List[str]
    page_count: int
    disclosed_at: str
    logged_by_user_id: str
    created_at: str
