"""Domain types for the Youth Orchestra Audition & Seating API.

Entity shapes, status enumerations and the role enumeration, exactly as the PRD
declares them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    ARTISTIC_DIRECTOR = "ArtisticDirector"
    REGISTRAR_STAFF = "RegistrarStaff"
    FINANCE_OFFICER = "FinanceOfficer"
    PANELIST = "Panelist"
    GUARDIAN = "Guardian"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------

class SeasonStatus(str, Enum):
    PLANNING = "PLANNING"
    AUDITIONS_OPEN = "AUDITIONS_OPEN"
    PLACEMENT = "PLACEMENT"
    IN_SEASON = "IN_SEASON"
    CLOSED = "CLOSED"


class EnsembleTier(str, Enum):
    SYMPHONY = "SYMPHONY"
    PHILHARMONIC = "PHILHARMONIC"
    CONCERT_ORCHESTRA = "CONCERT_ORCHESTRA"


class RosterState(str, Enum):
    FORMING = "FORMING"
    SEATED = "SEATED"
    CLOSED = "CLOSED"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class Instrument(str, Enum):
    VIOLIN = "VIOLIN"
    VIOLA = "VIOLA"
    CELLO = "CELLO"
    BASS = "BASS"
    FLUTE = "FLUTE"
    OBOE = "OBOE"
    CLARINET = "CLARINET"
    BASSOON = "BASSOON"
    HORN = "HORN"
    TRUMPET = "TRUMPET"
    TROMBONE = "TROMBONE"
    PERCUSSION = "PERCUSSION"


ALL_INSTRUMENTS = [i.value for i in Instrument]


class InstrumentClass(str, Enum):
    STRING = "STRING"
    WIND = "WIND"
    PERCUSSION = "PERCUSSION"


class BalanceState(str, Enum):
    UNDERFILLED = "UNDERFILLED"
    BALANCED = "BALANCED"
    FULL = "FULL"


class RotationPolicy(str, Enum):
    ROTATING = "ROTATING"
    FIXED = "FIXED"


class EnrollmentStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ENROLLED = "ENROLLED"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"
    ALUMNI = "ALUMNI"


class StandingStatus(str, Enum):
    CLEAR = "CLEAR"
    ATTENDANCE_PROBATION = "ATTENDANCE_PROBATION"
    FINANCIAL_HOLD = "FINANCIAL_HOLD"


class IncomeBand(str, Enum):
    BAND_A = "BAND_A"
    BAND_B = "BAND_B"
    BAND_C = "BAND_C"


class PanelRole(str, Enum):
    ADJUDICATOR = "ADJUDICATOR"
    CHAIR = "CHAIR"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"


class AuditionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    SCORED = "SCORED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ADJUDICATED = "ADJUDICATED"


class TierRecommendation(str, Enum):
    SYMPHONY = "SYMPHONY"
    PHILHARMONIC = "PHILHARMONIC"
    CONCERT_ORCHESTRA = "CONCERT_ORCHESTRA"
    NOT_PLACED = "NOT_PLACED"


class OfferKind(str, Enum):
    OFFER = "OFFER"
    WAITLIST = "WAITLIST"


class PlacementStatus(str, Enum):
    OFFERED = "OFFERED"
    WAITLISTED = "WAITLISTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"
    RELEASED = "RELEASED"


class SeatStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ROTATED_OUT = "ROTATED_OUT"
    VACATED = "VACATED"


class AssessmentVariant(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"


class BillingStatus(str, Enum):
    PENDING_ASSESSMENT = "PENDING_ASSESSMENT"
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    PAID_IN_FULL = "PAID_IN_FULL"


class AidStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESCINDED = "RESCINDED"


class AidDenialReason(str, Enum):
    NONE = "NONE"
    INSUFFICIENT_BUDGET = "INSUFFICIENT_BUDGET"
    BELOW_MIN_AWARD = "BELOW_MIN_AWARD"


class EventKind(str, Enum):
    REHEARSAL = "REHEARSAL"
    CONCERT = "CONCERT"
    TOUR_PERFORMANCE = "TOUR_PERFORMANCE"
    FESTIVAL = "FESTIVAL"


PERFORMANCE_KINDS = [
    EventKind.CONCERT.value,
    EventKind.TOUR_PERFORMANCE.value,
    EventKind.FESTIVAL.value,
]


class SoloistSelectionMode(str, Enum):
    AUTO_SELECT = "AUTO_SELECT"
    MANUAL = "MANUAL"
    NONE = "NONE"


class ProgrammingState(str, Enum):
    DRAFT = "DRAFT"
    PROGRAMMED = "PROGRAMMED"
    SOLOIST_VACANT = "SOLOIST_VACANT"


class AttendanceStatus(str, Enum):
    NOT_RECORDED = "NOT_RECORDED"
    PRESENT = "PRESENT"
    TARDY = "TARDY"
    ABSENCE_UNVERIFIED = "ABSENCE_UNVERIFIED"
    EXCUSE_PENDING = "EXCUSE_PENDING"
    EXCUSED_ABSENT = "EXCUSED_ABSENT"
    UNEXCUSED_ABSENT = "UNEXCUSED_ABSENT"


class ExcuseReasonCode(str, Enum):
    NONE = "NONE"
    ILLNESS = "ILLNESS"
    ACADEMIC_CONFLICT = "ACADEMIC_CONFLICT"
    FAMILY = "FAMILY"
    TRANSPORT = "TRANSPORT"


class PerformanceEligibility(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class IneligibilityReason(str, Enum):
    NONE = "NONE"
    ATTENDANCE_INDEX_BELOW_THRESHOLD = "ATTENDANCE_INDEX_BELOW_THRESHOLD"
    DRESS_REHEARSAL_MISSED = "DRESS_REHEARSAL_MISSED"
    MEMBER_ON_PROBATION = "MEMBER_ON_PROBATION"


class TourStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    READY = "READY"


class MemberDimension(str, Enum):
    ENROLLMENT = "ENROLLMENT"
    STANDING = "STANDING"


class ExcuseDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------

class Season(TypedDict):
    id: str
    name: str
    year_label: str
    status: str
    audition_window_start: str
    audition_window_end: str
    tuition_base_cents: int
    tuition_due_at: str
    aid_budget_cents: int
    aid_committed_cents: int
    aid_available_cents: int
    ensemble_count: int
    seated_ensemble_count: int
    created_at: str
    updated_at: str
    version: int


class Ensemble(TypedDict):
    id: str
    season_id: str
    name: str
    tier: str
    min_total_size: int
    max_total_size: int
    rehearsal_weekday: str
    roster_state: str
    seated_count: int
    offered_count: int
    created_at: str
    updated_at: str
    version: int


class SectionQuota(TypedDict):
    id: str
    ensemble_id: str
    instrument: str
    min_count: int
    target_count: int
    max_count: int
    principal_required: bool
    rotation_policy: str
    filled_count: int
    balance_state: str
    rotation_cycle_index: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    legal_name: str
    primary_instrument: str
    instrument_class: str
    grade_level: int
    graduation_year: int
    years_in_org: int
    household_income_band: str
    sibling_enrolled: bool
    alumni_engagement_opt_in: bool
    enrollment_status: str
    standing_status: str
    unexcused_absence_count: int
    tardy_count: int
    effective_unexcused_count: int
    probation_baseline_count: int
    created_at: str
    updated_at: str
    version: int


class Panelist(TypedDict):
    id: str
    display_name: str
    instrument_expertise: str
    panel_role: str
    conflict_member_ids: List[str]
    available_for_panels: bool
    created_at: str
    updated_at: str
    version: int


class AuditionSlot(TypedDict):
    id: str
    season_id: str
    room_code: str
    start_at: str
    end_at: str
    panelist_ids: List[str]
    instrument_focus: str
    required_excerpt_codes: List[str]
    quorum_required: int
    capacity: int
    booked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Audition(TypedDict):
    id: str
    member_id: str
    season_id: str
    slot_id: Optional[str]
    declared_program: str
    excerpt_ids: List[str]
    scale_attested: bool
    blind_code: str
    status: str
    revision_round: int
    submitted_score_count: int
    composite_provisional_score: Optional[float]
    composite_final_score: Optional[float]
    tier_recommendation: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PanelScore(TypedDict):
    """A rubric sheet is immutable: it carries only `id` and `created_at`
    (PRD §2.4). It has no `updated_at` and no `version`."""

    id: str
    audition_id: str
    panelist_id: str
    revision_round: int
    tone_score: int
    rhythm_score: int
    intonation_score: int
    sight_reading_score: int
    weighted_total: float
    blind: bool
    created_at: str


class Placement(TypedDict):
    id: str
    audition_id: str
    member_id: str
    ensemble_id: str
    offer_kind: str
    status: str
    waitlist_rank: Optional[int]
    offer_expires_at: Optional[str]
    accepted_at: Optional[str]
    instrument_loan_requested: bool
    instrument_class_loaned: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SeatAssignment(TypedDict):
    id: str
    placement_id: str
    section_quota_id: str
    member_id: str
    predecessor_assignment_id: Optional[str]
    chair_number: int
    is_principal: bool
    ranking_score: float
    rotation_cycle_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TuitionAccount(TypedDict):
    id: str
    member_id: str
    season_id: str
    ensemble_tier: str
    assessment_variant: str
    assessed_cents: int
    sibling_discount_cents: int
    loyalty_credit_cents: int
    aid_requested_cents: int
    aid_awarded_cents: int
    aid_effective_cents: int
    instrument_loan_fee_cents: int
    payments_total_cents: int
    balance_cents: int
    billing_status: str
    aid_status: str
    aid_need_score: int
    aid_reviewed_by_user_id: Optional[str]
    aid_awarded_by_user_id: Optional[str]
    aid_denial_reason: str
    created_at: str
    updated_at: str
    version: int


class EnsembleEvent(TypedDict):
    id: str
    ensemble_id: str
    kind: str
    start_at: str
    end_at: str
    venue_code: str
    is_dress_rehearsal: bool
    dress_rehearsal_required: bool
    eligibility_window_start: Optional[str]
    soloist_selection_mode: str
    soloist_member_id: Optional[str]
    guest_artist_name: Optional[str]
    guest_artist_fee_cents: int
    programming_state: str
    tour_cost_share_cents: int
    chaperone_required: bool
    participation_count: int
    created_at: str
    updated_at: str
    version: int


class EventParticipation(TypedDict):
    id: str
    event_id: str
    member_id: str
    attendance_status: str
    excuse_reason_code: str
    excuse_documentation_ref: Optional[str]
    excuse_decided_by_user_id: Optional[str]
    performance_eligibility: str
    ineligibility_reason: str
    attendance_index: Optional[float]
    fundraising_credited_cents: int
    fundraising_shortfall_cents: int
    chaperone_name: Optional[str]
    chaperone_background_check_ref: Optional[str]
    chaperone_confirmed: bool
    tour_status: str
    created_at: str
    updated_at: str
    version: int
