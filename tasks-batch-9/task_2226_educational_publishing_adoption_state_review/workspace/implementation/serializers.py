"""Resource serializers."""

from datetime import datetime
from decimal import Decimal

from db import iso

STATE_PROFILE_FIELDS = (
    "id", "state_code", "adoption_model", "sampling_copies_required",
    "comment_response_days", "required_topics", "prohibited_content_tags",
    "multi_year_max_years", "price_cap_cents", "min_verified_coverage_pct",
    "accessibility_standard", "rostering_standard", "data_privacy_addendum_required",
    "created_at", "updated_at", "version",
)

STATE_STANDARD_FIELDS = (
    "id", "state_id", "subject", "standard_code", "grade_low", "grade_high",
    "weight", "is_focus", "created_at",
)

ADOPTION_CYCLE_FIELDS = (
    "id", "state_id", "subject", "cycle_year", "submission_open_at",
    "submission_deadline_at", "committee_review_at", "public_comment_start_at",
    "public_comment_end_at", "adoption_decision_at", "contract_term_years",
    "status", "phase_epoch", "submission_count", "scheduled_submission_count",
    "adopted_count", "created_at", "updated_at", "version",
)

TITLE_FIELDS = (
    "id", "isbn_base", "subject", "grade_low", "grade_high", "edition_number",
    "copyright_year", "content_tags", "page_count", "signature_page_capacity",
    "page_budget_remaining", "content_revision", "list_price_cents", "status",
    "revision_target_cycle_year", "adopted_state_codes", "total_received_units",
    "on_hand_units", "committed_units", "sample_reserved_units", "fulfilled_units",
    "written_off_units", "created_at", "updated_at", "version",
)

ANCILLARY_BUNDLE_FIELDS = (
    "id", "title_id", "bundle_code", "component_count", "component_list_total_cents",
    "digital_seat_price_cents", "rostering_standard", "accessibility_conformance",
    "privacy_addendum_signed", "created_at", "updated_at", "version",
)

CONTENT_EDIT_FIELDS = (
    "id", "title_id", "state_id", "edit_type", "topic_code", "pages_delta",
    "rationale", "status", "revision_round", "proposed_by_user_id",
    "reviewed_by_user_id", "rejection_reason", "created_at", "updated_at", "version",
)

SUBMISSION_FIELDS = (
    "id", "cycle_id", "title_id", "review_status", "pricing_status",
    "sampling_status", "sample_copies_shipped", "pinned_content_revision",
    "content_pin_stale", "self_reported_coverage_pct", "verified_coverage_pct",
    "prohibited_hit_count", "missing_required_topic_count",
    "unresolved_critical_count", "overdue_response_count", "compliance_score",
    "adoption_blocked", "filed_at", "created_at", "updated_at", "version",
)

CORRELATION_ENTRY_FIELDS = (
    "id", "submission_id", "standard_code", "depth_level", "page_reference",
    "evidence_citation", "reviewer_verdict", "verdict_by_user_id",
    "effective_weight", "created_at", "updated_at", "version",
)

COMMITTEE_PANEL_FIELDS = (
    "id", "cycle_id", "panel_label", "session_start_at", "session_end_at",
    "buffer_minutes", "slot_minutes_capacity", "reserved_minutes", "member_count",
    "quorum_required", "status", "created_at", "updated_at", "version",
)

PRESENTATION_SLOT_FIELDS = (
    "id", "panel_id", "submission_id", "start_at", "end_at", "duration_minutes",
    "status", "tally_outcome", "recommend_ratio", "counted_vote_count",
    "created_at", "updated_at", "version",
)

COMMITTEE_VOTE_FIELDS = (
    "id", "slot_id", "member_user_id", "vote", "rationale", "sequence_no",
    "superseded", "created_at",
)

PUBLIC_COMMENT_FIELDS = (
    "id", "submission_id", "commenter_ref", "category", "severity", "body",
    "status", "response_due_at", "responded_at", "response_body",
    "was_overdue_at_response", "created_at", "updated_at", "version",
)

PRICING_PROPOSAL_FIELDS = (
    "id", "submission_id", "bundle_id", "base_price_cents", "term_years",
    "annual_escalator_bps", "projected_adoption_units", "digital_seat_price_cents",
    "volume_discount_pct", "term_discount_pct", "bundle_discount_pct",
    "total_discount_pct", "net_state_price_cents", "avg_annual_price_cents",
    "status", "contract_locked", "decision_officer_ref", "created_at",
    "updated_at", "version",
)

DISTRICT_ORDER_FIELDS = (
    "id", "district_ref", "state_id", "title_id", "pricing_proposal_id",
    "print_units", "digital_seats", "status", "quoted_tcv_cents",
    "contracted_tcv_cents", "freight_surcharge_cents", "allocated_units",
    "created_by_user_id", "confirmed_by_user_id", "created_at", "updated_at",
    "version",
)


def _convert(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_convert(item) for item in value]
    return value


def serialize(record, fields):
    return {field: _convert(record.get(field)) for field in fields}


def serialize_many(records, fields):
    return [serialize(record, fields) for record in records]
