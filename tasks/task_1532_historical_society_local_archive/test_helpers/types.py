"""Domain types: entity TypedDicts, status enums, role enum.

Every resource carries the standard system-managed fields (id, created_at,
updated_at, version) described in PRD section 2.4.
"""
from enum import Enum
from typing import Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    REGISTRAR = "Registrar"
    ARCHIVIST = "Archivist"
    READING_ROOM_STAFF = "ReadingRoomStaff"
    BOARD_OFFICER = "BoardOfficer"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    VOLUNTEER = "Volunteer"
    RESEARCHER = "Researcher"
    SYSTEM_ADMIN = "SystemAdmin"


class ZonePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class CollectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACCESSIONED = "DEACCESSIONED"


class AccessionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_DEED = "PENDING_DEED"
    ACCESSIONED = "ACCESSIONED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    WITHDRAWN = "WITHDRAWN"


class DeedStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class ItemStatus(str, Enum):
    PENDING_CATALOG = "PENDING_CATALOG"
    CATALOGED = "CATALOGED"
    AVAILABLE = "AVAILABLE"
    FLAGGED_CONSERVATION = "FLAGGED_CONSERVATION"
    IN_TREATMENT = "IN_TREATMENT"
    ZONE_HOLD = "ZONE_HOLD"
    DEACCESSIONED = "DEACCESSIONED"


