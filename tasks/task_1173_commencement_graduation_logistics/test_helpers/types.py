"""Domain types: entity TypedDicts, status enums, role enum (PRD §2 and §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COMMITTEE_CHAIR = "CommitteeChair"
    REGISTRAR_OFFICER = "RegistrarOfficer"
    VENUE_COORDINATOR = "VenueCoordinator"
    GRADUATE = "Graduate"
    VENDOR = "Vendor"


class ReadinessPosture(str, Enum):
    PLANNING = "PLANNING"
    AUDIT_OPEN = "AUDIT_OPEN"
    AUDIT_LOCKED = "AUDIT_LOCKED"
    READY = "READY"
    COMMENCED = "COMMENCED"
    COMPLETED = "COMPLETED"


class WeatherMode(str, Enum):
    FAIR = "FAIR"
    RAIN_PLAN_ACTIVE = "RAIN_PLAN_ACTIVE"


class GraduateStatus(str, Enum):
    PENDING_AUDIT = "PENDING_AUDIT"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    APPEALING = "APPEALING"
    ELIGIBLE_ON_APPEAL = "ELIGIBLE_ON_APPEAL"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class HonorTier(str, Enum):
    NONE = "NONE"
    CUM_LAUDE = "CUM_LAUDE"
    MAGNA_CUM_LAUDE = "MAGNA_CUM_LAUDE"
    SUMMA_CUM_LAUDE = "SUMMA_CUM_LAUDE"


class HonorBasis(str, Enum):
    NONE = "NONE"
    COMBINED = "COMBINED"
    INSTITUTIONAL = "INSTITUTIONAL"


class AuditResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FailReason(str, Enum):
    INSUFFICIENT_CREDITS = "INSUFFICIENT_CREDITS"
    OUTSTANDING_HOLD = "OUTSTANDING_HOLD"
    NO_INSTITUTIONAL_CREDITS = "NO_INSTITUTIONAL_CREDITS"


class AppealStatus(str, Enum):
    NONE = "NONE"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class TicketAllocationStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    PARTIAL = "PARTIAL"
    WAITLISTED = "WAITLISTED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class RegaliaOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    FULFILLED = "FULFILLED"
    EXCHANGE_REQUESTED = "EXCHANGE_REQUESTED"
    CANCELLED = "CANCELLED"


class SeatAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    EVICTED = "EVICTED"


class EvictedReason(str, Enum):
    RAIN_SHRINK = "RAIN_SHRINK"
    MANUAL = "MANUAL"
    WITHDRAWN = "WITHDRAWN"


class ReaderCardStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class PrintBatchStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"
    PRINTED = "PRINTED"


class DiplomaStatus(str, Enum):
    QUEUED = "QUEUED"
    PRINTED = "PRINTED"
    ISSUED = "ISSUED"
    CORRECTION_REQUESTED = "CORRECTION_REQUESTED"
    REPRINT_QUEUED = "REPRINT_QUEUED"
    ARCHIVED = "ARCHIVED"


class RehearsalSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RehearsalAttendanceStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ATTENDED = "ATTENDED"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"
    CANCELLED = "CANCELLED"


class AccommodationRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    FULFILLED = "FULFILLED"


class AccommodationRequestType(str, Enum):
    WHEELCHAIR_SEAT = "WHEELCHAIR_SEAT"
    SIGN_INTERPRETER = "SIGN_INTERPRETER"
    ASSISTIVE_LISTENING = "ASSISTIVE_LISTENING"
    SERVICE_ANIMAL = "SERVICE_ANIMAL"


class VendorContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class VendorType(str, Enum):
    LIVESTREAM = "LIVESTREAM"
    PHOTOGRAPHY = "PHOTOGRAPHY"


# --- Entity TypedDicts (all fourteen resources share id/created_at/updated_at/version, PRD §2.4) ---

class Ceremony(TypedDict, total=False):
    id: str
    name: str
    ceremony_date: str
    venue_id: str
    rain_venue_id: Optional[str]
    readiness_posture: str
    weather_mode: str
    ticket_ratio: float
    guest_ticket_base_cap: int
    honor_bonus_tickets: int
    rehearsal_required: bool
    pronunciation_deadline: str
    ticket_request_deadline: str
    regalia_order_deadline: str
    effective_capacity: int
    ticket_pool_total: int
    ticket_pool_remaining: int
    open_seat_count: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    name: str
    address: str
    total_capacity: int
    accessible_capacity: int
    indoor: bool
    created_at: str
    updated_at: str
    version: int


class Graduate(TypedDict, total=False):
    id: str
    ceremony_id: str
    full_name: str
    email: str
    institutional_gpa_credits: float
    institutional_quality_points: float
    transfer_gpa_credits: float
    transfer_quality_points: float
    credits_completed: float
    credits_required: float
    outstanding_hold_count: int
    status: str
    honor_tier: str
    honor_basis: str
    conduct_strike_count: int
    walk_privilege_revoked: bool
    created_at: str
    updated_at: str
    version: int


class EligibilityAudit(TypedDict, total=False):
    id: str
    graduate_id: str
    result: str
    fail_reasons: List[str]
    provisional_honor_tier: str
    appeal_status: str
    audited_by_user_id: str
    decided_by_user_id: Optional[str]
    notes: str
    created_at: str
    updated_at: str
    version: int


class TicketAllocation(TypedDict, total=False):
    id: str
    graduate_id: str
    ceremony_id: str
    requested_count: int
    entitlement_count: int
    provisional_granted_count: int
    granted_count: int
    waitlist_position: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegaliaOrder(TypedDict, total=False):
    id: str
    graduate_id: str
    items: List[dict]
    subtotal_cents: int
    discount_cents: int
    late_fee_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeatAssignment(TypedDict, total=False):
    id: str
    ceremony_id: str
    graduate_id: str
    section: str
    row_label: str
    seat_number: int
    accessible: bool
    status: str
    evicted_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReaderCard(TypedDict, total=False):
    id: str
    graduate_id: str
    phonetic_spelling: str
    status: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrintBatch(TypedDict, total=False):
    id: str
    ceremony_id: str
    scheduled_print_date: Optional[str]
    status: str
    created_by_user_id: str
    released_by_user_id: Optional[str]
    diploma_count: int
    created_at: str
    updated_at: str
    version: int


class Diploma(TypedDict, total=False):
    id: str
    graduate_id: str
    print_batch_id: str
    printed_name: Optional[str]
    honors_text: str
    pinned_honor_tier: str
    corrected_name: Optional[str]
    correction_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RehearsalSession(TypedDict, total=False):
    id: str
    ceremony_id: str
    venue_id: str
    start_utc: str
    end_utc: str
    capacity: int
    registered_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RehearsalAttendance(TypedDict, total=False):
    id: str
    rehearsal_session_id: str
    graduate_id: str
    status: str
    checked_in_at: Optional[str]
    recorded_by_user_id: Optional[str]
    waived_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccommodationRequest(TypedDict, total=False):
    id: str
    graduate_id: str
    ceremony_id: str
    request_type: str
    notes: str
    status: str
    approved_by_user_id: Optional[str]
    fulfilled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorContract(TypedDict, total=False):
    id: str
    ceremony_id: str
    vendor_type: str
    vendor_user_id: str
    coverage_start_utc: str
    coverage_end_utc: str
    setup_buffer_minutes: int
    fee_cents: int
    deliverable_url: Optional[str]
    cancellation_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
