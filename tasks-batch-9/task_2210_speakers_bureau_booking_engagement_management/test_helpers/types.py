"""Domain types for the Speakers Bureau Engagements API.

Entity TypedDicts, status enumerations and the role enumeration, all named
exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    BUREAU_ADMIN = "BureauAdmin"
    BOOKING_AGENT = "BookingAgent"
    SPEAKER = "Speaker"
    CLIENT = "Client"


# ---------------------------------------------------------------------------
# Taxonomies and code lists (PRD §3.1, §3.2, §3.5, §3.6)
# ---------------------------------------------------------------------------


class TopicCode(str, Enum):
    AI_STRATEGY = "AI_STRATEGY"
    LEADERSHIP = "LEADERSHIP"
    HEALTHCARE_POLICY = "HEALTHCARE_POLICY"
    CYBERSECURITY = "CYBERSECURITY"
    FUTURE_OF_WORK = "FUTURE_OF_WORK"
    SALES_MOTIVATION = "SALES_MOTIVATION"


class IndustryCode(str, Enum):
    HEALTHCARE = "HEALTHCARE"
    FINANCE = "FINANCE"
    TECHNOLOGY = "TECHNOLOGY"
    EDUCATION = "EDUCATION"
    MANUFACTURING = "MANUFACTURING"


class ObjectiveTag(str, Enum):
    INSPIRE = "INSPIRE"
    STRATEGY = "STRATEGY"
    TRAINING = "TRAINING"
    CELEBRATE = "CELEBRATE"


class TravelClass(str, Enum):
    ECONOMY = "ECONOMY"
    PREMIUM = "PREMIUM"
    BUSINESS = "BUSINESS"


class TaxFormStatus(str, Enum):
    MISSING = "MISSING"
    ON_FILE = "ON_FILE"


class DistanceBand(str, Enum):
    LOCAL = "LOCAL"
    REGIONAL = "REGIONAL"
    NATIONAL = "NATIONAL"
    INTERNATIONAL = "INTERNATIONAL"


class CancellationScheduleCode(str, Enum):
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class TravelPolicyCode(str, Enum):
    POLICY_A = "POLICY_A"
    POLICY_B = "POLICY_B"


class RecordingRights(str, Enum):
    NONE = "NONE"
    AUDIO_ONLY = "AUDIO_ONLY"
    FULL_BUY_OUT = "FULL_BUY_OUT"


class TechnicalRiderCode(str, Enum):
    STANDARD_AV = "STANDARD_AV"
    STAGE_PLUS = "STAGE_PLUS"
    BROADCAST = "BROADCAST"


class CancelledBy(str, Enum):
    CLIENT = "CLIENT"
    SPEAKER = "SPEAKER"
    BUREAU = "BUREAU"


class InvoiceKind(str, Enum):
    ENGAGEMENT_FEE = "ENGAGEMENT_FEE"
    CANCELLATION_RETENTION = "CANCELLATION_RETENTION"


class HoldKind(str, Enum):
    ENGAGEMENT = "ENGAGEMENT"
    BLACKOUT = "BLACKOUT"


class PerformanceVariant(str, Enum):
    ROLLING = "ROLLING"
    LIFETIME = "LIFETIME"


# ---------------------------------------------------------------------------
# Status enumerations (PRD §3.1 – §3.9)
# ---------------------------------------------------------------------------


class RosterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class RosterTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class CreditStatus(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    HOLD = "HOLD"


class InquiryStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QUALIFIED = "QUALIFIED"
    BLOCKED = "BLOCKED"
    PROPOSED = "PROPOSED"
    WON = "WON"
    LOST = "LOST"
    DISQUALIFIED = "DISQUALIFIED"


class ProposalStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class ProposalOptionStatus(str, Enum):
    OFFERED = "OFFERED"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class BookingStatus(str, Enum):
    OFFERED = "OFFERED"
    CONFIRMED = "CONFIRMED"
    CONTRACTED = "CONTRACTED"
    DELIVERED = "DELIVERED"
    DECLINED_BY_SPEAKER = "DECLINED_BY_SPEAKER"
    CANCELLED_BY_CLIENT = "CANCELLED_BY_CLIENT"
    CANCELLED_BY_SPEAKER = "CANCELLED_BY_SPEAKER"


class SettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PARTIALLY_COLLECTED = "PARTIALLY_COLLECTED"
    COLLECTED = "COLLECTED"
    REMITTED = "REMITTED"
    WAIVED = "WAIVED"
    WRITTEN_OFF = "WRITTEN_OFF"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    PARTIALLY_SIGNED = "PARTIALLY_SIGNED"
    EXECUTED = "EXECUTED"
    VOID = "VOID"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class ExclusivityGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    WAIVED = "WAIVED"


class TravelExpenseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REIMBURSED = "REIMBURSED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class RemittanceStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class CircumventionClaimStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    SETTLED = "SETTLED"


# ---------------------------------------------------------------------------
# Entity shapes. Every entity below carries id, created_at, updated_at and
# version (PRD §2.4) except Feedback, which is append-only and carries only
# id and created_at.
# ---------------------------------------------------------------------------


class Speaker(TypedDict):
    id: str
    full_name: str
    topics: List[str]
    fee_floor_cents: int
    fee_ceiling_cents: int
    travel_class: str
    travel_buffer_days: int
    tax_form_status: str
    roster_status: str
    roster_tier: str
    default_commission_pct: float
    engagements_delivered_count: int
    lifetime_gross_fees_cents: int
    held_days_count: int
    pending_remittance_cents: int
    rolling_score: Optional[float]
    lifetime_score: Optional[float]
    feedback_count: int
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    org_name: str
    industry_code: str
    primary_contact_email: str
    credit_status: str
    outstanding_balance_cents: int
    circumvention_strikes: int
    created_at: str
    updated_at: str
    version: int


class Inquiry(TypedDict):
    id: str
    client_id: str
    required_topic: str
    event_start_utc: str
    event_end_utc: str
    is_virtual: bool
    audience_size: int
    budget_cents: int
    objective_tags: List[str]
    owning_agent_user_id: Optional[str]
    status: str
    qualification_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict):
    id: str
    inquiry_id: str
    created_by_agent_user_id: str
    round_no: int
    revision_count: int
    options_count: int
    valid_until_utc: str
    status: str
    presented_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProposalOption(TypedDict):
    id: str
    proposal_id: str
    speaker_id: str
    quoted_fee_cents: int
    travel_allowance_cents: int
    rank_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    inquiry_id: str
    speaker_id: str
    selected_option_id: str
    owning_agent_user_id: str
    event_start_utc: str
    event_end_utc: str
    is_virtual: bool
    quoted_fee_cents: int
    travel_allowance_cents: int
    recording_rights: str
    recording_fee_cents: int
    technical_rider_code: str
    booking_status: str
    settlement_status: str
    commission_pct_snapshot: Optional[float]
    provisional_commission_cents: Optional[int]
    final_commission_cents: Optional[int]
    travel_reimbursable_cents: int
    commission_adjustment_count: int
    cancelled_by: Optional[str]
    cancellation_days_before: Optional[int]
    retention_net_cents: Optional[int]
    retention_commission_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    engagement_id: str
    cancellation_schedule_code: str
    travel_policy_code: str
    recording_rights: str
    recording_fee_cents: int
    technical_rider_code: str
    exclusivity_days: int
    status: str
    speaker_signed_at_utc: Optional[str]
    client_signed_at_utc: Optional[str]
    executed_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpeakerHold(TypedDict):
    id: str
    speaker_id: str
    engagement_id: Optional[str]
    kind: str
    hold_start_utc: str
    hold_end_utc: str
    day_span: int
    status: str
    reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExclusivityGrant(TypedDict):
    id: str
    source_engagement_id: str
    speaker_id: str
    beneficiary_client_id: str
    industry_code: str
    effective_from_utc: str
    effective_to_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TravelExpense(TypedDict):
    id: str
    engagement_id: str
    receipts_cents: int
    travel_days: int
    distance_band: str
    memo: Optional[str]
    status: str
    reimbursable_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    engagement_id: str
    client_id: str
    kind: str
    fee_line_cents: int
    recording_line_cents: int
    travel_line_cents: int
    surcharge_cents: int
    amount_due_cents: int
    amount_paid_cents: int
    status: str
    issued_at_utc: str
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict):
    id: str
    engagement_id: str
    speaker_id: str
    gross_fee_cents: int
    commission_cents: int
    travel_passthrough_cents: int
    net_payable_cents: int
    status: str
    paid_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Feedback(TypedDict):
    """Append-only: a feedback record carries only id and created_at.

    The PRD states that both updated_at and version are absent from a
    Feedback resource, so they are deliberately not listed here.
    """

    id: str
    engagement_id: str
    content_score: int
    logistics_score: int
    rebook_intent: Optional[bool]
    comment: Optional[str]
    composite_score: float
    created_at: str


class CircumventionClaim(TypedDict):
    id: str
    client_id: str
    speaker_id: str
    source_engagement_id: str
    direct_event_date_utc: str
    direct_fee_cents: int
    days_after_source: int
    protection_factor: float
    commission_due_cents: int
    status: str
    settled_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
