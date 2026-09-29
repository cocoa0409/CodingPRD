"""Entity -> response body projections (scaffold 1.1 field lists)."""


def _pick(row, fields):
    return {name: row.get(name) for name in fields}


CAMPAIGN_FIELDS = (
    "id", "name", "objective_type", "target_segment_codes", "syndication_retailer_ids",
    "sampling_window_start", "sampling_window_end", "review_due_days",
    "min_review_word_count", "holdout_pct", "budget_total_cents", "status",
    "compliance_posture", "kit_assembly_unit_cost_cents", "budget_committed_cents",
    "budget_available_cents", "enrollment_count", "holdout_enrollment_count",
    "allocated_sample_count", "delivered_sample_count", "approved_review_count",
    "syndicated_review_count", "disclosure_rejected_review_count",
    "substantiated_diversion_count", "write_off_cost_cents",
    "cost_per_sample_provisional_cents", "cost_per_sample_final_cents",
    "launched_by_user_id", "closed_at", "created_at", "updated_at", "version",
)

KIT_LINE_FIELDS = (
    "id", "campaign_id", "component_sku", "component_role", "unit_cost_cents",
    "quantity_per_kit", "component_discount_pct", "extended_cost_cents", "status",
    "units_received", "units_available", "units_reserved", "units_shipped",
    "units_written_off", "created_at", "updated_at", "version",
)

FULFILLMENT_CENTER_FIELDS = (
    "id", "name", "zone_code", "daily_pick_capacity_units", "freight_cents_per_kit",
    "created_at", "updated_at", "version",
)

FULFILLMENT_WAVE_FIELDS = (
    "id", "fulfillment_center_id", "window_start", "window_end",
    "planned_capacity_units", "planned_unit_count", "shipped_unit_count", "status",
    "created_at", "updated_at", "version",
)

PANELIST_FIELDS = (
    "id", "email", "display_name", "address_hash", "account_opened_at",
    "segment_code", "referred_by_panelist_id", "integrity_status",
    "diversion_strikes", "fraud_risk_score_screening", "fraud_risk_score_audit",
    "last_risk_scored_at", "created_at", "updated_at", "version",
)

ENROLLMENT_FIELDS = (
    "id", "campaign_id", "panelist_id", "screening_answers", "enrollment_seq",
    "holdout_flag", "screening_status", "obligation_status",
    "screening_failure_reason", "screen_attempt_count", "review_due_at",
    "fraud_score_at_screening", "created_at", "updated_at", "version",
)

SAMPLE_SHIPMENT_FIELDS = (
    "id", "enrollment_id", "fulfillment_wave_id", "supersedes_shipment_id",
    "surcharge_cents", "status", "committed_cost_cents", "reserved_line_units",
    "kit_unit_total", "shipped_at", "delivered_at", "created_at", "updated_at",
    "version",
)

REVIEW_SUBMISSION_FIELDS = (
    "id", "enrollment_id", "headline", "body_text", "star_rating",
    "disclosure_statement", "honest_opinion_attested", "word_count", "status",
    "revision_count", "first_submitted_at", "changes_requested_by_user_id",
    "approved_by_user_id", "moderator_note", "created_at", "updated_at", "version",
)

RETAILER_FIELDS = (
    "id", "name", "feed_status", "requires_disclosure_badge",
    "min_star_rating_accepted", "max_reviews_per_panelist_per_month",
    "created_at", "updated_at", "version",
)

SYNDICATION_RECORD_FIELDS = (
    "id", "review_submission_id", "retailer_id", "status", "rejection_reason",
    "syndicated_at", "takedown_requested_at", "created_at", "updated_at", "version",
)

DIVERSION_CASE_FIELDS = (
    "id", "panelist_id", "sample_shipment_id", "signal_type", "evidence_note",
    "status", "opened_by_user_id", "substantiated_at", "reopen_count",
    "created_at", "updated_at", "version",
)

PURCHASE_MATCH_FIELDS = (
    "id", "enrollment_id", "retailer_channel_code", "purchase_amount_cents",
    "purchased_at", "match_confidence", "qualified", "created_at",
)

LIFT_ANALYSIS_FIELDS = (
    "id", "campaign_id", "variant", "treated_count", "holdout_count",
    "treated_converted_count", "holdout_converted_count", "treated_conversion_rate",
    "holdout_conversion_rate", "lift_pct", "power_status", "effective_sample_count",
    "diverted_unit_count", "base_cost_per_sample_cents", "penalty_rate_pct",
    "diversion_penalty_cents", "adjusted_cost_per_sample_cents", "superseded",
    "computed_at", "created_at", "updated_at", "version",
)


def campaign(row):
    return _pick(row, CAMPAIGN_FIELDS)


def kit_line(row):
    return _pick(row, KIT_LINE_FIELDS)


def fulfillment_center(row):
    return _pick(row, FULFILLMENT_CENTER_FIELDS)


def fulfillment_wave(row):
    return _pick(row, FULFILLMENT_WAVE_FIELDS)


def panelist(row):
    return _pick(row, PANELIST_FIELDS)


def enrollment(row):
    return _pick(row, ENROLLMENT_FIELDS)


def sample_shipment(row):
    return _pick(row, SAMPLE_SHIPMENT_FIELDS)


def review_submission(row):
    return _pick(row, REVIEW_SUBMISSION_FIELDS)


def retailer(row):
    return _pick(row, RETAILER_FIELDS)


def syndication_record(row):
    return _pick(row, SYNDICATION_RECORD_FIELDS)


def diversion_case(row):
    return _pick(row, DIVERSION_CASE_FIELDS)


def purchase_match(row):
    return _pick(row, PURCHASE_MATCH_FIELDS)


def lift_analysis(row):
    return _pick(row, LIFT_ANALYSIS_FIELDS)


def cost_summary(row):
    return {
        "campaign_id": row["id"],
        "kit_assembly_unit_cost_cents": row["kit_assembly_unit_cost_cents"],
        "cost_per_sample_provisional_cents": row["cost_per_sample_provisional_cents"],
        "cost_per_sample_final_cents": row["cost_per_sample_final_cents"],
        "budget_total_cents": row["budget_total_cents"],
        "budget_committed_cents": row["budget_committed_cents"],
        "budget_available_cents": row["budget_available_cents"],
        "allocated_sample_count": row["allocated_sample_count"],
        "delivered_sample_count": row["delivered_sample_count"],
        "write_off_cost_cents": row["write_off_cost_cents"],
    }
