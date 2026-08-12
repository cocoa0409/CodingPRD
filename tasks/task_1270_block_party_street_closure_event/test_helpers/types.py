"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    ORGANIZER = "Organizer"
    NEIGHBOR = "Neighbor"
    TRAFFIC_REVIEWER = "TrafficReviewer"
    SAFETY_REVIEWER = "SafetyReviewer"
    PERMIT_OFFICER = "PermitOfficer"
    DEPOT_OFFICER = "DepotOfficer"
    CITY_ADMIN = "CityAdmin"


class OrganizerStanding(str, Enum):
    GOOD = "GOOD"
    FLAGGED = "FLAGGED"
    SUSPENDED = "SUSPENDED"


class Jurisdiction(str, Enum):
    CITY = "CITY"
    COUNTY = "COUNTY"
    STATE_ROUTE = "STATE_ROUTE"


class SegmentKind(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    MIXED_USE = "MIXED_USE"


class SupportMode(str, Enum):
    SIGNATURE_COUNT = "SIGNATURE_COUNT"
    DISTINCT_HOUSEHOLD = "DISTINCT_HOUSEHOLD"


class PetitionStatus(str, Enum):
    COLLECTING = "COLLECTING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    DEFICIENT = "DEFICIENT"
    LOCKED = "LOCKED"


class SignatureStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUSPENDED = "SUSPENDED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ISSUED = "ISSUED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class TcpStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    TCP_APPROVED = "TCP_APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    LOCKED = "LOCKED"


class SoundPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SOUND_APPROVED = "SOUND_APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    LOCKED = "LOCKED"


class InsuranceKind(str, Enum):
    CERTIFICATE = "CERTIFICATE"
    WAIVER_REQUEST = "WAIVER_REQUEST"


class InsuranceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    WAIVER_GRANTED = "WAIVER_GRANTED"
    WAIVER_DENIED = "WAIVER_DENIED"
    SUPERSEDED = "SUPERSEDED"


class EquipmentKind(str, Enum):
    BARRICADE = "BARRICADE"
    CONE = "CONE"
    SIGN = "SIGN"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    DISPATCHED = "DISPATCHED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    RECALLED = "RECALLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    WAIVED = "WAIVED"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    FUNDED = "FUNDED"
    CLOSED = "CLOSED"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"


class ContributionStatus(str, Enum):
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class DepositStatus(str, Enum):
    HELD = "HELD"
    SETTLED = "SETTLED"
    FORFEITED = "FORFEITED"


class ChargeKind(str, Enum):
    LATE_EQUIPMENT = "LATE_EQUIPMENT"
    SHORTAGE = "SHORTAGE"
    CLEANING = "CLEANING"


class InspectionResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


# --- Entity shapes (PRD §2.4 common fields; §3 per-entity fields) ---

class Organizer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    address: str
    standing: str
    forfeiture_count: int
    created_at: str
    updated_at: str
    version: int


class StreetSegment(TypedDict, total=False):
    id: str
    name: str
    jurisdiction: str
    segment_kind: str
    household_count: int
    business_count: int
    intersects_arterial: bool
    length_m: int
    created_at: str
    updated_at: str
    version: int


class Petition(TypedDict, total=False):
    id: str
    segment_id: str
    organizer_id: str
    required_signatures: int
    support_mode: str
    valid_signature_count: int
    distinct_household_count: int
    status: str
    deficiency_note: Optional[str]
    cure_round: int
    created_at: str
    updated_at: str
    version: int


class PetitionSignature(TypedDict, total=False):
    id: str
    petition_id: str
    household_address: str
    signer_name: str
    signer_email: str
    is_business: bool
    status: str
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict, total=False):
    id: str
    organizer_id: str
    petition_id: str
    segment_id: str
    event_start_at: str
    event_end_at: str
    expected_attendance: int
    amplified_sound: bool
    alcohol_served: bool
    food_vendors: bool
    status: str
    provisional_fee_cents: Optional[int]
    final_fee_cents: Optional[int]
    equipment_total_cents: Optional[int]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrafficControlPlan(TypedDict, total=False):
    id: str
    application_id: str
    barricade_count: int
    cone_count: int
    sign_count: int
    emergency_lane_width_m: float
    emergency_lane_continuous: bool
    placement_notes: str
    status: str
    reviewed_by: Optional[str]
    review_note: Optional[str]
    locked_at_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SoundPlan(TypedDict, total=False):
    id: str
    application_id: str
    speaker_count: int
    max_db_at_property_line: int
    planned_sound_end: str
    status: str
    reviewed_by: Optional[str]
    review_note: Optional[str]
    locked_at_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InsuranceCertificate(TypedDict, total=False):
    id: str
    application_id: str
    kind: str
    insurer_name: Optional[str]
    policy_number: Optional[str]
    coverage_amount_cents: Optional[int]
    expires_on: Optional[str]
    status: str
    reviewed_by: Optional[str]
    review_note: Optional[str]
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EquipmentStock(TypedDict, total=False):
    id: str
    depot_name: str
    equipment_kind: str
    total_units: int
    reserved_units: int
    out_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class EquipmentReservation(TypedDict, total=False):
    id: str
    application_id: str
    stock_id: str
    equipment_kind: str
    units: int
    reservation_status: str
    billing_status: str
    invoice_cents: Optional[int]
    dispatched_by: Optional[str]
    dispatched_at: Optional[str]
    return_due_at: Optional[str]
    returned_at: Optional[str]
    returned_units: Optional[int]
    late_days: Optional[int]
    return_verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostSharePool(TypedDict, total=False):
    id: str
    application_id: str
    target_cents: int
    collected_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict, total=False):
    id: str
    pool_id: str
    household_address: str
    amount_cents: int
    status: str
    refunded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict, total=False):
    id: str
    application_id: str
    required_cents: int
    held_cents: int
    charges_cents: int
    refund_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargeEntry(TypedDict, total=False):
    # Append-only record: carries only id + created_at from the common set
    # (PRD §2.4 exception); no updated_at, no version.
    id: str
    created_at: str
    deposit_id: str
    kind: str
    amount_cents: int
    note: str
    source_reservation_id: Optional[str]


class PostEventReport(TypedDict, total=False):
    id: str
    application_id: str
    cleanup_completed: bool
    cleanup_notes: str
    submitted_at: str
    inspection_result: str
    inspected_by: Optional[str]
    cleaning_charge_cents: int
    created_at: str
    updated_at: str
    version: int
