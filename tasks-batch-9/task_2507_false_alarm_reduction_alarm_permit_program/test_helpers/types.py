"""Domain types for the False Alarm Reduction Permit Program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles (PRD §2.1 — the eight declared role names, case sensitive)
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    PERMIT_CLERK = "PermitClerk"
    ALARM_COMPANY_OPERATOR = "AlarmCompanyOperator"
    ALARM_USER = "AlarmUser"
    POLICE_DISPATCH_SUPERVISOR = "PoliceDispatchSupervisor"
    FALSE_ALARM_REVIEW_OFFICER = "FalseAlarmReviewOfficer"
    HEARING_OFFICER = "HearingOfficer"
    BILLING_CLERK = "BillingClerk"


# --------------------------------------------------------------------------- #
# Status enums
# --------------------------------------------------------------------------- #
class FeeScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class CountingWindowMode(str, Enum):
    ROLLING_365 = "ROLLING_365"
    PERMIT_YEAR = "PERMIT_YEAR"


class AlarmCompanyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class ScoreMode(str, Enum):
    VOLUME_WEIGHTED = "VOLUME_WEIGHTED"
    PERIOD_EQUAL = "PERIOD_EQUAL"


class AlarmSiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class OccupancyClass(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"
    SCHOOL = "SCHOOL"
    FINANCIAL = "FINANCIAL"
    GOVERNMENT = "GOVERNMENT"


class ResponseStatus(str, Enum):
    RESPONSE_ACTIVE = "RESPONSE_ACTIVE"
    RESPONSE_PROBATION = "RESPONSE_PROBATION"
    RESPONSE_SUSPENDED = "RESPONSE_SUSPENDED"


class SiteContactStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class AlarmSystemStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PERMITTED = "PERMITTED"
    UNPERMITTED = "UNPERMITTED"
    REJECTED = "REJECTED"
    DECOMMISSIONED = "DECOMMISSIONED"


class SystemType(str, Enum):
    BURGLARY = "BURGLARY"
    HOLDUP_PANIC = "HOLDUP_PANIC"
    COMBINATION = "COMBINATION"


class VerifiedResponseMode(str, Enum):
    NONE = "NONE"
    AUDIO_VIDEO_REQUIRED = "AUDIO_VIDEO_REQUIRED"
    GUARD_REQUIRED = "GUARD_REQUIRED"


class AlarmPermitStatus(str, Enum):
    PENDING_ISSUANCE = "PENDING_ISSUANCE"
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    RENEWAL_BLOCKED = "RENEWAL_BLOCKED"
    GRACE = "GRACE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class DispatchRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    DISPATCHED = "DISPATCHED"
    REFUSED = "REFUSED"
    CLOSED_VALID = "CLOSED_VALID"
    CANCELLED = "CANCELLED"


class AlarmType(str, Enum):
    BURGLARY = "BURGLARY"
    HOLDUP = "HOLDUP"
    PANIC = "PANIC"
    DURESS = "DURESS"


class VerificationMethod(str, Enum):
    NONE = "NONE"
    SINGLE_CALL = "SINGLE_CALL"
    TWO_CALL_ECV = "TWO_CALL_ECV"
    AUDIO_VIDEO = "AUDIO_VIDEO"
    GUARD_RESPONSE = "GUARD_RESPONSE"


class CallAttemptOutcome(str, Enum):
    NO_ANSWER = "NO_ANSWER"
    VOICEMAIL = "VOICEMAIL"
    ANSWERED_UNVERIFIED = "ANSWERED_UNVERIFIED"
    ANSWERED_CANCELLED = "ANSWERED_CANCELLED"


class RefusalReason(str, Enum):
    ECV_DEFICIENT = "ECV_DEFICIENT"
    RESPONSE_SUSPENDED = "RESPONSE_SUSPENDED"
    VERIFIED_RESPONSE_MISSING = "VERIFIED_RESPONSE_MISSING"
    DUPLICATE_SIGNAL = "DUPLICATE_SIGNAL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    COUNTED = "COUNTED"
    EXEMPT = "EXEMPT"
    APPEALED = "APPEALED"
    EXEMPT_BY_APPEAL = "EXEMPT_BY_APPEAL"
    VOIDED = "VOIDED"


class Determination(str, Enum):
    COUNTED = "COUNTED"
    EXEMPT = "EXEMPT"


class CauseCode(str, Enum):
    OPERATOR_ERROR = "OPERATOR_ERROR"
    EQUIPMENT_MALFUNCTION = "EQUIPMENT_MALFUNCTION"
    UNKNOWN = "UNKNOWN"
    ANIMAL_MOVEMENT = "ANIMAL_MOVEMENT"
    OPEN_DOOR_WINDOW = "OPEN_DOOR_WINDOW"
    SEVERE_WEATHER = "SEVERE_WEATHER"
    UTILITY_POWER_FAILURE = "UTILITY_POWER_FAILURE"
    TELEPHONE_LINE_FAILURE = "TELEPHONE_LINE_FAILURE"
    AUTHORIZED_TEST_WITH_NOTICE = "AUTHORIZED_TEST_WITH_NOTICE"
    CRIMINAL_OFFENSE_CONFIRMED = "CRIMINAL_OFFENSE_CONFIRMED"
    NEW_INSTALLATION_GRACE = "NEW_INSTALLATION_GRACE"


class HearingDocketStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_FOR_SCHEDULING = "CLOSED_FOR_SCHEDULING"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    SCHEDULED = "SCHEDULED"
    HEARD = "HEARD"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REMANDED = "REMANDED"
    WITHDRAWN = "WITHDRAWN"
    DISMISSED_UNTIMELY = "DISMISSED_UNTIMELY"


class AppealDecision(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REMANDED = "REMANDED"


class AppealGrounds(str, Enum):
    WRONG_CAUSE_CODE = "WRONG_CAUSE_CODE"
    EXEMPT_CAUSE = "EXEMPT_CAUSE"
    NOT_MY_SYSTEM = "NOT_MY_SYSTEM"
    VERIFIED_RESPONSE_DEFECT = "VERIFIED_RESPONSE_DEFECT"
    COUNTING_ERROR = "COUNTING_ERROR"
    FEE_CALCULATION_ERROR = "FEE_CALCULATION_ERROR"


class SuspensionOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EFFECTIVE = "EFFECTIVE"
    REINSTATEMENT_PENDING = "REINSTATEMENT_PENDING"
    LIFTED = "LIFTED"
    VACATED = "VACATED"
    EXPIRED = "EXPIRED"


class SuspensionBasis(str, Enum):
    EXCESSIVE_FALSE_ALARMS = "EXCESSIVE_FALSE_ALARMS"
    UNPERMITTED_OPERATION = "UNPERMITTED_OPERATION"
    NONPAYMENT = "NONPAYMENT"


class InvoiceKind(str, Enum):
    FALSE_ALARM_FEE = "FALSE_ALARM_FEE"
    PERMIT_ISSUE_FEE = "PERMIT_ISSUE_FEE"
    PERMIT_RENEWAL_FEE = "PERMIT_RENEWAL_FEE"
    UNPERMITTED_OPERATION_PENALTY = "UNPERMITTED_OPERATION_PENALTY"
    REINSTATEMENT_FEE = "REINSTATEMENT_FEE"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOIDED = "VOIDED"


class CollectionsStage(str, Enum):
    CURRENT = "CURRENT"
    NOTICE = "NOTICE"
    FINAL_NOTICE = "FINAL_NOTICE"
    REFERRED = "REFERRED"
    WRITTEN_OFF = "WRITTEN_OFF"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CHECK = "CHECK"
    CASH = "CASH"
    ACH = "ACH"


class AllocationMode(str, Enum):
    AUTO_WATERFALL = "AUTO_WATERFALL"
    EXPLICIT = "EXPLICIT"


class PaymentRecordStatus(str, Enum):
    APPLIED = "APPLIED"
    VOIDED = "VOIDED"


class PaymentAllocationStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class AdjustmentKind(str, Enum):
    WAIVE = "WAIVE"
    REDUCE = "REDUCE"
    WRITE_OFF = "WRITE_OFF"


class ComplianceReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    VARIANCE_FLAGGED = "VARIANCE_FLAGGED"
    CORRECTED = "CORRECTED"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    FLAG_VARIANCE = "FLAG_VARIANCE"


class CompanyStatusAction(str, Enum):
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    REVOKE = "REVOKE"


# --------------------------------------------------------------------------- #
# Entity TypedDicts
# Every entity below carries id / created_at / updated_at / version except
# PaymentAllocation, which is an immutable ledger line carrying only id and
# created_at (PRD §2.4).
# --------------------------------------------------------------------------- #
class FeeSchedule(TypedDict, total=False):
    id: str
    schedule_code: str
    status: str
    effective_from: str
    counting_window_mode: str
    free_alarm_allowance: int
    fee_tiers: List[Dict[str, Any]]
    occupancy_multipliers: Dict[str, float]
    non_ecv_surcharge_pct: float
    unpermitted_multiplier: float
    suspension_period_aggravation_cents: int
    per_incident_fee_cap_cents: int
    probation_threshold_count: int
    suspension_threshold_count: int
    appeal_filing_days: int
    permit_term_days: int
    renewal_grace_days: int
    new_installation_grace_days: int
    permit_issue_fee_cents: int
    permit_renewal_fee_cents: int
    late_renewal_tiers: List[Dict[str, Any]]
    unpermitted_operation_penalty_cents: int
    reinstatement_base_fee_cents: int
    reinstatement_escalation_pct: float
    admin_fee_pct: float
    admin_fee_min_cents: int
    admin_fee_max_cents: int
    invoice_due_days: int
    late_penalty_pct: float
    delinquency_days: int
    collections_referral_threshold_cents: int
    delinquent_balance_block_cents: int
    exempt_cause_codes: List[str]
    company_probation_score_threshold: float
    company_suspension_score_threshold: float
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlarmCompany(TypedDict, total=False):
    id: str
    legal_name: str
    license_number: str
    contact_email: str
    contact_phone: str
    status: str
    score_mode: str
    reporting_compliance_score: float
    monitored_system_count: int
    dispatch_request_count_lifetime: int
    consecutive_flagged_report_count: int
    probation_started_at: Optional[str]
    status_reason: Optional[str]
    last_status_action_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlarmSite(TypedDict, total=False):
    id: str
    address_key: str
    street_address: str
    city: str
    zip_code: str
    occupancy_class: str
    police_beat: str
    status: str
    governing_fee_schedule_id: Optional[str]
    response_status: str
    chargeable_count_window: int
    chargeable_count_rolling_365: int
    chargeable_count_permit_year: int
    lifetime_assessed_cents: int
    outstanding_balance_cents: int
    credit_balance_cents: int
    unpermitted_system_count: int
    lifted_suspension_count: int
    ecv_callable_contact_count: int
    renewal_block_active: bool
    created_at: str
    updated_at: str
    version: int


class SiteContact(TypedDict, total=False):
    id: str
    alarm_site_id: str
    full_name: str
    phone_number: str
    relationship: str
    contact_priority: int
    is_ecv_callable: bool
    status: str
    removed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlarmSystem(TypedDict, total=False):
    id: str
    alarm_site_id: str
    monitoring_company_id: str
    system_type: str
    zone_count: int
    ecv_enabled: bool
    verified_response_mode: str
    status: str
    installed_at: str
    permitted_at: Optional[str]
    unpermitted_since: Optional[str]
    rejection_reason: Optional[str]
    decommissioned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AlarmPermit(TypedDict, total=False):
    id: str
    alarm_system_id: str
    alarm_site_id: str
    permit_number: str
    status: str
    term_start_at: str
    term_end_at: str
    grace_through_at: str
    new_installation_grace_through: Optional[str]
    renewal_count: int
    issued_by_user_id: str
    last_renewed_at: Optional[str]
    revocation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispatchRequest(TypedDict, total=False):
    id: str
    alarm_system_id: str
    alarm_site_id: str
    monitoring_company_id: str
    alarm_type: str
    verification_method: str
    call_attempts: List[Dict[str, Any]]
    distinct_ecv_contact_count: int
    audio_video_evidence: bool
    guard_on_scene: bool
    occurred_at: str
    status: str
    ecv_sufficient: bool
    system_permitted_at_occurrence: bool
    refusal_reason: Optional[str]
    validated_at: Optional[str]
    validated_by_user_id: Optional[str]
    dispatched_at: Optional[str]
    idempotency_key: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FalseAlarmIncident(TypedDict, total=False):
    id: str
    dispatch_request_id: str
    alarm_site_id: str
    alarm_system_id: str
    occurred_at: str
    cause_code: str
    status: str
    determination: Optional[str]
    exempt_cause_code: Optional[str]
    determined_at: Optional[str]
    determined_by_user_id: Optional[str]
    occurrence_index: Optional[int]
    assessed_fee_cents: int
    fee_basis: Optional[Dict[str, Any]]
    counted_window_mode: Optional[str]
    appeal_count: int
    narrative: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HearingDocket(TypedDict, total=False):
    id: str
    hearing_officer_user_id: str
    session_start: str
    session_end: str
    location: str
    capacity: int
    scheduled_appeal_count: int
    status: str
    held_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    false_alarm_incident_id: str
    alarm_site_id: str
    hearing_docket_id: Optional[str]
    prior_appeal_id: Optional[str]
    filed_by_user_id: str
    grounds: str
    narrative: str
    filed_at: str
    status: str
    decision: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    findings: Optional[str]
    rehearing_depth: int
    created_at: str
    updated_at: str
    version: int


class SuspensionOrder(TypedDict, total=False):
    id: str
    alarm_site_id: str
    triggering_incident_id: str
    basis: str
    status: str
    effective_from: str
    effective_through: str
    suspension_sequence: int
    reinstatement_fee_cents: Optional[int]
    probation_days: Optional[int]
    required_conditions: Optional[Dict[str, Any]]
    served_at: Optional[str]
    reinstatement_requested_at: Optional[str]
    technician_inspection_date: Optional[str]
    ecv_attestation: Optional[bool]
    lifted_at: Optional[str]
    vacated_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PenaltyInvoice(TypedDict, total=False):
    id: str
    alarm_site_id: str
    false_alarm_incident_id: Optional[str]
    alarm_permit_id: Optional[str]
    suspension_order_id: Optional[str]
    invoice_number: str
    kind: str
    line_items: List[Dict[str, Any]]
    subtotal_cents: int
    admin_fee_cents: int
    assessed_cents: int
    paid_cents: int
    adjusted_cents: int
    outstanding_cents: int
    payment_status: str
    collections_stage: str
    issued_on: str
    due_on: str
    late_penalty_cents: int
    days_delinquent: int
    referral_total_cents: Optional[int]
    referral_agency: Optional[str]
    referred_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentRecord(TypedDict, total=False):
    id: str
    alarm_site_id: str
    amount_cents: int
    tendered_on: str
    method: str
    allocation_mode: str
    receipt_number: str
    recorded_by_user_id: str
    status: str
    allocated_cents: int
    credited_cents: int
    voided_at: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentAllocation(TypedDict, total=False):
    """Immutable ledger line — carries only id and created_at (PRD §2.4)."""
    id: str
    payment_record_id: str
    penalty_invoice_id: str
    amount_cents: int
    sequence_index: int
    status: str
    created_at: str


class ComplianceReport(TypedDict, total=False):
    id: str
    monitoring_company_id: str
    period_start: str
    period_end: str
    reported_dispatch_count: int
    reported_cancellation_count: int
    ecv_attempt_count: int
    system_dispatch_count: int
    variance_count: int
    variance_pct: float
    period_accuracy: float
    period_ecv_rate: float
    period_score: float
    status: str
    correction_count: int
    reviewed_at: Optional[str]
    reviewed_by_user_id: Optional[str]
    variance_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int
