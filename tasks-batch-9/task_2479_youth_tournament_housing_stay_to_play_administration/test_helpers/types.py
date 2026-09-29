"""Domain types for the Youth Tournament Housing API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.

Two entities are deliberately narrower than the rest. PRD §2.4: "Two resources
are append-only records of a moment rather than mutable rows, and they carry
only ``id`` and ``created_at``." Those two are ``RoomingListEntry`` and
``ActualizationReport``, so their TypedDicts carry neither ``updated_at`` nor
``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    HOUSING_MANAGER = "HousingManager"
    EXCEPTION_REVIEWER = "ExceptionReviewer"
    RIGHTS_HOLDER = "RightsHolder"
    TEAM_MANAGER = "TeamManager"
    HOTEL_REPRESENTATIVE = "HotelRepresentative"


# ---------------------------------------------------------------------------
# Tournament (PRD §3.1)
# ---------------------------------------------------------------------------


class TournamentPosture(str, Enum):
    OPEN = "OPEN"
    BOOKING_CLOSED = "BOOKING_CLOSED"
    RECONCILING = "RECONCILING"
    SETTLED = "SETTLED"


class HousingPressure(str, Enum):
    NORMAL = "NORMAL"
    CONSTRAINED = "CONSTRAINED"


# ---------------------------------------------------------------------------
# HotelContract and RoomBlock (PRD §3.2)
# ---------------------------------------------------------------------------


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    NEGOTIATING = "NEGOTIATING"
    EXECUTED = "EXECUTED"
    CLOSED = "CLOSED"


class BlockPosture(str, Enum):
    AVAILABLE = "AVAILABLE"
    TIGHT = "TIGHT"
    SOLD_OUT = "SOLD_OUT"


class RebateModel(str, Enum):
    PER_ROOM_NIGHT_FLAT = "PER_ROOM_NIGHT_FLAT"
    PERCENT_OF_ROOM_REVENUE = "PERCENT_OF_ROOM_REVENUE"
    TIERED_PER_ROOM_NIGHT = "TIERED_PER_ROOM_NIGHT"


class NegotiationAction(str, Enum):
    SUBMIT = "SUBMIT"
    REVISE = "REVISE"
    COUNTERSIGN = "COUNTERSIGN"


class RoomType(str, Enum):
    DOUBLE_QUEEN = "DOUBLE_QUEEN"
    KING = "KING"
    SUITE = "SUITE"


class BlockStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    RELEASED = "RELEASED"
    SETTLED = "SETTLED"


# ---------------------------------------------------------------------------
# TeamRegistration (PRD §3.3)
# ---------------------------------------------------------------------------


class RegistrationStatus(str, Enum):
    PENDING_HOUSING = "PENDING_HOUSING"
    HOUSING_COMPLIANT = "HOUSING_COMPLIANT"
    EXCEPTION_GRANTED = "EXCEPTION_GRANTED"
    NON_COMPLIANT = "NON_COMPLIANT"


# ---------------------------------------------------------------------------
# Booking — two independent axes (PRD §3.7)
# ---------------------------------------------------------------------------


class BookingStatus(str, Enum):
    DRAFT = "DRAFT"
    ROOMING_LIST_SUBMITTED = "ROOMING_LIST_SUBMITTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class RebateStatus(str, Enum):
    NOT_DUE = "NOT_DUE"
    ACCRUED = "ACCRUED"
    INVOICED = "INVOICED"
    COLLECTED = "COLLECTED"
    SHORT_PAID = "SHORT_PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


# ---------------------------------------------------------------------------
# ExceptionRequest (PRD §3.6)
# ---------------------------------------------------------------------------


class ExceptionReasonCode(str, Enum):
    LOCAL_TEAM = "LOCAL_TEAM"
    FAMILY_MEDICAL = "FAMILY_MEDICAL"
    ADA_ACCOMMODATION = "ADA_ACCOMMODATION"
    FINANCIAL_HARDSHIP = "FINANCIAL_HARDSHIP"
    RELATIVE_HOSTING = "RELATIVE_HOSTING"


class ExceptionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReviewAction(str, Enum):
    START_REVIEW = "START_REVIEW"
    REQUEST_INFO = "REQUEST_INFO"
    APPROVE = "APPROVE"
    DENY = "DENY"


class TeamAction(str, Enum):
    RESUBMIT = "RESUBMIT"
    APPEAL = "APPEAL"


# ---------------------------------------------------------------------------
# Complaint (PRD §3.9)
# ---------------------------------------------------------------------------


class ComplaintCategory(str, Enum):
    PRICING_FAIRNESS = "PRICING_FAIRNESS"
    POLICY_FAIRNESS = "POLICY_FAIRNESS"
    BLOCK_AVAILABILITY = "BLOCK_AVAILABILITY"
    REBATE_TRANSPARENCY = "REBATE_TRANSPARENCY"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    INVESTIGATING = "INVESTIGATING"
    ESCALATED = "ESCALATED"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class ComplaintRoute(str, Enum):
    INVESTIGATE = "INVESTIGATE"
    ESCALATE = "ESCALATE"


class ComplaintOutcome(str, Enum):
    UPHOLD = "UPHOLD"
    DISMISS = "DISMISS"


class RemedyType(str, Enum):
    NONE = "NONE"
    FEE_WAIVER = "FEE_WAIVER"
    RATE_ADJUSTMENT = "RATE_ADJUSTMENT"
    POLICY_EXEMPTION = "POLICY_EXEMPTION"


# ---------------------------------------------------------------------------
# RebateInvoice and RevenueDistribution (PRD §3.8 – §3.9)
# ---------------------------------------------------------------------------


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    WRITTEN_OFF = "WRITTEN_OFF"


class InvoiceLifecycleAction(str, Enum):
    ISSUE = "ISSUE"
    DISPUTE = "DISPUTE"
    WRITE_OFF = "WRITE_OFF"


class DistributionStatus(str, Enum):
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"


class DistributionAction(str, Enum):
    APPROVE = "APPROVE"
    PAY = "PAY"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class VersionedRecord(TypedDict):
    """PRD §2.4 full common-field set."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyRecord(TypedDict):
    """PRD §2.4: append-only records carry only ``id`` and ``created_at``."""

    id: str
    created_at: str


