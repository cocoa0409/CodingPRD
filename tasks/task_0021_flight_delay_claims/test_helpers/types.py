"""Domain types for the Flight Delay Claims API.

PRD §2.4 — common-fields branching:
  * Insurer, Policy, Ticket, Flight, Claim, ClaimSegment, PayoutBatch,
    ManualReviewCase carry id + created_at + updated_at + version.
  * FlightStatusEvent, ReinsuranceAllocation, ReserveAdjustment, AuditLog,
    OutboxEvent are append-only — they carry ONLY id + created_at.
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    CLAIMS_ADMIN = "ClaimsAdmin"
    POLICY_ADMIN = "PolicyAdmin"
    CLAIMS_REVIEWER = "ClaimsReviewer"
    CLAIMS_APPROVER = "ClaimsApprover"
    BATCH_APPROVER = "BatchApprover"
    BATCH_EXECUTOR = "BatchExecutor"
    PAYOUT_OPERATOR = "PayoutOperator"
    AUDITOR = "Auditor"
    SYSTEM = "system"
    ANY = "Any"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class DelayBasis(str, Enum):
    DEPARTURE = "DEPARTURE"
    ARRIVAL = "ARRIVAL"


class PayoutMode(str, Enum):
    FIXED = "FIXED"
    ACTUAL_LOSS = "ACTUAL_LOSS"


class DelayCause(str, Enum):
    WEATHER = "WEATHER"
    ATC = "ATC"
    SECURITY = "SECURITY"
    AIRLINE = "AIRLINE"
    OTHER = "OTHER"


class TicketStatus(str, Enum):
    ATTACHED = "ATTACHED"
    CHANGED = "CHANGED"
    REFUNDED = "REFUNDED"
    UNMATCHED = "UNMATCHED"


class FlightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    LANDED = "LANDED"
    CANCELLED = "CANCELLED"
    DIVERTED = "DIVERTED"
    RETURNED = "RETURNED"
    ARCHIVED = "ARCHIVED"


class FlightEventSource(str, Enum):
    AIRLINE = "AIRLINE"
    AIRPORT = "AIRPORT"
    AVIATION_AUTHORITY = "AVIATION_AUTHORITY"


class ReportedFlightStatus(str, Enum):
    ON_TIME = "ON_TIME"
    DELAYED = "DELAYED"
    CANCELLED = "CANCELLED"
    DIVERTED = "DIVERTED"
    RETURNED = "RETURNED"


class ClaimReviewStatus(str, Enum):
    PENDING_MATCH = "PENDING_MATCH"
    MATCHED = "MATCHED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ClaimPayoutStatus(str, Enum):
    NOT_PAYABLE = "NOT_PAYABLE"
    PAYABLE = "PAYABLE"
    EXECUTING = "EXECUTING"
    PAID = "PAID"
    REVERSED = "REVERSED"


class RejectionReason(str, Enum):
    EXCLUDED_CAUSE = "EXCLUDED_CAUSE"
    WAITING_PERIOD = "WAITING_PERIOD"
    DELAY_BELOW_THRESHOLD = "DELAY_BELOW_THRESHOLD"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    MATCHING_FAILED = "MATCHING_FAILED"
    MANUAL_DENY = "MANUAL_DENY"
    DUPLICATE = "DUPLICATE"


class TierSelected(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"
    NONE = "NONE"


class SegmentEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    EXCLUDED_CAUSE = "EXCLUDED_CAUSE"
    WAITING_PERIOD = "WAITING_PERIOD"
    DELAY_BELOW_THRESHOLD = "DELAY_BELOW_THRESHOLD"
    TICKET_NOT_BOUND = "TICKET_NOT_BOUND"


class BatchReviewPhase(str, Enum):
    STAGED = "STAGED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BatchExecutionPhase(str, Enum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    SETTLED = "SETTLED"
    EXCEPTIONS = "EXCEPTIONS"


class ManualReviewStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_BIND = "RESOLVED_BIND"
    RESOLVED_REJECT = "RESOLVED_REJECT"


class ManualReviewFailureReason(str, Enum):
    DOC_ID_MISMATCH = "DOC_ID_MISMATCH"
    NAME_MISMATCH = "NAME_MISMATCH"
    NO_POLICY_FOUND = "NO_POLICY_FOUND"
    POLICY_INACTIVE = "POLICY_INACTIVE"
    DUPLICATE_BINDING = "DUPLICATE_BINDING"


class ReserveAdjustmentReason(str, Enum):
    APPROVE_DEBIT = "APPROVE_DEBIT"
    SETTLE_RELEASE = "SETTLE_RELEASE"
    REJECT_RELEASE = "REJECT_RELEASE"
    REVERSE_REBUILD = "REVERSE_REBUILD"


class AuditSubjectType(str, Enum):
    CLAIM = "CLAIM"
    PAYOUT_BATCH = "PAYOUT_BATCH"
    POLICY = "POLICY"
    FLIGHT = "FLIGHT"


class AuditAction(str, Enum):
    STATUS_CHANGE = "STATUS_CHANGE"
    PAYOUT_RECORDED = "PAYOUT_RECORDED"
    RESERVE_ADJUSTED = "RESERVE_ADJUSTED"
    EXTERNAL_EVENT_EMITTED = "EXTERNAL_EVENT_EMITTED"


class OutboxTargetSystem(str, Enum):
    PAYMENT = "PAYMENT"
    BANKING = "BANKING"
    AIRLINE = "AIRLINE"
    POLICY_ADMIN = "POLICY_ADMIN"


class OutboxDispatchStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields:true entities carry id/created_at/updated_at/version.
# ---------------------------------------------------------------------------

class Insurer(TypedDict):
    id: str
    name: str
    currency: str
    now_epoch_ms: int
    total_outstanding_reserve_cents: int
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    insurer_id: str
    policy_holder_name: str
    policy_holder_doc_id: str
    effective_from_epoch_ms: int
    effective_to_epoch_ms: int
    waiting_period_ms: int
    delay_basis: str
    payout_mode: str
    reimbursement_rate_bps: int
    deductible_cents: int
    policy_limit_cents: int
    claim_quota_total_cents: int
    claim_quota_used_cents: int
    reserve_balance_cents: int
    excluded_delay_causes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict, total=False):
    id: str
    insurer_id: str
    policy_id: Optional[str]
    passenger_name: str
    passenger_doc_id: str
    pnr_code: str
    flight_id: str
    scheduled_departure_epoch_ms: int
    scheduled_arrival_epoch_ms: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict, total=False):
    id: str
    insurer_id: str
    carrier_code: str
    flight_number: str
    origin_airport: str
    destination_airport: str
    scheduled_departure_epoch_ms: int
    scheduled_arrival_epoch_ms: int
    actual_departure_epoch_ms: Optional[int]
    actual_arrival_epoch_ms: Optional[int]
    classified_cause: Optional[str]
    status: str
    archived_at_epoch_ms: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only (PRD §2.4).
class FlightStatusEvent(TypedDict, total=False):
    id: str
    flight_id: str
    insurer_id: str
    source: str
    source_event_id: str
    reported_status: str
    reported_actual_departure_epoch_ms: Optional[int]
    reported_actual_arrival_epoch_ms: Optional[int]
    reported_cause: Optional[str]
    report_epoch_ms: int
    ingested_epoch_ms: int
    created_at: str


class ClaimSegment(TypedDict, total=False):
    id: str
    claim_id: str
    insurer_id: str
    ticket_id: str
    flight_id: str
    claimed_actual_loss_cents: int
    delay_minutes_used: Optional[int]
    tier_selected: Optional[str]
    gross_segment_payout_cents: int
    final_segment_payout_cents: int
    eligibility: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_id: str
    insurer_id: str
    ticket_ids: List[str]
    review_status: str
    payout_status: str
    estimated_payout_cents: int
    final_payout_cents: int
    rejection_reason: Optional[str]
    payout_batch_id: Optional[str]
    assigned_reviewer_id: Optional[str]
    assigned_approver_id: Optional[str]
    payout_operator_id: Optional[str]
    segments: List[ClaimSegment]
    created_at: str
    updated_at: str
    version: int


class PayoutBatch(TypedDict, total=False):
    id: str
    insurer_id: str
    flight_id: str
    claim_ids: List[str]
    review_phase: str
    execution_phase: str
    total_planned_payout_cents: int
    total_settled_payout_cents: int
    exception_claim_ids: List[str]
    assigned_batch_approver_id: Optional[str]
    assigned_batch_executor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ManualReviewCase(TypedDict, total=False):
    id: str
    insurer_id: str
    ticket_id: str
    failure_reason: str
    candidate_policy_ids: List[str]
    status: str
    resolved_policy_id: Optional[str]
    assigned_reviewer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only entities — id + created_at only.

class ReinsuranceAllocation(TypedDict, total=False):
    id: str
    claim_id: str
    insurer_id: str
    primary_share_cents: int
    reinsurer_share_cents: int
    pinned_total_cents: int
    created_at: str


class ReserveAdjustment(TypedDict, total=False):
    id: str
    policy_id: str
    insurer_id: str
    claim_id: str
    delta_cents: int
    reason: str
    balance_after_cents: int
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    insurer_id: str
    subject_type: str
    subject_id: str
    action: str
    actor_role: str
    actor_id: str
    details: dict
    created_at: str


class OutboxEvent(TypedDict, total=False):
    id: str
    insurer_id: str
    target_system: str
    event_type: str
    subject_type: str
    subject_id: str
    payload: dict
    dispatch_status: str
    created_at: str
