"""Domain types for the Passport & Visa Expediting API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them. Thirteen entities carry the full common field set
(``id``, ``created_at``, ``updated_at``, ``version``); four are append-only
records carrying only ``id`` and ``created_at`` alongside their own attributes.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CASE_MANAGER = "CaseManager"
    COURIER_OPS = "CourierOps"
    AGENCY_LIAISON = "AgencyLiaison"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRAVELER = "Traveler"


# --------------------------------------------------------------------------
# Enumerations that appear on request bodies and on stored rows
# --------------------------------------------------------------------------
class ServiceLevel(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"
    RUSH = "RUSH"


class VisaType(str, Enum):
    TOURIST = "TOURIST"
    BUSINESS = "BUSINESS"
    STUDENT = "STUDENT"
    PASSPORT_RENEWAL = "PASSPORT_RENEWAL"
    PASSPORT_FIRST_TIME = "PASSPORT_FIRST_TIME"


class GovernmentFeeBasis(str, Enum):
    PER_APPLICANT = "PER_APPLICANT"
    PER_ORDER = "PER_ORDER"


class DocType(str, Enum):
    PASSPORT_BOOK = "PASSPORT_BOOK"
    PROOF_OF_TRAVEL = "PROOF_OF_TRAVEL"
    INVITATION_LETTER = "INVITATION_LETTER"
    BANK_STATEMENT = "BANK_STATEMENT"
    VACCINATION_CERT = "VACCINATION_CERT"
    EMPLOYMENT_LETTER = "EMPLOYMENT_LETTER"
    PARENTAL_CONSENT = "PARENTAL_CONSENT"


class ValidityRule(str, Enum):
    NONE = "NONE"
    EXPIRES_AFTER_ISSUE_DAYS = "EXPIRES_AFTER_ISSUE_DAYS"
    VALID_BEYOND_RETURN_MONTHS = "VALID_BEYOND_RETURN_MONTHS"


class BackgroundCode(str, Enum):
    WHITE = "WHITE"
    OFF_WHITE = "OFF_WHITE"
    COLORED = "COLORED"


class HolderType(str, Enum):
    APPLICANT = "APPLICANT"
    SERVICE = "SERVICE"
    COURIER = "COURIER"
    AGENCY = "AGENCY"


class ShipmentMethod(str, Enum):
    GROUND = "GROUND"
    OVERNIGHT = "OVERNIGHT"
    COURIER_SAME_DAY = "COURIER_SAME_DAY"


class LedgerStream(str, Enum):
    GOVERNMENT = "GOVERNMENT"
    SERVICE = "SERVICE"


class LedgerKind(str, Enum):
    COLLECTION = "COLLECTION"
    TENDER = "TENDER"
    EARN = "EARN"
    REFUND = "REFUND"
    TRANSFER_OUT = "TRANSFER_OUT"
    TRANSFER_IN = "TRANSFER_IN"


class LedgerReason(str, Enum):
    CUSTOMER_PAYMENT = "CUSTOMER_PAYMENT"
    AGENCY_TENDER = "AGENCY_TENDER"
    SERVICE_RECOGNITION = "SERVICE_RECOGNITION"
    CANCELLATION_REFUND = "CANCELLATION_REFUND"
    REJECTION_REFUND = "REJECTION_REFUND"
    SPLIT_PARTITION = "SPLIT_PARTITION"


class CustodyReason(str, Enum):
    ORDER_CREATED = "ORDER_CREATED"
    LEG_DISPATCHED = "LEG_DISPATCHED"
    LEG_DELIVERED = "LEG_DELIVERED"
    LEG_FAILED_RETURN = "LEG_FAILED_RETURN"
    DECISION_RETURNED = "DECISION_RETURNED"
    SHIPMENT_DELIVERED = "SHIPMENT_DELIVERED"
    SHIPMENT_PICKED_UP = "SHIPMENT_PICKED_UP"


# --------------------------------------------------------------------------
# State machine status enums
# --------------------------------------------------------------------------
class AgencyFormStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class WorkflowStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    INTAKE = "INTAKE"
    READY_FOR_SUBMISSION = "READY_FOR_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    AT_AGENCY = "AT_AGENCY"
    RFE_PENDING = "RFE_PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DELIVERING = "DELIVERING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ABANDONED = "ABANDONED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_COLLECTED = "PARTIALLY_COLLECTED"
    COLLECTED = "COLLECTED"
    REFUND_PENDING = "REFUND_PENDING"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class FeasibilityStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    ACKNOWLEDGED_INFEASIBLE = "ACKNOWLEDGED_INFEASIBLE"


class ReadinessStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    WITHDRAWN = "WITHDRAWN"


class ReviewStatus(str, Enum):
    MISSING = "MISSING"
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ComplianceStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class PrepStatus(str, Enum):
    PREPARED = "PREPARED"
    SIGNED = "SIGNED"
    STALE = "STALE"
    VOID = "VOID"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class LegStatus(str, Enum):
    CREATED = "CREATED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RfeStatus(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    CLEARED = "CLEARED"
    INSUFFICIENT = "INSUFFICIENT"
    EXPIRED = "EXPIRED"


class DeliveryStatus(str, Enum):
    CREATED = "CREATED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    HELD_FOR_PICKUP = "HELD_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"


class SegmentKind(str, Enum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"


class SegmentCause(str, Enum):
    SUBMISSION = "SUBMISSION"
    RFE_ISSUED = "RFE_ISSUED"
    RFE_RESPONDED = "RFE_RESPONDED"
    DECISION = "DECISION"


# --------------------------------------------------------------------------
# Entity shapes — thirteen versioned entities
# --------------------------------------------------------------------------
class ServiceCatalogItem(TypedDict):
    id: str
    nationality_code: str
    destination_country: str
    visa_type: str
    government_fee_cents: int
    government_fee_basis: str
    base_service_fee_cents: int
    agency_turnaround_override_days: Optional[int]
    form_code: str
    requires_appointment: bool
    created_at: str
    updated_at: str
    version: int


class AgencyForm(TypedDict):
    id: str
    form_code: str
    revision: int
    required_field_count: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Consulate(TypedDict):
    id: str
    name: str
    destination_country: str
    jurisdiction_region_codes: List[str]
    closure_dates: List[str]
    created_at: str
    updated_at: str
    version: int


class AppointmentSlot(TypedDict):
    id: str
    consulate_id: str
    starts_at: str
    capacity: int
    booked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    catalog_item_id: str
    consulate_id: Optional[str]
    parent_order_id: Optional[str]
    service_level: str
    travel_date: str
    return_date: str
    delivery_region_code: str
    workflow_status: str
    payment_status: str
    custody_holder: str
    feasibility_status: str
    furthest_stage_reached: str
    applicant_count: int
    government_fee_quoted_cents: int
    service_fee_quoted_cents: int
    total_quoted_cents: int
    discount_pct_applied: float
    handling_fee_waived: bool
    collected_government_cents: int
    collected_service_cents: int
    collected_cents: int
    government_tendered_cents: int
    service_earned_cents: int
    refunded_cents: int
    refund_scheduled_cents: int
    outstanding_cents: int
    quoted_by_user_id: Optional[str]
    submitted_by_user_id: Optional[str]
    acknowledged_by_user_id: Optional[str]
    quoted_at: Optional[str]
    submitted_at: Optional[str]
    tendered_at: Optional[str]
    decided_at: Optional[str]
    effective_submission_date: Optional[str]
    projected_completion_date: Optional[str]
    rfe_round_count: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    order_id: str
    full_name: str
    date_of_birth: str
    nationality_code: str
    residence_region_code: str
    readiness_status: str
    age_years: int
    required_doc_count: int
    accepted_doc_count: int
    created_at: str
    updated_at: str
    version: int


class ApplicantDocument(TypedDict):
    id: str
    applicant_id: str
    doc_type: str
    is_required: bool
    validity_rule: str
    validity_param: Optional[int]
    review_status: str
    issue_date: Optional[str]
    expiry_date: Optional[str]
    resubmission_count: int
    rejection_reason: Optional[str]
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PhotoAsset(TypedDict):
    id: str
    applicant_id: str
    taken_on: str
    head_height_ratio: float
    background_code: str
    resolution_px: int
    compliance_status: str
    retake_count: int
    failure_reasons: List[str]
    created_at: str
    updated_at: str
    version: int


class PreparedForm(TypedDict):
    id: str
    applicant_id: str
    agency_form_id: str
    form_code: str
    revision_used: int
    filled_field_count: int
    prep_status: str
    signed_at: Optional[str]
    signed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    applicant_id: str
    slot_id: str
    booking_status: str
    reschedule_count: int
    no_show_count: int
    booked_at: str
    created_at: str
    updated_at: str
    version: int


class CourierLeg(TypedDict):
    id: str
    order_id: str
    leg_index: int
    from_holder: str
    to_holder: str
    scheduled_date: str
    leg_status: str
    attempt_count: int
    created_at: str
    updated_at: str
    version: int


class RFE(TypedDict):
    id: str
    order_id: str
    round_index: int
    requested_doc_type: str
    issued_at: str
    deadline_at: str
    rfe_status: str
    responded_at: Optional[str]
    response_count: int
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    method: str
    address_region_code: str
    signature_required: bool
    delivery_status: str
    attempt_count: int
    escalation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Entity shapes — four append-only records: id + created_at only, no
# updated_at and no version.
# --------------------------------------------------------------------------
class DocumentRequirement(TypedDict):
    id: str
    catalog_item_id: str
    doc_type: str
    is_required: bool
    validity_rule: str
    validity_param: Optional[int]
    applies_max_age_years: Optional[int]
    created_at: str


class CustodyEvent(TypedDict):
    id: str
    order_id: str
    holder_type: str
    leg_index: Optional[int]
    acquired_at: str
    released_at: Optional[str]
    reason: str
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    order_id: str
    stream: str
    kind: str
    amount_cents: int
    reason: str
    recorded_at: str
    created_at: str


class SlaSegment(TypedDict):
    id: str
    order_id: str
    segment_kind: str
    cause: str
    started_at: str
    ended_at: Optional[str]
    business_minutes: Optional[int]
    created_at: str