class Tournament(VersionedRecord):
    name: str
    rights_holder_org: str
    destination_org: str
    start_date: str
    end_date: str
    booking_deadline: str
    stay_to_play_required: bool
    share_pct_organizer: float
    share_pct_rights_holder: float
    share_pct_destination: float
    night_count: int
    posture: str
    housing_pressure: str
    executed_contract_count: int
    sold_out_contract_count: int


class Hotel(VersionedRecord):
    name: str
    city: str
    total_rooms: int
    distance_miles_from_venue: float


class HotelContract(VersionedRecord):
    tournament_id: str
    hotel_id: str
    negotiated_nightly_rate_cents: int
    rebate_model: str
    rebate_flat_cents_per_room_night: int
    rebate_percent: float
    attrition_threshold_pct: float
    attrition_penalty_rate_cents_per_room_night: int
    cutoff_date: str
    status: str
    block_posture: str
    revision_round: int
    contracted_room_nights: int
    countersigned_by_hotel_id: Optional[str]


class RoomBlock(VersionedRecord):
    contract_id: str
    room_type: str
    block_size_rooms: int
    arrival_date: str
    departure_date: str
    release_deadline: str
    status: str
    rooms_committed: int
    rooms_available: int
    rooms_released_unsold: int
    utilization_pct: float
    actualized_room_nights: int
    threshold_room_nights: int


class Team(VersionedRecord):
    name: str
    home_city: str
    home_state: str
    org_contact_email: str
    distance_miles_from_venue: float


class TeamRegistration(VersionedRecord):
    tournament_id: str
    team_id: str
    roster_player_count: int
    roster_staff_count: int
    local_team_flag: bool
    required_rooms_registered: int
    required_room_nights: int
    minimum_rooms_for_compliance: int
    exempt_rooms_granted: int
    effective_required_rooms: int
    committed_rooms: int
    status: str
    compliance_evaluated_at: Optional[str]


class Booking(VersionedRecord):
    registration_id: str
    room_block_id: str
    rooms_requested: int
    check_in_date: str
    check_out_date: str
    supersedes_booking_id: Optional[str]
    booking_status: str
    rebate_status: str
    nights: int
    projected_room_nights: int
    actualized_room_nights: int
    rebate_accrued_cents: int
    penalty_cents: int
    penalty_room_nights: int
    penalty_credit_cents: int
    cancellation_reason: Optional[str]
    cancelled_at: Optional[str]


class RoomingListEntry(AppendOnlyRecord):
    """No ``updated_at`` and no ``version`` — PRD §2.4."""

    booking_id: str
    room_index: int
    occupant_count: int
    minor_occupant_count: int
    chaperone_name: Optional[str]


class ActualizationReport(AppendOnlyRecord):
    """No ``updated_at`` and no ``version`` — PRD §2.4."""

    booking_id: str
    reported_room_nights: int
    report_note: Optional[str]
    sequence_no: int


class ExceptionRequest(VersionedRecord):
    registration_id: str
    reason_code: str
    requested_rooms_exempt: int
    justification: str
    status: str
    review_round: int
    appeal_count: int
    approved_rooms_exempt: int
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]


class Complaint(VersionedRecord):
    tournament_id: str
    registration_id: Optional[str]
    cited_exception_request_id: Optional[str]
    affected_booking_id: Optional[str]
    category: str
    narrative: str
    status: str
    route: Optional[str]
    remedy_type: str
    remedy_amount_cents: int
    remedy_credit_cents: int
    triaged_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]


class RebateInvoice(VersionedRecord):
    contract_id: str
    period_label: str
    invoiced_room_nights: int
    invoiced_rebate_cents: int
    attrition_shortfall_room_nights_per_block: int
    attrition_shortfall_room_nights_aggregate: int
    attrition_penalty_cents: int
    total_due_cents: int
    collected_cents: int
    written_off_cents: int
    outstanding_cents: int
    distributed_cents: int
    status: str
    dispute_note: Optional[str]


class RevenueDistribution(VersionedRecord):
    tournament_id: str
    source_invoice_id: str
    gross_collected_cents: int
    admin_fee_pct: float
    admin_fee_cents: int
    distributable_cents: int
    organizer_cents: int
    rights_holder_cents: int
    destination_cents: int
    rounding_remainder_cents: int
    status: str
    approved_by_user_id: Optional[str]


RoomingList = List[RoomingListEntry]
