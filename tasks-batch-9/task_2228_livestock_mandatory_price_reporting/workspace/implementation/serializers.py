"""Entity → JSON projections.

Field sets follow SCAFFOLD §1.1 exactly. Records carrying common fields expose
id / created_at / updated_at / version; the three append-only ledger line types
(TransactionRecord, WholesaleLot, PublicComment) expose only id / created_at
(PRD §2.5).
"""


def _pick(rec, fields):
    return {f: rec.get(f) for f in fields}


REPORTING_ENTITY_FIELDS = (
    "id",
    "legal_name",
    "entity_type",
    "species_scope",
    "delinquency_points",
    "assessed_penalty_cents",
    "paid_penalty_cents",
    "waived_penalty_cents",
    "outstanding_penalty_cents",
    "created_at",
    "updated_at",
    "version",
)

PLANT_FIELDS = (
    "id",
    "reporting_entity_id",
    "plant_code",
    "species",
    "annual_head_history",
    "boxed_beef_volume_lbs_prior_year",
    "forward_commitment_cap_head",
    "status",
    "wholesale_reporting_required",
    "created_at",
    "updated_at",
    "version",
)

REGISTRATION_FIELDS = (
    "id",
    "reporting_entity_id",
    "determination_year",
    "basis_variant",
    "measured_head",
    "threshold_head",
    "determination_outcome",
    "registration_number",
    "status",
    "appeal_count",
    "suspended_reason",
    "effective_from",
    "created_at",
    "updated_at",
    "version",
)

REPORTING_WINDOW_FIELDS = (
    "id",
    "species",
    "report_class",
    "frequency",
    "period_start",
    "period_end",
    "submission_deadline_utc",
    "correction_deadline_utc",
    "publication_release_utc",
    "min_reporter_count",
    "max_single_reporter_share_pct",
    "min_reported_head",
    "status",
    "accepted_submission_count",
    "total_head_reported",
    "created_at",
    "updated_at",
    "version",
)

SUBMISSION_FIELDS = (
    "id",
    "plant_id",
    "reporting_window_id",
    "supersedes_submission_id",
    "status",
    "submitted_at",
    "accepted_at",
    "lateness_minutes",
    "is_late",
    "days_late",
    "reported_head",
    "reported_cwt",
    "reported_value_dollars",
    "reported_pounds",
    "reported_load_count",
    "resubmission_count",
    "correction_reason",
    "review_note",
    "created_at",
    "updated_at",
    "version",
)

TRANSACTION_RECORD_FIELDS = (
    "id",
    "submission_id",
    "purchase_type",
    "head_count",
    "avg_net_price_per_cwt",
    "avg_carcass_weight_cwt",
    "formula_base_reference",
    "grid_premium_discount_per_cwt",
    "forward_delivery_start",
    "forward_delivery_end",
    "line_value_dollars",
    "created_at",
)

WHOLESALE_LOT_FIELDS = (
    "id",
    "submission_id",
    "product_class",
    "sale_type",
    "load_count",
    "total_pounds",
    "price_per_cwt",
    "lot_value_dollars",
    "created_at",
)

MARKET_REPORT_FIELDS = (
    "id",
    "reporting_window_id",
    "category",
    "weighting_variant",
    "purchase_type_filter",
    "aggregation_state",
    "disclosure_state",
    "publication_state",
    "weighted_average_price_per_cwt",
    "price_low_per_cwt",
    "price_high_per_cwt",
    "total_head",
    "total_pounds",
    "reporter_count",
    "max_reporter_share_pct",
    "source_submission_count",
    "suppression_reason",
    "computed_at",
    "published_at",
    "created_at",
    "updated_at",
    "version",
)

AUDIT_CASE_FIELDS = (
    "id",
    "submission_id",
    "materiality_pct",
    "status",
    "opened_by_user_id",
    "finalized_by_user_id",
    "verified_head",
    "verified_value_dollars",
    "head_discrepancy_rate_pct",
    "value_discrepancy_rate_pct",
    "finding",
    "closed_at",
    "created_at",
    "updated_at",
    "version",
)

PENALTY_ASSESSMENT_FIELDS = (
    "id",
    "reporting_entity_id",
    "audit_case_id",
    "submission_id",
    "violation_type",
    "days_late",
    "base_amount_cents",
    "repeat_index",
    "day_tier_multiplier",
    "repeat_multiplier",
    "volume_factor",
    "suspension_surcharge",
    "assessed_amount_cents",
    "points",
    "delinquency_tier_at_assessment",
    "status",
    "assessed_by_user_id",
    "waiver_reason",
    "settled_at",
    "created_at",
    "updated_at",
    "version",
)

METHODOLOGY_CHANGE_FIELDS = (
    "id",
    "change_code",
    "affected_category",
    "proposed_weighting_variant",
    "comment_period_end",
    "effective_from",
    "status",
    "comment_count",
    "industry_notice_issued_at",
    "restated_report_count",
    "created_at",
    "updated_at",
    "version",
)

PUBLIC_COMMENT_FIELDS = (
    "id",
    "methodology_change_id",
    "commenter_reference",
    "comment_text",
    "stance",
    "received_at",
    "created_at",
)


def reporting_entity(rec):
    return _pick(rec, REPORTING_ENTITY_FIELDS)


def plant(rec):
    return _pick(rec, PLANT_FIELDS)


def registration(rec):
    return _pick(rec, REGISTRATION_FIELDS)


def reporting_window(rec):
    return _pick(rec, REPORTING_WINDOW_FIELDS)


def submission(rec):
    return _pick(rec, SUBMISSION_FIELDS)


def transaction_record(rec):
    return _pick(rec, TRANSACTION_RECORD_FIELDS)


def wholesale_lot(rec):
    return _pick(rec, WHOLESALE_LOT_FIELDS)


def market_report(rec):
    return _pick(rec, MARKET_REPORT_FIELDS)


def audit_case(rec):
    return _pick(rec, AUDIT_CASE_FIELDS)


def penalty_assessment(rec):
    return _pick(rec, PENALTY_ASSESSMENT_FIELDS)


def methodology_change(rec):
    return _pick(rec, METHODOLOGY_CHANGE_FIELDS)


def public_comment(rec):
    return _pick(rec, PUBLIC_COMMENT_FIELDS)
