"""TypedDict shapes for the entities returned by the API (PRD sections 2.5, 3.x).

These are documentation-grade shapes used to keep the assertion helpers honest;
the tests still assert against plain dictionaries.
"""

from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    """The four universal properties carried by every entity (PRD 2.5)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class Company(CommonFields):
    ticker: str
    legal_name: str
    shares_outstanding: int
    dividend_reserve_cents: int
    dividend_paid_cents: int
    blackout_window_start: Optional[str]
    blackout_window_end: Optional[str]
    disclosure_posture: str
    posture_recomputed_at: Optional[str]
    open_inquiry_count: int


class Contact(CommonFields):
    company_id: str
    contact_type: str
    display_name: str
    email: str
    shares_held: int
    ownership_pct: float
    target_tier: str
    nda_on_file: bool
    coverage_status: str
    activist_flag: bool
    model_access_status: str
    threat_level: str
    dividend_received_cents: int


class Disclosure(CommonFields):
    company_id: str
    disclosure_type: str
    fact_key: str
    metric: str
    period_label: Optional[str]
    guidance_low: Optional[float]
    guidance_high: Optional[float]
    is_guidance: bool
    status: str
    published_at: Optional[str]
    withdrawal_reason: Optional[str]


class InquiryTicket(CommonFields):
    company_id: str
    contact_id: str
    topic_category: str
    subject: str
    requests_nonpublic_detail: bool
    linked_prior_inquiry_id: Optional[str]
    sensitivity_score: int
    routing_queue: str
    sla_due_at: str
    status: str
    answered_at: Optional[str]


class ResponseDraft(CommonFields):
    inquiry_id: str
    body_text: str
    disclosure_class: str
    cited_disclosure_id: Optional[str]
    author_user_id: str
    reviewer_user_id: Optional[str]
    reviewer_note: Optional[str]
    pinned_disclosure_version: Optional[int]
    blocked_reason: Optional[str]
    revision_round: int
    status: str


class EstimateSubmission(CommonFields):
    contact_id: str
    metric: str
    period_label: str
    value: float
    status: str
    submitted_at: str


class RoadshowEvent(CommonFields):
    company_id: str
    event_type: str
    venue_city: str
    window_start: str
    window_end: str
    slot_minutes: int
    capacity_slots: int
    status: str
    allocated_count: int
    waitlisted_count: int
    released_count: int
    declined_count: int
    request_ledger_total: int


class MeetingRequest(CommonFields):
    event_id: str
    contact_id: str
    requested_slot_start: str
    requested_slot_end: str
    provisional_priority_score: float
    final_priority_score: Optional[float]
    status: str
    allocated_at: Optional[str]
    release_reason: Optional[str]
    promoted_from_waitlist: bool


class PayoutLedgerRow(TypedDict):
    contact_id: str
    shares_held: int
    amount_cents: int


class TransferAgentInstruction(CommonFields):
    company_id: str
    instruction_type: str
    notes: Optional[str]
    record_date: Optional[str]
    payable_date: Optional[str]
    declared_rate_cents_per_share: Optional[float]
    funding_mode: str
    status: str
    submitted_by_user_id: str
    acknowledged_by_user_id: Optional[str]
    executed_by_user_id: Optional[str]
    snapshot_holder_count: Optional[int]
    snapshot_shares_total: Optional[int]
    payout_ledger: Optional[List[PayoutLedgerRow]]
    total_payout_cents: Optional[int]
    executed_at: Optional[str]
    decision_reason: Optional[str]


class ConsensusRead(TypedDict):
    """The inline computed payload of GET /companies/{id}/consensus (PRD 3.7)."""

    company_id: str
    metric: str
    period_label: str
    variant: str
    eligible_count: int
    simple_mean: float
    guidance_anchored: bool
    band_low: float
    band_high: float
    outlier_excluded_count: int
    trimmed_applied: bool
    consensus_mean: float
    dispersion_pct: Optional[float]


class AllocationRunSummary(TypedDict):
    """The inline payload returned by the allocation waterfall (PRD 3.8)."""

    event_id: str
    event_status: str
    evaluated_count: int
    allocated_count: int
    waitlisted_count: int
    threshold_deferred_count: int


class ClockState(TypedDict):
    current_utc: str


EntityDict = Dict[str, Any]
