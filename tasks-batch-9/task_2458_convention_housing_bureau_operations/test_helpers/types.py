"""Domain types for the Convention Housing Bureau Operations API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    BUREAU_COORDINATOR = "BureauCoordinator"
    BUREAU_CONTROLLER = "BureauController"
    HOTEL_MANAGER = "HotelManager"
    EVENT_ORGANIZER = "EventOrganizer"
    ATTENDEE = "Attendee"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class HousingPosture(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class HotelStanding(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class HotelBlockStatus(str, Enum):
    DRAFT = "DRAFT"
    TERMS_SUBMITTED = "TERMS_SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CONTRACTED = "CONTRACTED"
    OPEN = "OPEN"
    CUTOFF_PASSED = "CUTOFF_PASSED"
    CLOSED = "CLOSED"


class SubBlockSegment(str, Enum):
    GENERAL = "GENERAL"
    VIP = "VIP"
    STAFF = "STAFF"
    EXHIBITOR = "EXHIBITOR"


class SubBlockApprovalStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RELEASED = "RELEASED"


class InventoryStatus(str, Enum):
    FULL = "FULL"
    OPEN = "OPEN"


class AttendeeType(str, Enum):
    GENERAL = "GENERAL"
    VIP = "VIP"
    STAFF = "STAFF"
    EXHIBITOR = "EXHIBITOR"


class ReservationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class TransmissionStatus(str, Enum):
    NOT_TRANSMITTED = "NOT_TRANSMITTED"
    TRANSMITTED = "TRANSMITTED"
    CHANGE_PENDING = "CHANGE_PENDING"


class TransmissionType(str, Enum):
    INITIAL = "INITIAL"
    CHANGE = "CHANGE"
    FINAL = "FINAL"


class PickupSource(str, Enum):
    HOTEL = "HOTEL"


class ReductionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXERCISED = "EXERCISED"


class VendorStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED_POACHER = "CONFIRMED_POACHER"
    CLEARED = "CLEARED"


class DetectionSource(str, Enum):
    ATTENDEE_REPORT = "ATTENDEE_REPORT"
    HOTEL_REPORT = "HOTEL_REPORT"
    WEB_MONITORING = "WEB_MONITORING"


class ContactChannel(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    SMS = "SMS"
    WEB = "WEB"


class IncidentStatus(str, Enum):
    RECORDED = "RECORDED"
    WARNING_ISSUED = "WARNING_ISSUED"
    DISMISSED = "DISMISSED"


class WarningSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    URGENT = "URGENT"


class CommissionBasis(str, Enum):
    BUREAU_CONFIRMED = "BUREAU_CONFIRMED"
    HOTEL_REPORTED = "HOTEL_REPORTED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (PRD §2.4)
# ---------------------------------------------------------------------------


class Event(TypedDict):
    id: str
    name: str
    code: str
    event_start_date: str
    event_end_date: str
    cutoff_date: str
    attrition_deadline_date: str
    standard_commission_pct: float
    standard_rebate_per_room_night_cents: int
    night_count: int
    housing_posture: str
    total_contracted_room_nights: int
    total_confirmed_room_nights: int
    commission_collected_cents: int
    created_at: str
    updated_at: str
    version: int


class Hotel(TypedDict):
    id: str
    name: str
    distance_to_venue_miles: float
    room_tax_pct: float
    total_rooms: int
    standing: str
    created_at: str
    updated_at: str
    version: int


class HotelBlock(TypedDict):
    id: str
    event_id: str
    hotel_id: str
    status: str
    revision_round: int
    negotiated_nightly_rate_cents: int
    commission_pct: float
    rebate_per_room_night_cents: int
    cutoff_date: str
    reduction_rights_pct: float
    contracted_rooms_per_night: int
    original_contracted_rooms_per_night: Optional[int]
    unassigned_rooms_per_night: int
    released_rooms_per_night: int
    contracted_room_nights: int
    attrition_liability_cents: int
    confirmation_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubBlock(TypedDict):
    id: str
    hotel_block_id: str
    parent_sub_block_id: Optional[str]
    segment: str
    allotted_rooms: int
    eligibility_code: Optional[str]
    approval_status: str
    carve_seq: int
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    committed_rooms: int
    available_rooms: int
    released_rooms: int
    inventory_status: str
    created_at: str
    updated_at: str
    version: int


class Attendee(TypedDict):
    id: str
    event_id: str
    email: str
    full_name: str
    registration_id: str
    attendee_type: str
    eligibility_codes: List[str]
    warning_count: int
    housing_risk_flag: bool
    no_show_strikes: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    sub_block_id: str
    attendee_id: str
    check_in_date: str
    check_out_date: str
    occupants: int
    intake_seq: int
    room_nights: int
    quoted_nightly_rate_cents: int
    room_tax_pct_snapshot: float
    total_room_charge_cents: int
    reservation_status: str
    transmission_status: str
    eligibility_review_required: bool
    no_show_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class AttritionReduction(TypedDict):
    id: str
    hotel_block_id: str
    requested_reduction_rooms: int
    effective_date: str
    justification_code: str
    status: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    rooms_absorbed_from_unassigned: int
    rooms_absorbed_from_sub_blocks: int
    penalty_avoided_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RogueHousingVendor(TypedDict):
    id: str
    event_id: str
    name: str
    contact_domain: str
    detection_source: str
    status: str
    risk_score: int
    verified_incident_count: int
    warning_issued_count: int
    created_at: str
    updated_at: str
    version: int


class PoachingIncident(TypedDict):
    id: str
    rogue_vendor_id: str
    attendee_id: str
    contact_channel: str
    occurred_at: str
    verified: bool
    solicited_payment: bool
    status: str
    warning_issued_at: Optional[str]
    warning_severity: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommissionInvoice(TypedDict):
    id: str
    hotel_block_id: str
    basis: str
    bureau_confirmed_commission_cents: int
    hotel_reported_commission_cents: Optional[int]
    commission_due_cents: int
    rebate_due_cents: int
    billable_room_nights: int
    variance_cents: Optional[int]
    paid_cents: int
    written_off_cents: int
    outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only records of fact: only id + created_at (PRD §2.4)
# ---------------------------------------------------------------------------


class RoomingListTransmission(TypedDict):
    id: str
    hotel_block_id: str
    transmission_type: str
    batch_seq: int
    reservation_count: int
    transmitted_at: str
    included_reservation_ids: List[str]
    created_at: str


class PickupReport(TypedDict):
    id: str
    hotel_block_id: str
    as_of_date: str
    reported_rooms_picked_up: int
    reported_room_nights: int
    reported_gross_revenue_cents: int
    source: str
    created_at: str
