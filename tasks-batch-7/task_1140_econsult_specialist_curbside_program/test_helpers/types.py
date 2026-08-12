"""Domain types: entity record shapes, status enums, role enum.

Mirrors the resources described in the PRD. Append-only audit records
(ClarificationMessage, RoutingDecision) carry only id + created_at as
system-managed fields — no updated_at, no version.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    REFERRING_PROVIDER = "ReferringProvider"
    SPECIALIST = "Specialist"
    QUALITY_REVIEWER = "QualityReviewer"
    BILLING_CLERK = "BillingClerk"


class SpecialtyCode(str, Enum):
    CARDIOLOGY = "CARDIOLOGY"
    ENDOCRINOLOGY = "ENDOCRINOLOGY"
    NEUROLOGY = "NEUROLOGY"
    DERMATOLOGY = "DERMATOLOGY"
    RHEUMATOLOGY = "RHEUMATOLOGY"


class PersonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class Standing(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class ConsultStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    CLARIFICATION_REQUESTED = "CLARIFICATION_REQUESTED"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLABLE = "UNBILLABLE"
    PENDING_DOCUMENTATION = "PENDING_DOCUMENTATION"
    CHARGEABLE = "CHARGEABLE"
    CLAIMED = "CLAIMED"
    VOID = "VOID"


class Urgency(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"


class Disposition(str, Enum):
    MANAGE_IN_PRIMARY_CARE = "MANAGE_IN_PRIMARY_CARE"
    MANAGE_WITH_PLAN = "MANAGE_WITH_PLAN"
    CONVERT_TO_VISIT = "CONVERT_TO_VISIT"


class ResponseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"
    REBUKED = "REBUKED"


class AuthorRole(str, Enum):
    REFERRING_PROVIDER = "REFERRING_PROVIDER"
    SPECIALIST = "SPECIALIST"


class ConversionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class Verdict(str, Enum):
    PASS = "PASS"
    REBUKE = "REBUKE"


class EntryType(str, Enum):
    RESPONSE_FEE = "RESPONSE_FEE"
    CLARIFICATION_FEE = "CLARIFICATION_FEE"


class Posture(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class WindowStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOID = "VOID"


class MeasurementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class RoutingOutcome(str, Enum):
    ASSIGNED = "ASSIGNED"
    QUEUED = "QUEUED"


class RecordType(str, Enum):
    PCP_NOTE = "PCP_NOTE"
    SPECIALIST_NOTE = "SPECIALIST_NOTE"


# --- Entity record shapes (common fields: id, created_at, updated_at, version) ---

class SpecialtyTrack(TypedDict, total=False):
    id: str
    specialty_code: str
    response_time_target_hours: int
    urgent_target_hours: int
    base_response_fee_cents: int
    conversion_response_fee_cents: int
    clarification_fee_cents: int
    late_penalty_cents: int
    monthly_billing_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class ReferringProvider(TypedDict, total=False):
    id: str
    full_name: str
    npi: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Specialist(TypedDict, total=False):
    id: str
    full_name: str
    npi: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PanelMembership(TypedDict, total=False):
    id: str
    specialist_id: str
    specialty_track_id: str
    standing: str
    quality_score_bps: int
    reviews_count: int
    reviews_score_sum: int
    responded_count: int
    on_time_count: int
    rebuke_count: int
    expired_count: int
    open_consult_count: int
    provisional_balance_cents: int
    posted_balance_cents: int
    is_accepting: bool
    created_at: str
    updated_at: str
    version: int


class ConsultRequest(TypedDict, total=False):
    id: str
    referring_provider_id: str
    patient_ref: str
    specialty_track_id: str
    question_text: str
    icd10_primary: str
    comorbidity_flags: List[str]
    urgency: str
    status: str
    billing_status: str
    assigned_specialist_id: Optional[str]
    assigned_membership_id: Optional[str]
    sla_due_at: Optional[str]
    sla_breached: bool
    clarification_rounds: int
    created_at: str
    updated_at: str
    version: int


class ConsultResponse(TypedDict, total=False):
    id: str
    consult_id: str
    specialist_id: str
    disposition: str
    recommendation_text: str
    on_time: bool
    response_minutes: int
    pcp_note_documented: bool
    specialist_note_documented: bool
    documentation_complete: bool
    review_required: bool
    last_submitted_at: str
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: only id + created_at system-managed (NO updated_at, NO version).
class ClarificationMessage(TypedDict, total=False):
    id: str
    consult_id: str
    author_role: str
    body: str
    sequence_no: int
    created_at: str


class InPersonConversion(TypedDict, total=False):
    id: str
    consult_id: str
    specialist_id: str
    appointment_start: str
    appointment_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityReview(TypedDict, total=False):
    id: str
    response_id: str
    reviewer_specialist_id: str
    timeliness_score: int
    appropriateness_score: int
    clarity_score: int
    composite_score_bps: int
    verdict: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CompensationEntry(TypedDict, total=False):
    id: str
    membership_id: str
    consult_id: str
    entry_type: str
    amount_cents: int
    posture: str
    period_key: str
    created_at: str
    updated_at: str
    version: int


class SpecialistAvailabilityWindow(TypedDict, total=False):
    id: str
    membership_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingClaim(TypedDict, total=False):
    id: str
    consult_id: str
    claim_code: str
    amount_cents: int
    period_key: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AvoidedVisitMeasurement(TypedDict, total=False):
    id: str
    specialty_track_id: str
    period_key: str
    responded_count: int
    conversions_count: int
    avoided_attributed_count: int
    avoided_conservative_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit row: only id + created_at system-managed.
class RoutingDecision(TypedDict, total=False):
    id: str
    consult_id: str
    outcome: str
    candidate_count: int
    selected_membership_id: Optional[str]
    ranking_basis: str
    created_at: str


class CompensationSummary(TypedDict, total=False):
    provisional_balance_cents: int
    posted_balance_cents: int
    reversed_total_cents: int
    open_consult_count: int


Scenario = Dict[str, Any]
