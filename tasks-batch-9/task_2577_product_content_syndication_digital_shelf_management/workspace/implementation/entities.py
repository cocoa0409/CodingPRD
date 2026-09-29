"""Entity lookups (PRD 2.8 existence steps) and output serializers."""
from datetime import datetime

from errors import ApiError
from store import db, fmt_dt

# ------------------------------------------------------------------ lookups
def _get(table, row_id, error_id):
    if not isinstance(row_id, str) or row_id == "":
        raise ApiError(error_id)
    row = table.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


def get_retailer(row_id):
    return _get(db.retailers, row_id, "ERR_RETAILER_NOT_FOUND")


def get_product(row_id):
    return _get(db.products, row_id, "ERR_PRODUCT_NOT_FOUND")


def get_content_version(row_id):
    return _get(db.content_versions, row_id, "ERR_CONTENT_VERSION_NOT_FOUND")


def get_listing(row_id):
    return _get(db.listings, row_id, "ERR_LISTING_NOT_FOUND")


def get_media_asset(row_id):
    return _get(db.media_assets, row_id, "ERR_MEDIA_ASSET_NOT_FOUND")


def get_change_request(row_id):
    return _get(db.change_requests, row_id, "ERR_CHANGE_REQUEST_NOT_FOUND")


def get_job(row_id):
    return _get(db.jobs, row_id, "ERR_SYNDICATION_JOB_NOT_FOUND")


def get_rejection_error(row_id):
    return _get(db.rejection_errors, row_id, "ERR_REJECTION_ERROR_NOT_FOUND")


def get_deployment(row_id):
    return _get(db.deployments, row_id, "ERR_DEPLOYMENT_NOT_FOUND")


def get_alert(row_id):
    return _get(db.alerts, row_id, "ERR_ALERT_NOT_FOUND")


def require_attribute_key(attribute_key):
    """Evaluation step 20 -> ERR_ATTRIBUTE_KEY_UNKNOWN (422)."""
    for row in db.attribute_definitions.values():
        if row["attribute_key"] == attribute_key:
            return row
    raise ApiError("ERR_ATTRIBUTE_KEY_UNKNOWN")


# -------------------------------------------------------------- serializers
COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "retailer": ("name", "retailer_code", "status", "min_image_count", "feed_slot_capacity",
                 "max_concurrent_feed_windows", "enhanced_content_requires_approval",
                 "feed_slots_reserved"),
    "attribute_definition": ("attribute_key", "data_type", "taxonomy_group", "max_chars",
                             "base_weight", "is_global_required"),
    "retailer_requirement": ("retailer_id", "attribute_key", "requirement_level",
                             "max_chars_override", "weight_override"),
    "product": ("sku", "gtin", "category_code", "brand_code", "status", "shelf_health_index",
                "conversion_lift_pct", "open_alert_count", "governance_flag",
                "last_pinned_at", "last_review_at"),
    "content_version": ("product_id", "supersedes_content_version_id", "revision_no", "state",
                        "image_count", "pin_count", "author_user_id"),
    "attribute_value": ("content_version_id", "attribute_key", "value", "char_count",
                        "type_valid"),
    "media_asset": ("product_id", "asset_role", "source_uri", "approval_state",
                    "approving_retailer_id", "decided_at"),
    "listing": ("product_id", "retailer_id", "pinned_content_version_id", "account_team_user_id",
                "syndication_state", "shelf_state", "completeness_score_declared",
                "completeness_score_certified", "readiness_score", "search_rank_latest",
                "content_accuracy_pct", "rating_avg", "in_stock", "open_blocking_error_count"),
    "job": ("retailer_listing_id", "content_version_id", "slot_count", "window_start",
            "window_end", "state", "attempt_no", "readiness_at_queue", "service_fee_cents",
            "transmitted_at", "responded_at"),
    "rejection_error": ("syndication_job_id", "retailer_error_code", "attribute_key", "severity",
                        "message", "state", "resolution_mode", "resolved_by_user_id",
                        "resolution_note", "resolved_at"),
    "change_request": ("product_id", "retailer_id", "target_content_version_id", "rationale",
                       "state", "legal_review_state", "brand_review_state", "author_user_id",
                       "legal_reviewer_user_id", "brand_reviewer_user_id", "submitted_at",
                       "decided_at"),
    "deployment": ("retailer_listing_id", "change_request_id", "media_asset_id", "module_kind",
                   "window_start", "window_end", "state", "retailer_decision_at",
                   "withdrawn_reason"),
    "observation": ("retailer_listing_id", "observed_at", "search_rank", "in_stock",
                    "content_accuracy_pct", "rating_avg", "rating_count",
                    "unauthorized_seller_count", "conversion_rate_pct", "units_sold"),
    "alert": ("retailer_listing_id", "source_observation_id", "alert_type", "severity", "state",
              "assigned_account_team_user_id", "acknowledged_by_user_id", "resolution_note",
              "resolved_at"),
}


def _value(raw):
    if isinstance(raw, datetime):
        return fmt_dt(raw)
    return raw


def _shape(row, kind, common=COMMON):
    out = {}
    for key in common:
        out[key] = _value(row.get(key))
    for key in FIELDS[kind]:
        out[key] = _value(row.get(key))
    return out


def retailer_out(row):
    return _shape(row, "retailer")


def attribute_definition_out(row):
    return _shape(row, "attribute_definition")


def retailer_requirement_out(row):
    return _shape(row, "retailer_requirement")


def product_out(row):
    return _shape(row, "product")


def content_version_out(row):
    return _shape(row, "content_version")


def attribute_value_out(row):
    return _shape(row, "attribute_value")


def media_asset_out(row):
    return _shape(row, "media_asset")


def listing_out(row):
    return _shape(row, "listing")


def job_out(row):
    return _shape(row, "job")


def rejection_error_out(row):
    return _shape(row, "rejection_error")


def change_request_out(row):
    return _shape(row, "change_request")


def deployment_out(row):
    return _shape(row, "deployment")


def observation_out(row):
    # Append-only event row: id and created_at only, no updated_at and no version (PRD 2.4).
    return _shape(row, "observation", common=("id", "created_at"))


def alert_out(row):
    return _shape(row, "alert")
