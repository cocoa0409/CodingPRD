"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PRESIDENT = "President"
    TREASURER = "Treasurer"
    CHOIR_DIRECTOR = "ChoirDirector"
    LIBRARIAN = "Librarian"
    MEMBER = "Member"


class SeasonPosture(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    REHEARSING = "REHEARSING"
    CONCERT_LOCK = "CONCERT_LOCK"
    ARCHIVED = "ARCHIVED"


class SectionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class VoicePart(str, Enum):
    SOPRANO = "SOPRANO"
    ALTO = "ALTO"
    TENOR = "TENOR"
    BASS = "BASS"


class MemberStatus(str, Enum):
    APPLICANT = "APPLICANT"
    AUDITION_SCHEDULED = "AUDITION_SCHEDULED"
    AUDITIONED = "AUDITIONED"
    ENROLLED = "ENROLLED"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"
    DROPPED = "DROPPED"
    RESIGNED = "RESIGNED"


class AuditionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class AuditionDecision(str, Enum):
    NONE = "NONE"
    ACCEPTED = "ACCEPTED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    WAIVED = "WAIVED"
    OVERDUE = "OVERDUE"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CHECK = "CHECK"
    CARD = "CARD"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REFUNDED = "REFUNDED"


class GrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"
    REVOKED = "REVOKED"


class RehearsalStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    LATE = "LATE"
    ABSENT_UNEXCUSED = "ABSENT_UNEXCUSED"
    ABSENT_EXCUSED = "ABSENT_EXCUSED"


class ScoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CheckoutStatus(str, Enum):
    CHECKED_OUT = "CHECKED_OUT"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    LOST = "LOST"


class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class ConcertStatus(str, Enum):
    PLANNING = "PLANNING"
    VENUE_BOOKED = "VENUE_BOOKED"
    PROGRAM_LOCKED = "PROGRAM_LOCKED"
    READY = "READY"
    PERFORMED = "PERFORMED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class PieceStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    VOID = "VOID"


class ServiceLineKind(str, Enum):
    REHEARSAL = "REHEARSAL"
    CONCERT = "CONCERT"
    MASTERCLASS = "MASTERCLASS"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class TourStatus(str, Enum):
    PLANNING = "PLANNING"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class CommitteeStatus(str, Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    DISSOLVED = "DISSOLVED"


class PledgeStatus(str, Enum):
    PLEDGED = "PLEDGED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class RecognitionTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


# All entities carry the common system-managed fields
# (id, created_at, updated_at, version).

class Season(TypedDict, total=False):
    id: str
    name: str
    base_dues_cents: int
    early_bird_pct: float
    early_bird_cutoff: str
    dues_due_date: str
    late_fee_weekly_cents: int
    late_fee_cap_cents: int
    scholarship_pool_cents: int
    audition_slot_minutes: int
    attendance_threshold: float
    posture: str
    ops_week_index: int
    pool_available_cents: int
    pool_reserved_cents: int
    pool_spent_cents: int
    treasury_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Section(TypedDict, total=False):
    id: str
    season_id: str
    voice_part: str
    target_min: int
    target_max: int
    status: str
    active_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    season_id: str
    full_name: str
    email: str
    section_id: Optional[str]
    status: str
    enrolled_at: Optional[str]
    attendance_rate: float
    performance_eligible: bool
    dues_balance_cents: int
    ledger_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Audition(TypedDict, total=False):
    id: str
    member_id: str
    scheduled_at: str
    status: str
    tone_score: Optional[int]
    pitch_score: Optional[int]
    sight_score: Optional[int]
    composite_score: Optional[float]
    decision: str
    created_at: str
    updated_at: str
    version: int


class DuesInvoice(TypedDict, total=False):
    id: str
    member_id: str
    season_id: str
    issued_at: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    scholarship_applied_cents: int
    paid_cents: int
    late_fee_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentAllocation(TypedDict):
    invoice_id: str
    amount_cents: int


class DuesPayment(TypedDict, total=False):
    id: str
    member_id: str
    amount_cents: int
    method: str
    allocations: List[PaymentAllocation]
    status: str
    received_at: str
    created_at: str
    updated_at: str
    version: int


class ScholarshipGrant(TypedDict, total=False):
    id: str
    member_id: str
    season_id: str
    requested_cents: int
    need_note: Optional[str]
    status: str
    approved_cents: Optional[int]
    invoice_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Rehearsal(TypedDict, total=False):
    id: str
    season_id: str
    scheduled_at: str
    location: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict, total=False):
    id: str
    rehearsal_id: str
    member_id: str
    status: str
    excused_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MusicScore(TypedDict, total=False):
    id: str
    title: str
    composer: Optional[str]
    copy_count: int
    copies_available: int
    copies_lost: int
    replacement_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoreCheckout(TypedDict, total=False):
    id: str
    score_id: str
    member_id: str
    checked_out_at: str
    due_date: str
    returned_at: Optional[str]
    status: str
    fine_cents: int
    charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Concert(TypedDict, total=False):
    id: str
    season_id: str
    title: str
    expected_attendance: int
    status: str
    program_duration_seconds: int
    created_at: str
    updated_at: str
    version: int


class VenueBooking(TypedDict, total=False):
    id: str
    concert_id: str
    venue_id: str
    start_at: str
    end_at: str
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramPiece(TypedDict, total=False):
    id: str
    concert_id: str
    title: str
    duration_seconds: int
    sequence_no: int
    featured_member_ids: List[str]
    guest_contract_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceLine(TypedDict):
    kind: str
    units: float
    rate_cents: int


class GuestContract(TypedDict, total=False):
    id: str
    season_id: str
    concert_id: Optional[str]
    musician_name: str
    service_lines: List[ServiceLine]
    travel_stipend_cents: int
    quoted_fee_cents: int
    cancellation_fee_cents: int
    counter_count: int
    status: str
    approved_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TourTrip(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    destination: str
    departure_at: str
    return_at: str
    seat_count: int
    min_seats: int
    transport_lodging_cost_cents: int
    provisional_share_cents: Optional[int]
    final_share_cents: Optional[int]
    confirmed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TourRegistration(TypedDict, total=False):
    id: str
    tour_id: str
    member_id: str
    status: str
    deposit_paid_cents: int
    share_charge_cents: Optional[int]
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class Committee(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    chair_member_id: str
    fundraising_goal_cents: int
    raised_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundraiserPledge(TypedDict, total=False):
    id: str
    committee_id: str
    donor_name: str
    amount_cents: int
    status: str
    recognition_tier: Optional[str]
    recorded_by_user_id: str
    fulfilled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
