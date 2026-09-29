"""Typed request payload shapes for the adoption-review API.

Each ``TypedDict`` mirrors one request body described by the PRD. Every field is
declared ``total=False`` so a test may omit an optional field and exercise the
server's defaulting or its required-field validation.
"""

from typing import Any, Dict, List, TypedDict


JsonDict = Dict[str, Any]


class StateProfilePayload(TypedDict, total=False):
    state_code: str
    adoption_model: str
    sampling_copies_required: int
    comment_response_days: int
    required_topics: List[str]
    prohibited_content_tags: List[str]
    multi_year_max_years: int
    price_cap_cents: int
    min_verified_coverage_pct: float
    accessibility_standard: str
    rostering_standard: str
    data_privacy_addendum_required: bool


class StateStandardPayload(TypedDict, total=False):
    subject: str
    standard_code: str
    grade_low: int
    grade_high: int
    weight: int
    is_focus: bool


class AdoptionCyclePayload(TypedDict, total=False):
    state_id: str
    subject: str
    cycle_year: int
    submission_open_at: str
    submission_deadline_at: str
    committee_review_at: str
    public_comment_start_at: str
    public_comment_end_at: str
    adoption_decision_at: str
    contract_term_years: int


class TitlePayload(TypedDict, total=False):
    isbn_base: str
    subject: str
    grade_low: int
    grade_high: int
    edition_number: int
    copyright_year: int
    content_tags: List[str]
    page_count: int
    signature_page_capacity: int
    list_price_cents: int


class InventoryAdjustmentPayload(TypedDict, total=False):
    adjustment_type: str
    units: int
    reason: str


class RevisionPlanPayload(TypedDict, total=False):
    action: str
    revision_target_cycle_year: int


class AncillaryBundlePayload(TypedDict, total=False):
    bundle_code: str
    component_count: int
    component_list_total_cents: int
    digital_seat_price_cents: int
    rostering_standard: str
    accessibility_conformance: str
    privacy_addendum_signed: bool


class ContentEditPayload(TypedDict, total=False):
    title_id: str
    state_id: str
    edit_type: str
    topic_code: str
    pages_delta: int
    rationale: str


class ContentEditReviewPayload(TypedDict, total=False):
    verdict: str
    rejection_reason: str


class ContentEditResubmitPayload(TypedDict, total=False):
    pages_delta: int
    rationale: str


class ContentEditRevertPayload(TypedDict, total=False):
    reason: str


class SubmissionPayload(TypedDict, total=False):
    cycle_id: str
    title_id: str


class CorrelationEntryPayload(TypedDict, total=False):
    standard_code: str
    depth_level: str
    page_reference: str
    evidence_citation: str


class CorrelationVerdictPayload(TypedDict, total=False):
    verdict: str


class SamplingShipmentPayload(TypedDict, total=False):
    units: int
    carrier_ref: str


class WithdrawPayload(TypedDict, total=False):
    reason: str


class PublicCommentPayload(TypedDict, total=False):
    commenter_ref: str
    category: str
    severity: str
    body: str


class PublicCommentResponsePayload(TypedDict, total=False):
    response_body: str


class CommitteePanelPayload(TypedDict, total=False):
    cycle_id: str
    panel_label: str
    session_start_at: str
    session_end_at: str
    buffer_minutes: int
    slot_minutes_capacity: int
    member_count: int
    quorum_required: int


class PresentationSlotPayload(TypedDict, total=False):
    submission_id: str
    start_at: str
    end_at: str
    expected_panel_version: int


class CommitteeVotePayload(TypedDict, total=False):
    vote: str
    rationale: str


class PricingProposalPayload(TypedDict, total=False):
    submission_id: str
    bundle_id: str
    base_price_cents: int
    term_years: int
    annual_escalator_bps: int
    projected_adoption_units: int
    digital_seat_price_cents: int
    expected_submission_version: int


class PricingDecisionPayload(TypedDict, total=False):
    verdict: str


class DistrictOrderPayload(TypedDict, total=False):
    district_ref: str
    state_id: str
    title_id: str
    pricing_proposal_id: str
    print_units: int
    digital_seats: int


class OrderCancelPayload(TypedDict, total=False):
    reason: str


class ClockPayload(TypedDict, total=False):
    to_iso8601: str
