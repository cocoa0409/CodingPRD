"""Domain types: entity shapes, status enums, and the role enum (PRD §2-§4)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    OPS_CONTROLLER = "OpsController"
    DUTY_MANAGER = "DutyManager"
    REACCOMMODATION_AGENT = "ReaccommodationAgent"
    CREW_SCHEDULER = "CrewScheduler"
    FINANCE_PROCESSOR = "FinanceProcessor"
    OPS_ADMIN = "OpsAdmin"
    PASSENGER = "Passenger"


class EventClassification(str, Enum):
    WEATHER = "WEATHER"
    ATC = "ATC"
    MECHANICAL = "MECHANICAL"
    CREW_SHORTAGE = "CREW_SHORTAGE"


class EventStatus(str, Enum):
    OPEN = "OPEN"
    ASSESSING = "ASSESSING"
    RECOVERY = "RECOVERY"
    CLOSED = "CLOSED"


class FlightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    IN_FLIGHT = "IN_FLIGHT"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class CrewCoverageStatus(str, Enum):
    CREW_OK = "CREW_OK"
    CREW_SHORT = "CREW_SHORT"


class Cabin(str, Enum):
    ECONOMY = "ECONOMY"
    PREMIUM = "PREMIUM"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class LoyaltyTier(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class BookingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISRUPTED = "DISRUPTED"
    REBOOKED = "REBOOKED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class CompensationStatus(str, Enum):
    NONE = "NONE"
    ELIGIBLE_PENDING = "ELIGIBLE_PENDING"
    ELECTED_REFUND = "ELECTED_REFUND"
    ELECTED_CREDIT = "ELECTED_CREDIT"
    SETTLED = "SETTLED"


class CompensationBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SegmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    DISRUPTED = "DISRUPTED"
    CANCELLED = "CANCELLED"
    REBOOKED = "REBOOKED"
    FLOWN = "FLOWN"


class CaseStatus(str, Enum):
    QUEUED = "QUEUED"
    OFFERED = "OFFERED"
    COMMITTED = "COMMITTED"
    EXPIRED = "EXPIRED"
    ESCALATED = "ESCALATED"
    VOIDED = "VOIDED"


class OptionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VoucherType(str, Enum):
    HOTEL = "HOTEL"
    MEAL = "MEAL"
    TRANSPORT = "TRANSPORT"


class VoucherStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class CrewRole(str, Enum):
    CAPTAIN = "CAPTAIN"
    FIRST_OFFICER = "FIRST_OFFICER"
    FLIGHT_ATTENDANT = "FLIGHT_ATTENDANT"


class LegalityStatus(str, Enum):
    LEGAL = "LEGAL"
    FLAGGED_ILLEGAL = "FLAGGED_ILLEGAL"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class Election(str, Enum):
    REFUND = "REFUND"
    CREDIT = "CREDIT"


class ElectionSource(str, Enum):
    USER = "USER"
    SYSTEM_DEFAULT = "SYSTEM_DEFAULT"


class ElectionStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSED = "PROCESSED"


class CostEntryKind(str, Enum):
    ACCRUAL = "ACCRUAL"
    SETTLEMENT = "SETTLEMENT"
    REVERSAL = "REVERSAL"


class CostSourceType(str, Enum):
    VOUCHER = "VOUCHER"
    REFUND = "REFUND"
    CREDIT = "CREDIT"
    COMPENSATION = "COMPENSATION"
    INTERLINE = "INTERLINE"


class CommTemplate(str, Enum):
    DISRUPTION_DETECTED = "DISRUPTION_DETECTED"
    CANCELLATION = "CANCELLATION"
    REBOOK_OFFER = "REBOOK_OFFER"
    REBOOK_CONFIRMED = "REBOOK_CONFIRMED"
    REMINDER = "REMINDER"
    ELECTION_DEFAULT = "ELECTION_DEFAULT"


class CommChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"


class LogStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Entity shapes (PRD §2.4, §3). Primary resources carry
# id / created_at / updated_at / version. The two append-only ledger rows
# (CostEntry, CommunicationLog) carry ONLY id and created_at.
# All TypedDicts are total=False: nullable system fields start empty.
# ---------------------------------------------------------------------------


class DisruptionEvent(TypedDict, total=False):
    id: str
    event_code: str
    hub: str
    classification: str
    is_controllable: bool
    event_status: str
    cost_cap_cents: int
    detected_at: str
    affected_booking_count: int
    affected_passenger_count: int
    accrual_total_cents: int
    settled_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict, total=False):
    id: str
    flight_number: str
    origin: str
    destination: str
    sched_dep_utc: str
    sched_arr_utc: str
    orig_sched_dep_utc: str
    orig_sched_arr_utc: str
    act_dep_utc: Optional[str]
    act_arr_utc: Optional[str]
    distance_km: int
    operating_carrier: str
    flight_status: str
    disruption_event_id: Optional[str]
    cancelled_at: Optional[str]
    crew_coverage_status: str
    created_at: str
    updated_at: str
    version: int


class CabinInventory(TypedDict, total=False):
    id: str
    flight_id: str
    cabin: str
    capacity: int
    seats_sold: int
    interline_seats_committed: int
    seats_available: int
    created_at: str
    updated_at: str
    version: int


class Passenger(TypedDict, total=False):
    id: str
    full_name: str
    loyalty_tier: str
    special_service_codes: List[str]
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    passenger_id: str
    fare_cents: int
    cabin: str
    party_size: int
    booking_status: str
    compensation_status: str
    eligible_at: Optional[str]
    election_deadline: Optional[str]
    refund_amount_cents: int
    credit_amount_cents: int
    compensation_amount_cents: int
    compensation_basis: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BookingSegment(TypedDict, total=False):
    id: str
    booking_id: str
    flight_id: str
    seq_no: int
    cabin: str
    segment_status: str
    reaccommodation_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReaccommodationCase(TypedDict, total=False):
    id: str
    booking_id: str
    disruption_event_id: str
    priority_score: int
    case_status: str
    queued_at: str
    committed_option_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReaccommodationOption(TypedDict, total=False):
    id: str
    case_id: str
    interline_agreement_id: Optional[str]
    is_interline: bool
    legs: List[Dict[str, Any]]
    est_first_dep_utc: str
    est_final_arr_utc: str
    projected_arrival_delay_minutes: int
    interline_fare_cents: int
    rank_score: int
    option_status: str
    created_at: str
    updated_at: str
    version: int


class InterlineAgreement(TypedDict, total=False):
    id: str
    partner_carrier: str
    origin: str
    destination: str
    cabin_map: Dict[str, str]
    settlement_rate_pct: int
    seats_quota_per_flight: int
    agreement_status: str
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict, total=False):
    id: str
    booking_id: str
    disruption_event_id: str
    voucher_type: str
    check_in_date: Optional[str]
    nights: int
    meals_count: int
    face_value_cents: int
    valid_through: str
    voucher_status: str
    redeemed_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    flight_id: str
    crew_member_ref: str
    crew_role: str
    duty_start_utc: str
    duty_end_utc: str
    legality_status: str
    assignment_status: str
    created_at: str
    updated_at: str
    version: int


class RefundElection(TypedDict, total=False):
    id: str
    booking_id: str
    election: str
    election_source: str
    refund_amount_cents: int
    credit_amount_cents: int
    compensation_amount_cents: int
    election_status: str
    created_at: str
    updated_at: str
    version: int


class CostEntry(TypedDict, total=False):
    # Append-only ledger row: id + created_at ONLY (no updated_at, no version).
    id: str
    created_at: str
    disruption_event_id: str
    source_type: str
    source_id: str
    entry_kind: str
    amount_cents: int
    note: str


class CommunicationLog(TypedDict, total=False):
    # Append-only log row: id + created_at ONLY (no updated_at, no version).
    id: str
    created_at: str
    booking_id: str
    disruption_event_id: str
    template: str
    channel: str
    due_at: str
    sent_at: Optional[str]
    log_status: str
