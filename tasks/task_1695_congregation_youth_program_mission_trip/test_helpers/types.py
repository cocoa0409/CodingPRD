"""Domain types: entity TypedDicts, status enums, role enum.

All fourteen resources carry the standard system-managed fields from the PRD
("id", "created_at", "updated_at", "version"), so every TypedDict below
includes them.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TripStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    DEBRIEFED = "DEBRIEFED"
    CANCELLED = "CANCELLED"


class DestinationType(str, Enum):
    IN_STATE = "IN_STATE"
    OUT_OF_STATE = "OUT_OF_STATE"
    INTERNATIONAL = "INTERNATIONAL"


class InsuranceTier(str, Enum):
    NONE = "NONE"
    DOMESTIC = "DOMESTIC"
    INTERNATIONAL = "INTERNATIONAL"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"
    DISMISSED = "DISMISSED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class PaymentStatus(str, Enum):
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    DELINQUENT = "DELINQUENT"
    REFUNDED = "REFUNDED"


class ConsentFormType(str, Enum):
    PARENTAL_CONSENT = "PARENTAL_CONSENT"
    MEDICAL_RELEASE = "MEDICAL_RELEASE"
    MEDIA_RELEASE = "MEDIA_RELEASE"
    CONDUCT_AGREEMENT = "CONDUCT_AGREEMENT"


class ConsentFormStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class FundraisingAccountStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DonationChannel(str, Enum):
    CASH = "CASH"
    CHECK = "CHECK"
    CARD_ONLINE = "CARD_ONLINE"


class DonationStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CHECK = "CHECK"
    CARD_ONLINE = "CARD_ONLINE"


class PaymentRecordStatus(str, Enum):
    POSTED = "POSTED"
    REFUNDED = "REFUNDED"


class ScholarshipApplicationStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    DISBURSED = "DISBURSED"
    RESCINDED = "RESCINDED"
    RETURNED = "RETURNED"
    WITHDRAWN = "WITHDRAWN"


class IncomeBracket(str, Enum):
    BAND_A = "BAND_A"
    BAND_B = "BAND_B"
    BAND_C = "BAND_C"
    BAND_D = "BAND_D"
    UNDISCLOSED = "UNDISCLOSED"


class BackgroundCheckStatus(str, Enum):
    INITIATED = "INITIATED"
    SCREENING = "SCREENING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    EXPIRED = "EXPIRED"


class AssignmentRole(str, Enum):
    LEAD = "LEAD"
    SUPPORT = "SUPPORT"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    REMOVED = "REMOVED"


class RemovalReason(str, Enum):
    MANUAL = "MANUAL"
    AUTO_SCREENING = "AUTO_SCREENING"


class SegmentType(str, Enum):
    TRAVEL = "TRAVEL"
    LODGING = "LODGING"
    SERVICE = "SERVICE"
    MEAL = "MEAL"
    FREE = "FREE"


class LodgingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class DismissSanction(str, Enum):
    SENT_HOME = "SENT_HOME"
    BARRED_FROM_FUTURE = "BARRED_FROM_FUTURE"


class UserRole(str, Enum):
    PROGRAM_DIRECTOR = "ProgramDirector"
    TRIP_LEADER = "TripLeader"
    TREASURER = "Treasurer"
    SCHOLARSHIP_REVIEWER = "ScholarshipReviewer"
    GUARDIAN = "Guardian"
    CHAPERONE = "Chaperone"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Program(TypedDict):
    id: str
    name: str
    ministry_year: str
    status: str
    scholarship_fund_total_cents: int
    scholarship_reserved_cents: int
    scholarship_disbursed_cents: int
    scholarship_available_cents: int
    max_award_pct_bp: int
    per_registration_cap_cents: int
    default_chaperone_ratio: int
    code_of_conduct_text: str
    discipline_policy_text: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    program_id: str
    name: str
    destination_name: str
    destination_type: str
    start_date: str
    end_date: str
    capacity_youth: int
    base_cost_cents: int
    deposit_cents: int
    chaperone_ratio: int
    required_insurance_tier: str
    registration_open_at: str
    registration_close_at: str
    deposit_due_at: str
    final_payment_due_at: str
    emergency_protocol_text: str
    status: str
    seats_taken: int
    confirmed_youth_count: int
    cleared_chaperone_count: int
    required_cleared_chaperones: int
    ratio_compliant: bool
    lodging_cost_total_cents: int
    debrief_summary: str
    debrief_actual_participant_count: int
    debrief_incident_count: int
    debrief_lessons_learned: str
    debriefed_at: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    program_id: str
    family_key: str
    guardian_user_id: str
    first_name: str
    last_name: str
    birth_date: str
    grade: int
    annual_income_bracket: str
    household_size: int
    barred_until: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    trip_id: str
    participant_id: str
    guardian_user_id: str
    registration_status: str
    payment_status: str
    insurance_tier: str
    provisional_cost_share_cents: int
    final_cost_share_cents: int
    late_fees_total_cents: int
    covered_cents: int
    amount_due_cents: int
    fundraising_credit_applied_cents: int
    scholarship_awarded_cents: int
    conduct_acknowledged: bool
    deposit_late_fee_assessed: bool
    final_late_fee_assessed: bool
    dismiss_sanction: str
    dismiss_reason: str
    created_at: str
    updated_at: str
    version: int


class ConsentForm(TypedDict):
    id: str
    registration_id: str
    form_type: str
    status: str
    signed_by_name: str
    signed_at: str
    medical_notes: str
    reviewed_by_user_id: str
    rejection_reason: str
    created_at: str
    updated_at: str
    version: int


class FundraisingAccount(TypedDict):
    id: str
    registration_id: str
    status: str
    goal_cents: int
    raised_gross_cents: int
    fee_total_cents: int
    raised_net_cents: int
    credit_applied_cents: int
    available_credit_cents: int
    goal_met: bool
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict):
    id: str
    fundraising_account_id: str
    donor_name: str
    amount_cents: int
    channel: str
    fee_cents: int
    status: str
    received_at: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    registration_id: str
    amount_cents: int
    method: str
    status: str
    posted_at: str
    created_at: str
    updated_at: str
    version: int


class ScholarshipApplication(TypedDict):
    id: str
    registration_id: str
    requested_cents: int
    need_score: int
    award_cents: int
    status: str
    approved_by_user_id: str
    disbursed_by_user_id: str
    decision_reason: str
    created_at: str
    updated_at: str
    version: int


class Chaperone(TypedDict):
    id: str
    program_id: str
    first_name: str
    last_name: str
    email: str
    phone: str
    current_screening_expires_at: str
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict):
    id: str
    chaperone_id: str
    status: str
    vendor_reference: str
    cleared_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class ChaperoneAssignment(TypedDict):
    id: str
    trip_id: str
    chaperone_id: str
    role: str
    status: str
    removal_reason: str
    created_at: str
    updated_at: str
    version: int


class ItineraryItem(TypedDict):
    id: str
    trip_id: str
    segment_type: str
    title: str
    start_at: str
    end_at: str
    location: str
    vehicle_code: str
    created_at: str
    updated_at: str
    version: int


class LodgingReservation(TypedDict):
    id: str
    trip_id: str
    site_name: str
    room_code: str
    check_in_date: str
    check_out_date: str
    room_capacity: int
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
