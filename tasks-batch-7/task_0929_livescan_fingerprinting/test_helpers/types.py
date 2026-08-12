"""Domain types: entity TypedDicts, status enums, role enum.

Every persisted resource in this API carries id, created_at, updated_at and
version (PRD 2.4), with no entity carrying a reduced set.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    VENDOR_ADMIN = "VendorAdmin"
    LIVESCAN_TECHNICIAN = "LivescanTechnician"
    SITE_SUPERVISOR = "SiteSupervisor"
    AGENCY_ADJUDICATOR = "AgencyAdjudicator"
    STATE_REPOSITORY = "StateRepository"
    APPLICANT = "Applicant"


class AgencyBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"


class PayerRegime(str, Enum):
    APPLICANT_PAID = "APPLICANT_PAID"
    AGENCY_BILLED = "AGENCY_BILLED"
    FEE_WAIVED = "FEE_WAIVED"


class StatutoryAuthority(str, Enum):
    CRIMINAL_JUSTICE = "CRIMINAL_JUSTICE"
    NONCRIMINAL_STATUTORY = "NONCRIMINAL_STATUTORY"
    NONCRIMINAL_NOFED = "NONCRIMINAL_NOFED"


class DestinationRequirement(str, Enum):
    STATE_ONLY = "STATE_ONLY"
    STATE_AND_FBI = "STATE_AND_FBI"


class DisseminationTier(str, Enum):
    FULL_CHR = "FULL_CHR"
    FITNESS_CODE_ONLY = "FITNESS_CODE_ONLY"


class OriAuthorityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ServiceTypeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SiteKind(str, Enum):
    FIXED = "FIXED"
    MOBILE_EVENT = "MOBILE_EVENT"


class ReconciliationStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    RECONCILED = "RECONCILED"


class CalibrationStatus(str, Enum):
    CALIBRATED = "CALIBRATED"
    EXPIRED = "EXPIRED"
    QUARANTINED = "QUARANTINED"


class DeviceAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    REVOKED_TAINTED = "REVOKED_TAINTED"


class BookingChannel(str, Enum):
    BOOKED = "BOOKED"
    WALK_IN = "WALK_IN"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    IN_CAPTURE = "IN_CAPTURE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class CardStatus(str, Enum):
    OPEN = "OPEN"
    CAPTURING = "CAPTURING"
    READY_FOR_SUBMISSION = "READY_FOR_SUBMISSION"
    SUBMITTED = "SUBMITTED"
    CLOSED = "CLOSED"
    REJECTED_CLOSED = "REJECTED_CLOSED"
    SUPERSEDED = "SUPERSEDED"


class TaintReason(str, Enum):
    CALIBRATION_LAPSE = "CALIBRATION_LAPSE"
    PURGED_RECORD = "PURGED_RECORD"


class PositionStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    CEILING_REACHED = "CEILING_REACHED"
    EXCEPTION_CODED = "EXCEPTION_CODED"


class ExceptionCode(str, Enum):
    AMPUTATED = "AMPUTATED"
    BANDAGED = "BANDAGED"
    UNCLASSIFIABLE = "UNCLASSIFIABLE"


class Destination(str, Enum):
    STATE = "STATE"
    FBI = "FBI"


class ResultCode(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED_TECHNICAL = "REJECTED_TECHNICAL"
    REJECTED_ADMIN = "REJECTED_ADMIN"


class StateStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED_TECHNICAL = "REJECTED_TECHNICAL"
    REJECTED_ADMIN = "REJECTED_ADMIN"


class FbiStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED_TECHNICAL = "REJECTED_TECHNICAL"
    REJECTED_ADMIN = "REJECTED_ADMIN"


class CompositeDisposition(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    CLEARED = "CLEARED"
    HIT = "HIT"
    REJECTED = "REJECTED"
    MIXED = "MIXED"


class RetentionStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    GRANTED = "GRANTED"
    PURGE_REQUESTED = "PURGE_REQUESTED"
    PURGE_DENIED = "PURGE_DENIED"
    PURGED = "PURGED"


class FitnessCode(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    ELIGIBLE_WITH_NOTICE = "ELIGIBLE_WITH_NOTICE"
    INELIGIBLE = "INELIGIBLE"


class RoutingStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ROUTED = "ROUTED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class DeterminationOutcome(str, Enum):
    FIT = "FIT"
    NOT_FIT = "NOT_FIT"
    FIT_WITH_CONDITIONS = "FIT_WITH_CONDITIONS"


class DeterminationStatus(str, Enum):
    ISSUED = "ISSUED"
    CHALLENGED = "CHALLENGED"
    REAFFIRMED = "REAFFIRMED"
    AMENDED = "AMENDED"
    VACATED = "VACATED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    TERMINATED = "TERMINATED"


class NotificationStatus(str, Enum):
    ROUTED = "ROUTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ORPHANED = "ORPHANED"
    VOIDED = "VOIDED"


class RapbackEventType(str, Enum):
    ARREST = "ARREST"
    DISPOSITION = "DISPOSITION"
    WARRANT = "WARRANT"


class AssessmentKind(str, Enum):
    SUBMISSION = "SUBMISSION"
    REPRINT = "REPRINT"
    NO_SHOW = "NO_SHOW"
    ONSITE_SHORTFALL = "ONSITE_SHORTFALL"


class AssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CREDITED = "CREDITED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAST_DUE = "PAST_DUE"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class Agency(TypedDict):
    id: str
    name: str
    account_code: str
    billing_status: str
    payer_regime_default: str
    invoice_terms_days: int
    outstanding_balance_cents: int
    max_aging_days: int
    mtd_billed_cents: int
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ori(TypedDict):
    id: str
    agency_id: str
    ori_code: str
    statutory_authority: str
    destination_requirement: str
    dissemination_tier: str
    retention_permitted: bool
    rapback_authority: bool
    authority_status: str
    fee_waiver_eligible: bool
    tcn_consumed_count: int
    tcn_released_count: int
    created_at: str
    updated_at: str
    version: int


class ServiceType(TypedDict):
    id: str
    ori_id: str
    code: str
    applicant_type: str
    slot_duration_minutes: int
    required_document_codes: List[str]
    accepted_id_document_types: List[str]
    state_fee_cents: int
    federal_fee_cents: int
    retention_offered: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CaptureSite(TypedDict):
    id: str
    site_kind: str
    name: str
    concurrent_capacity: int
    walkin_usable_capacity: int
    host_agency_id: Optional[str]
    event_window_start: Optional[str]
    event_window_end: Optional[str]
    min_billable_prints: Optional[int]
    billable_print_count: int
    reconciliation_status: str
    shortfall_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    serial_number: str
    home_site_id: str
    last_calibrated_at: str
    calibration_expires_at: str
    calibration_status: str
    capture_count: int
    tainted_card_count: int
    created_at: str
    updated_at: str
    version: int


class DeviceAssignment(TypedDict):
    id: str
    device_id: str
    site_id: str
    window_start: str
    window_end: str
    status: str
    calibration_expires_at_snapshot: str
    billable_print_count: int
    tainted_print_count: int
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    sex: str
    place_of_birth: Optional[str]
    id_document_type: str
    id_document_expires_on: str
    demographics_complete: bool
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    applicant_id: str
    site_id: str
    service_type_id: str
    booking_channel: str
    scheduled_start: str
    scheduled_end: str
    status: str
    reschedule_count: int
    presented_document_type: Optional[str]
    presented_documents: Optional[List[str]]
    checked_in_at: Optional[str]
    no_show_fee_assessed: bool
    created_at: str
    updated_at: str
    version: int


class FingerprintCard(TypedDict):
    id: str
    appointment_id: str
    device_id: str
    site_id: str
    captured_by_user_id: str
    status: str
    positions_passed_count: int
    positions_exception_count: int
    mean_quality_score: float
    worst_position_score: Optional[int]
    submittable: bool
    exception_override_by_user_id: Optional[str]
    superseded_by_card_id: Optional[str]
    reprint_of_submission_id: Optional[str]
    free_reprint_granted: bool
    taint_reason: Optional[str]
    first_capture_at: Optional[str]
    last_capture_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PositionCapture(TypedDict):
    id: str
    card_id: str
    position_code: str
    attempt_count: int
    best_score: Optional[int]
    status: str
    exception_code: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    card_id: str
    ori_id: str
    original_submission_id: Optional[str]
    reprint_sequence: int
    transmitted_at: str
    destinations: List[str]
    state_status: str
    fbi_status: str
    composite_disposition: str
    retention_requested: bool
    retention_status: str
    tcn_root: str
    tcn_suffix: int
    tcn_full: str
    state_resulted_at: Optional[str]
    fbi_resulted_at: Optional[str]
    reprint_count: int
    free_reprint_count: int
    purge_requested_at: Optional[str]
    purge_requested_by_user_id: Optional[str]
    purge_decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChrResponse(TypedDict):
    id: str
    submission_id: str
    destination: str
    record_count: Optional[int]
    disqualifying_offense_count: Optional[int]
    record_detail: Optional[str]
    fitness_code: Optional[str]
    routing_status: str
    routed_at: Optional[str]
    routed_recipient_roles: Optional[List[str]]
    created_at: str
    updated_at: str
    version: int


class FitnessDetermination(TypedDict):
    id: str
    submission_id: str
    ori_id: str
    basis_response_id: Optional[str]
    outcome: Optional[str]
    issued_by_user_id: str
    resolved_by_user_id: Optional[str]
    status: str
    challenge_count: int
    challenge_filed_at: Optional[str]
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class RapbackSubscription(TypedDict):
    id: str
    submission_id: str
    ori_id: str
    term_start: str
    term_end: str
    status: str
    renewal_count: int
    notifications_received_count: int
    notifications_routed_count: int
    notifications_voided_count: int
    created_at: str
    updated_at: str
    version: int


class RapbackNotification(TypedDict):
    id: str
    subscription_id: Optional[str]
    ori_code: str
    subject_submission_tcn: str
    event_type: str
    event_date: str
    status: str
    acknowledged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict):
    id: str
    agency_id: str
    submission_id: Optional[str]
    appointment_id: Optional[str]
    invoice_id: Optional[str]
    assessment_kind: str
    payer_regime: str
    state_fee_cents: int
    federal_fee_cents: int
    processing_surcharge_cents: int
    vendor_convenience_fee_cents: int
    vendor_tax_cents: int
    trip_surcharge_cents: int
    reprint_fee_cents: int
    waived_cents: int
    discount_cents: int
    total_cents: int
    paid_cents: int
    credited_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    agency_id: str
    period_key: str
    issued_on: Optional[str]
    due_on: Optional[str]
    subtotal_cents: int
    late_fee_cents: int
    total_cents: int
    paid_cents: int
    aging_days: int
    status: str
    created_at: str
    updated_at: str
    version: int
