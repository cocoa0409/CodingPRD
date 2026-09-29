"""Domain types for the Vacation Ownership Sales Tour & Rescission API.

Status enums, enumerated code sets, role enum and entity TypedDicts, all named
exactly as the PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    MARKETING_MANAGER = "MarketingManager"
    GALLERY_MANAGER = "GalleryManager"
    SALES_REPRESENTATIVE = "SalesRepresentative"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CONTRACT_ADMINISTRATOR = "ContractAdministrator"
    PLATFORM_ADMIN = "PlatformAdmin"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------


class TourChannelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SalesGalleryStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class SalesRepresentativeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_TOUR = "ON_TOUR"
    RETRAINING = "RETRAINING"
    SUSPENDED = "SUSPENDED"


class TourBookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULE_PENDING = "RESCHEDULE_PENDING"
    CHECKED_IN = "CHECKED_IN"
    TOURED = "TOURED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class DisclosureStatus(str, Enum):
    PENDING = "PENDING"
    PARTIAL = "PARTIAL"
    COMPLETE = "COMPLETE"


class ReviewStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class RescissionStatus(str, Enum):
    OPEN = "OPEN"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"


class FulfillmentStatus(str, Enum):
    AWAITING_FUNDING = "AWAITING_FUNDING"
    FUNDED = "FUNDED"
    RECORDED = "RECORDED"
    DOCS_DELIVERED = "DOCS_DELIVERED"
    VOIDED = "VOIDED"
    TRADED_IN = "TRADED_IN"


class FinancingApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"


class RescissionRequestStatus(str, Enum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    REJECTED_LATE = "REJECTED_LATE"
    REFUNDED = "REFUNDED"


class RefundDisbursementStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"


class ClosingPackageStatus(str, Enum):
    AWAITING_RECORDING = "AWAITING_RECORDING"
    RECORDED = "RECORDED"
    DELIVERED = "DELIVERED"


class RetrainingAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# --------------------------------------------------------------------------
# Enumerated code sets
# --------------------------------------------------------------------------


class ChannelCode(str, Enum):
    OFF_PROPERTY_CONTACT = "OFF_PROPERTY_CONTACT"
    IN_HOUSE_REFERRAL = "IN_HOUSE_REFERRAL"
    MINI_VAC_PACKAGE = "MINI_VAC_PACKAGE"
    TELEMARKETING = "TELEMARKETING"
    OWNER_UPGRADE = "OWNER_UPGRADE"


class MaritalStatus(str, Enum):
    MARRIED = "MARRIED"
    SINGLE = "SINGLE"


class DisclosureCode(str, Enum):
    RESCISSION_RIGHTS = "RESCISSION_RIGHTS"
    PUBLIC_OFFERING_STATEMENT_DELIVERY = "PUBLIC_OFFERING_STATEMENT_DELIVERY"
    NOT_AN_INVESTMENT = "NOT_AN_INVESTMENT"
    MAINTENANCE_FEE_ESCALATION = "MAINTENANCE_FEE_ESCALATION"


class ClaimCode(str, Enum):
    GUARANTEED_RESALE = "GUARANTEED_RESALE"
    GUARANTEED_APPRECIATION = "GUARANTEED_APPRECIATION"
    RENTAL_INCOME_PROMISE = "RENTAL_INCOME_PROMISE"
    UNLIMITED_AVAILABILITY = "UNLIMITED_AVAILABILITY"


class ClaimSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    EGREGIOUS = "EGREGIOUS"


class ProductType(str, Enum):
    DEEDED_INTEREST = "DEEDED_INTEREST"
    RIGHT_TO_USE = "RIGHT_TO_USE"


class StateCode(str, Enum):
    FL = "FL"
    NV = "NV"
    CA = "CA"
    TX = "TX"
    HI = "HI"


class AnchorMode(str, Enum):
    LATER_OF_EXECUTION_OR_POS = "LATER_OF_EXECUTION_OR_POS"
    EXECUTION = "EXECUTION"
    POS_DELIVERY = "POS_DELIVERY"


class RefundPolicy(str, Enum):
    STATUTORY_FULL = "STATUTORY_FULL"
    CONTRACTUAL_NET_OF_GIFT = "CONTRACTUAL_NET_OF_GIFT"


class DeliveryMethod(str, Enum):
    HAND_DELIVERED = "HAND_DELIVERED"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    EMAIL = "EMAIL"


class TimelinessBasis(str, Enum):
    POSTMARK = "POSTMARK"
    RECEIPT = "RECEIPT"


class RefundMethod(str, Enum):
    ACH = "ACH"
    CHECK = "CHECK"
    CARD_REVERSAL = "CARD_REVERSAL"


class InstrumentType(str, Enum):
    DEED = "DEED"
    RTU_CERTIFICATE = "RTU_CERTIFICATE"


class DocumentDeliveryMethod(str, Enum):
    COURIER = "COURIER"
    ELECTRONIC_PORTAL = "ELECTRONIC_PORTAL"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"


class RetrainingTriggerReason(str, Enum):
    CANCELLATION_RATE_BREACH = "CANCELLATION_RATE_BREACH"
    PROHIBITED_CLAIM_POINTS = "PROHIBITED_CLAIM_POINTS"
    DISCLOSURE_GAP = "DISCLOSURE_GAP"


class RetrainingOutcome(str, Enum):
    COMPLETE = "COMPLETE"
    FAIL = "FAIL"


class ReviewDecision(str, Enum):
    CLEAR = "CLEAR"
    FLAG = "FLAG"


class FinancingDecision(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"


# --------------------------------------------------------------------------
# Entity TypedDicts — ordinary resources carry id/created_at/updated_at/version
# (PRD §2.4)
# --------------------------------------------------------------------------


class TourChannel(TypedDict):
    id: str
    name: str
    channel_code: str
    incentive_gift_value_cents: int
    min_age: int
    min_household_income_cents: int
    min_qualification_score: int
    requires_married_household: bool
    status: str
    booked_count: int
    toured_count: int
    no_show_count: int
    historical_no_show_rate: float
    gift_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class SalesGallery(TypedDict):
    id: str
    name: str
    site_code: str
    concurrent_tour_capacity: int
    presentation_minutes: int
    buffer_minutes: int
    status: str
    booked_slot_count: int
    available_rep_count: int
    created_at: str
    updated_at: str
    version: int


class SalesRepresentative(TypedDict):
    id: str
    gallery_id: str
    full_name: str
    license_number: str
    rotation_position: int
    status: str
    tours_taken_count: int
    executed_agreement_count: int
    rescinded_agreement_count: int
    compliance_strike_count: int
    cancellation_rate: Optional[float]
    last_assigned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Prospect(TypedDict):
    id: str
    household_name: str
    primary_age: int
    household_income_cents: int
    marital_status: str
    is_existing_owner: bool
    created_at: str
    updated_at: str
    version: int


class TourBooking(TypedDict):
    id: str
    channel_id: str
    prospect_id: str
    gallery_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    status: str
    assigned_rep_id: Optional[str]
    qualification_score: int
    qualification_penalty_points: int
    gift_issued: bool
    gift_value_cents: int
    reschedule_count: int
    reschedule_reason: Optional[str]
    cancel_reason: Optional[str]
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesPresentation(TypedDict):
    id: str
    booking_id: str
    rep_id: str
    recorded_ack_reference: str
    window_start_utc: str
    window_end_utc: str
    started_at: str
    required_disclosure_count: int
    disclosure_ack_count: int
    disclosure_status: str
    review_status: str
    prohibited_claim_points: int
    flag_count: int
    compliance_score: int
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PurchaseAgreement(TypedDict):
    id: str
    presentation_id: str
    prospect_id: str
    rep_id: str
    product_type: str
    state_code: str
    purchase_price_cents: int
    down_payment_cents: int
    pos_delivered_at: str
    traded_in_agreement_id: Optional[str]
    executed_at: str
    trade_in_equity_credit_cents: int
    total_due_cents: int
    down_payment_required_cents: int
    base_financed_cents: int
    doc_stamp_cents: int
    closing_cost_fee_cents: int
    financed_amount_cents: int
    escrow_collected_cents: int
    total_collected_cents: int
    retained_cents: int
    anchor_mode: str
    statutory_rescission_days: int
    rescission_anchor_utc: str
    rescission_deadline_utc: str
    business_day_rolled: bool
    refund_policy: str
    rescission_status: str
    fulfillment_status: str
    funded_at: Optional[str]
    funding_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict):
    id: str
    agreement_id: str
    requested_amount_cents: int
    applicant_fico: int
    term_months: int
    status: str
    apr_bps: Optional[int]
    max_ltv_rate: Optional[float]
    ltv_cap_cents: Optional[int]
    approved_amount_cents: Optional[int]
    monthly_payment_cents: Optional[int]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RescissionRequest(TypedDict):
    id: str
    agreement_id: str
    delivery_method: str
    postmark_utc: Optional[str]
    received_at: str
    intake_user_id: str
    timeliness_basis: str
    effective_utc: str
    is_timely: bool
    status: str
    adjudicated_at: Optional[str]
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundDisbursement(TypedDict):
    id: str
    rescission_request_id: str
    method: str
    refund_policy_applied: str
    base_refund_cents: int
    gift_recapture_cents: int
    doc_fee_retained_cents: int
    disbursed_amount_cents: int
    status: str
    issued_by_user_id: str
    settlement_reference: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClosingPackage(TypedDict):
    id: str
    agreement_id: str
    instrument_type: str
    status: str
    recording_jurisdiction: Optional[str]
    recording_reference: Optional[str]
    recorded_at: Optional[str]
    delivery_method: Optional[str]
    documents_delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceRetrainingAssignment(TypedDict):
    id: str
    rep_id: str
    trigger_reason: str
    required_module_count: int
    status: str
    cycle_index: int
    modules_completed: Optional[int]
    assigned_at: str
    started_at: Optional[str]
    closed_at: Optional[str]
    strike_count_at_assignment: int
    cancellation_rate_at_assignment: Optional[float]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only event collections — only id and created_at (PRD §2.4)
# --------------------------------------------------------------------------


class DisclosureAcknowledgment(TypedDict):
    id: str
    presentation_id: str
    disclosure_code: str
    acknowledged_by_prospect: bool
    recording_timestamp_offset_seconds: int
    counts_toward_required: bool
    acknowledged_at: str
    created_at: str


class ProhibitedClaimFinding(TypedDict):
    id: str
    presentation_id: str
    claim_code: str
    severity: str
    penalty_points: int
    reported_by_user_id: str
    detected_at: str
    created_at: str
