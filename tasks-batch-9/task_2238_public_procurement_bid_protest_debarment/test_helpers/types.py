"""Domain types: status enums, code enums, entity TypedDicts, role enum.

Four resource types are append-only journal rows and expose only `id` and
`created_at` (PRD §2.4): a mandatory requirement, an addendum, a question
submission and an agency record item. Their TypedDicts therefore omit
`updated_at` and `version` deliberately.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROCUREMENT_OFFICER = "ProcurementOfficer"
    RESPONSIBILITY_REVIEWER = "ResponsibilityReviewer"
    HEARING_OFFICER = "HearingOfficer"
    DEBARMENT_AUTHORITY = "DebarmentAuthority"
    VENDOR = "Vendor"
    SYSTEM_ADMIN = "SystemAdmin"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class VendorEligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    DEBARRED = "DEBARRED"


class SolicitationStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    QUESTION_PERIOD_CLOSED = "QUESTION_PERIOD_CLOSED"
    BIDS_OPENED = "BIDS_OPENED"
    EVALUATION = "EVALUATION"
    AWARD_PENDING = "AWARD_PENDING"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"
    RESOLICITED = "RESOLICITED"


class QuestionStatus(str, Enum):
    PENDING = "PENDING"
    ANSWERED = "ANSWERED"
    REJECTED_LATE = "REJECTED_LATE"


class Materiality(str, Enum):
    MATERIAL = "MATERIAL"
    INFORMALITY = "INFORMALITY"


class ResponsivenessStatus(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    RESPONSIVE = "RESPONSIVE"
    NONRESPONSIVE = "NONRESPONSIVE"
    WITHDRAWN = "WITHDRAWN"


class ResponsibilityStatus(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    RESPONSIBLE = "RESPONSIBLE"
    NONRESPONSIBLE = "NONRESPONSIBLE"


class NonresponsiveReasonCode(str, Enum):
    MATERIAL_REQUIREMENT_UNMET = "MATERIAL_REQUIREMENT_UNMET"
    ADDENDUM_NOT_ACKNOWLEDGED = "ADDENDUM_NOT_ACKNOWLEDGED"
    LATE_SUBMISSION = "LATE_SUBMISSION"
    VENDOR_DEBARRED = "VENDOR_DEBARRED"
    VENDOR_SUSPENDED = "VENDOR_SUSPENDED"
    OFFICER_DETERMINATION = "OFFICER_DETERMINATION"


class WeightProfile(str, Enum):
    STANDARD = "STANDARD"
    HIGH_VALUE = "HIGH_VALUE"


class AwardStatus(str, Enum):
    PENDING_STAY = "PENDING_STAY"
    EXECUTED = "EXECUTED"
    VOID = "VOID"
    RESCINDED = "RESCINDED"


class AwardVoidReasonCode(str, Enum):
    PROTEST_SUSTAINED = "PROTEST_SUSTAINED"
    APPARENT_LOW_BIDDER_CHANGED = "APPARENT_LOW_BIDDER_CHANGED"
    SOLICITATION_CANCELLED = "SOLICITATION_CANCELLED"


class ProtestStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class StayStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    OVERRIDDEN = "OVERRIDDEN"
    LIFTED = "LIFTED"


class ProtestGroundsCode(str, Enum):
    SOLICITATION_IMPROPRIETY = "SOLICITATION_IMPROPRIETY"
    RESPONSIVENESS_DETERMINATION = "RESPONSIVENESS_DETERMINATION"
    RESPONSIBILITY_DETERMINATION = "RESPONSIBILITY_DETERMINATION"
    AWARD_IMPROPRIETY = "AWARD_IMPROPRIETY"
    EVALUATION_ERROR = "EVALUATION_ERROR"


class StandingBasis(str, Enum):
    ACTUAL_BIDDER = "ACTUAL_BIDDER"
    PROSPECTIVE_BIDDER = "PROSPECTIVE_BIDDER"


class RemedyCode(str, Enum):
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
    CANCELLATION = "CANCELLATION"
    RESOLICITATION = "RESOLICITATION"
    NONE = "NONE"


class RecordItemType(str, Enum):
    SOLICITATION_DOCUMENT = "SOLICITATION_DOCUMENT"
    ADDENDUM = "ADDENDUM"
    BID_ABSTRACT = "BID_ABSTRACT"
    RESPONSIVENESS_MEMO = "RESPONSIVENESS_MEMO"
    RESPONSIBILITY_MEMO = "RESPONSIBILITY_MEMO"
    PROTESTER_SUBMISSION = "PROTESTER_SUBMISSION"
    AGENCY_REPORT = "AGENCY_REPORT"


class HearingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONVENED = "CONVENED"
    CONCLUDED = "CONCLUDED"
    CANCELLED = "CANCELLED"


class ProceedingStatus(str, Enum):
    NOTICE_ISSUED = "NOTICE_ISSUED"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    HEARING_HELD = "HEARING_HELD"
    DEBARRED = "DEBARRED"
    DISMISSED = "DISMISSED"


class InterimStatus(str, Enum):
    NONE = "NONE"
    INTERIM_SUSPENDED = "INTERIM_SUSPENDED"
    INTERIM_LIFTED = "INTERIM_LIFTED"


class CauseCode(str, Enum):
    FRAUD = "FRAUD"
    BID_RIGGING = "BID_RIGGING"
    REPEATED_NONPERFORMANCE = "REPEATED_NONPERFORMANCE"
    FALSE_CERTIFICATION = "FALSE_CERTIFICATION"
    SAFETY_VIOLATION = "SAFETY_VIOLATION"
    ADMINISTRATIVE_DEFAULT = "ADMINISTRATIVE_DEFAULT"


class MitigatingFactorCode(str, Enum):
    SELF_DISCLOSURE = "SELF_DISCLOSURE"
    RESTITUTION_PAID = "RESTITUTION_PAID"
    COMPLIANCE_PROGRAM = "COMPLIANCE_PROGRAM"
    COOPERATION = "COOPERATION"


class PetitionStatus(str, Enum):
    FILED = "FILED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class RemediationEvidenceCode(str, Enum):
    RESTITUTION_COMPLETE = "RESTITUTION_COMPLETE"
    MANAGEMENT_REPLACED = "MANAGEMENT_REPLACED"
    COMPLIANCE_AUDIT_PASSED = "COMPLIANCE_AUDIT_PASSED"
    TRAINING_COMPLETED = "TRAINING_COMPLETED"


class ScreeningResult(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED_SUSPENDED = "BLOCKED_SUSPENDED"
    BLOCKED_DEBARRED = "BLOCKED_DEBARRED"


# --------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (PRD §2.4)
# --------------------------------------------------------------------------
class Vendor(TypedDict, total=False):
    id: str
    legal_name: str
    tax_id: str
    contact_email: str
    eligibility_status: str
    protest_fee_balance_cents: int
    debarment_strike_count: int
    active_debarment_id: Optional[str]
    reinstatement_earliest_petition_utc: Optional[str]
    suspension_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Solicitation(TypedDict, total=False):
    id: str
    solicitation_number: str
    title: str
    issuing_agency_code: str
    estimated_value_cents: int
    original_bid_due_utc: str
    original_question_deadline_utc: str
    predecessor_solicitation_id: Optional[str]
    status: str
    issued_by_user_id: Optional[str]
    effective_bid_due_utc: Optional[str]
    question_deadline_utc: Optional[str]
    cumulative_extension_days: int
    addendum_count: int
    bids_opened_at_utc: Optional[str]
    apparent_low_bid_id: Optional[str]
    protest_escrow_cents: int
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    solicitation_id: str
    vendor_id: str
    total_price_cents: int
    acknowledged_addendum_sequences: List[int]
    submitted_at_utc: str
    responsiveness_status: str
    responsibility_status: str
    evaluated_price_cents: Optional[int]
    corrected_total_price_cents: Optional[int]
    informality_loading_cents: int
    nonresponsive_reason_codes: List[str]
    superseded_by_bid_id: Optional[str]
    responsiveness_decided_at_utc: Optional[str]
    responsiveness_decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResponsibilityReview(TypedDict, total=False):
    id: str
    bid_id: str
    reviewer_user_id: str
    financial_capacity_score: int
    past_performance_score: int
    integrity_score: int
    weight_profile: str
    strike_penalty_points: int
    composite_score: float
    determination: str
    notes: Optional[str]
    decided_at_utc: str
    superseded_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Award(TypedDict, total=False):
    id: str
    solicitation_id: str
    winning_bid_id: str
    vendor_id: str
    status: str
    base_obligation_cents: int
    administrative_fee_rate: float
    administrative_fee_cents: int
    protest_risk_reserve_cents: int
    award_total_obligation_cents: int
    executed_at_utc: Optional[str]
    void_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Protest(TypedDict, total=False):
    id: str
    solicitation_id: str
    protester_vendor_id: str
    grounds_code: str
    narrative: str
    challenged_bid_id: Optional[str]
    status: str
    stay_status: str
    standing_basis: str
    filed_at_utc: str
    timeliness_deadline_utc: str
    filing_fee_cents: int
    fee_refunded_cents: int
    decision_outcome: Optional[str]
    remedy_code: Optional[str]
    decided_at_utc: Optional[str]
    record_item_count: int
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProtestHearing(TypedDict, total=False):
    id: str
    protest_id: str
    hearing_officer_user_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    room_code: str
    status: str
    continuance_count: int
    convened_at_utc: Optional[str]
    concluded_at_utc: Optional[str]
    record_items_reviewed_count: int
    created_at: str
    updated_at: str
    version: int


class DebarmentProceeding(TypedDict, total=False):
    id: str
    vendor_id: str
    cause_code: str
    aggravating_factor_codes: List[str]
    mitigating_factor_codes: List[str]
    source_protest_id: Optional[str]
    status: str
    interim_status: str
    notice_issued_at_utc: str
    response_deadline_utc: str
    response_narrative: Optional[str]
    aggravating_total_points: float
    mitigating_credit_points: float
    severity_score: float
    debarment_period_months: int
    debarment_start_utc: Optional[str]
    debarment_end_utc: Optional[str]
    decided_at_utc: Optional[str]
    strikes_applied: int
    created_at: str
    updated_at: str
    version: int


class ReinstatementPetition(TypedDict, total=False):
    id: str
    proceeding_id: str
    remediation_evidence_codes: List[str]
    narrative: str
    status: str
    filed_at_utc: str
    months_served_at_filing: int
    decided_at_utc: Optional[str]
    decision_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubcontractorScreening(TypedDict, total=False):
    id: str
    solicitation_id: str
    prime_vendor_id: str
    sub_vendor_id: str
    tier: int
    result: str
    blocked_reason_code: Optional[str]
    screened_at_utc: str
    rescreened_count: int
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only journal rows — id + created_at only (PRD §2.4)
# --------------------------------------------------------------------------
class MandatoryRequirement(TypedDict, total=False):
    id: str
    solicitation_id: str
    requirement_code: str
    description: str
    materiality: str
    is_waivable: bool
    introduced_by_addendum_sequence: int
    created_at: str


class Addendum(TypedDict, total=False):
    id: str
    solicitation_id: str
    sequence_number: int
    summary: str
    extends_bid_due_by_days: int
    acknowledgment_required: bool
    adds_material_requirement: bool
    issued_at_utc: str
    created_at: str


class QuestionSubmission(TypedDict, total=False):
    id: str
    solicitation_id: str
    vendor_id: str
    question_text: str
    status: str
    submitted_at_utc: str
    answer_summary: Optional[str]
    answered_via_addendum_sequence: Optional[int]
    created_at: str


class AgencyRecordItem(TypedDict, total=False):
    id: str
    protest_id: str
    sequence_number: int
    item_type: str
    document_ref: str
    submitted_at_utc: str
    submitted_by_role: str
    created_at: str


# The four append-only types above must never expose these two fields.
APPEND_ONLY_FORBIDDEN_FIELDS = ("updated_at", "version")