class ConditionGrade(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    FRAGILE = "FRAGILE"


class ItemFormat(str, Enum):
    MANUSCRIPT = "MANUSCRIPT"
    PHOTOGRAPH = "PHOTOGRAPH"
    MAP = "MAP"
    ARTIFACT = "ARTIFACT"
    AUDIOVISUAL = "AUDIOVISUAL"
    BOUND_VOLUME = "BOUND_VOLUME"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    IN_TREATMENT = "IN_TREATMENT"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class FindingAidStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    PUBLISHED = "PUBLISHED"
    IN_REVISION = "IN_REVISION"
    RETIRED = "RETIRED"


class ProjectStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class TicketStatus(str, Enum):
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    IN_CAPTURE = "IN_CAPTURE"
    QC_REVIEW = "QC_REVIEW"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class ResearcherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RequestPurpose(str, Enum):
    PERSONAL = "PERSONAL"
    ACADEMIC = "ACADEMIC"
    COMMERCIAL = "COMMERCIAL"
    PUBLICATION = "PUBLICATION"


class RequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class RoomCode(str, Enum):
    MAIN = "MAIN"
    MAP_ROOM = "MAP_ROOM"


class AppointmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    NEEDS_RESCHEDULE = "NEEDS_RESCHEDULE"
    CANCELLED = "CANCELLED"


class ReproFormat(str, Enum):
    SCAN_STANDARD = "SCAN_STANDARD"
    SCAN_HIGHRES = "SCAN_HIGHRES"
    PRINT_PHOTOGRAPH = "PRINT_PHOTOGRAPH"


class LicenseClass(str, Enum):
    PERSONAL = "PERSONAL"
    NONPROFIT_PUBLICATION = "NONPROFIT_PUBLICATION"
    COMMERCIAL_PUBLICATION = "COMMERCIAL_PUBLICATION"


class OrderStatus(str, Enum):
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    DELIVERED = "DELIVERED"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"


class DisposalMethod(str, Enum):
    SALE = "SALE"
    TRANSFER = "TRANSFER"
    DESTRUCTION = "DESTRUCTION"
    RETURN_TO_DONOR = "RETURN_TO_DONOR"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    BOARD_REVIEW = "BOARD_REVIEW"
    APPROVED = "APPROVED"
    COOLED_OFF = "COOLED_OFF"
    FINALIZED = "FINALIZED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class RecordingRoom(str, Enum):
    STUDIO_A = "STUDIO_A"
    STUDIO_B = "STUDIO_B"


class RecordingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECORDED = "RECORDED"
    TRANSCRIBED = "TRANSCRIBED"
    IN_REVIEW = "IN_REVIEW"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class ReleaseStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"


# --- Entity TypedDicts (all entities carry the common fields of PRD 2.4) ---

class StorageZone(TypedDict, total=False):
    id: str
    zone_code: str
    name: str
    temp_high_c: float
    temp_low_c: float
    humidity_high_pct: float
    humidity_low_pct: float
    posture: str
    breach_streak: int
    recent_readings: List[dict]
    created_at: str
    updated_at: str
    version: int


class Collection(TypedDict, total=False):
    id: str
    title: str
    collection_code: str
    parent_collection_id: Optional[str]
    storage_zone_id: str
    status: str
    item_count: int
    published_finding_aid_present: bool
    created_at: str
    updated_at: str
    version: int


class Accession(TypedDict, total=False):
    id: str
    donor_name: str
    donor_contact: str
    accession_date: str
    lot_appraised_value_cents: int
    accession_number: str
    status: str
    current_deed_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeedOfGift(TypedDict, total=False):
    id: str
    accession_id: str
    deed_version: int
    reproduction_restricted: bool
    publication_license_required: bool
    embargo_until: Optional[str]
    required_citation_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    accession_id: str
    collection_id: str
    title: str
    description: Optional[str]
    condition_grade: Optional[str]
    appraised_value_cents: Optional[int]
    format: Optional[str]
    status: str
    conservation_priority_score: Optional[float]
    current_assessment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConservationAssessment(TypedDict, total=False):
    id: str
    item_id: str
    condition_grade_observed: str
    urgency_score: int
    treatment_estimate_hours: int
    open_request_count_snapshot: int
    preliminary_priority_score: float
    confirmed_priority_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class FindingAid(TypedDict, total=False):
    id: str
    collection_id: str
    title: str
    summary: str
    scope_note: Optional[str]
    status: str
    review_origin: Optional[str]
    published_revision_count: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VolunteerProject(TypedDict, total=False):
    id: str
    name: str
    description: Optional[str]
    max_hours_per_volunteer: int
    status: str
    hours_logged_total: float
    volunteer_hours: Dict[str, float]
    active_ticket_count: int
    created_at: str
    updated_at: str
    version: int


class DigitizationTicket(TypedDict, total=False):
    id: str
    project_id: str
    item_id: str
    priority_score: Optional[float]
    status: str
    claimed_by_user_id: Optional[str]
    qc_fail_count: int
    hours_logged: float
    created_at: str
    updated_at: str
    version: int


class Researcher(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    affiliation: Optional[str]
    status: str
    no_show_strikes: int
    total_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class ResearchRequest(TypedDict, total=False):
    id: str
    researcher_id: str
    item_ids: List[str]
    topic: str
    purpose: str
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReadingRoomAppointment(TypedDict, total=False):
    id: str
    researcher_id: str
    research_request_id: str
    room_code: str
    scheduled_date: str
    start_time: str
    end_time: str
    seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReproductionOrder(TypedDict, total=False):
    id: str
    researcher_id: str
    research_request_id: str
    item_ids: List[str]
    format: str
    page_estimate: int
    actual_pages: Optional[int]
    license_class: str
    rush: bool
    quoted_fee_cents: int
    invoiced_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeaccessionProposal(TypedDict, total=False):
    id: str
    item_ids: List[str]
    justification: str
    disposal_method: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    finalize_not_before: Optional[str]
    hammer_prices: Optional[List[dict]]
    proceeds_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class OralHistoryRecording(TypedDict, total=False):
    id: str
    collection_id: str
    narrator_name: str
    interviewer_name: str
    recording_room_id: str
    session_start: str
    session_end: str
    status: str
    release_status: str
    release_signed_at: Optional[str]
    embargo_until: Optional[str]
    created_at: str
    updated_at: str
    version: int
