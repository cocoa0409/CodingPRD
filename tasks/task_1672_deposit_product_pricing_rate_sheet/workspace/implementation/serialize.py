"""Per-entity serialization: common fields + declared fields only; computed
fields resolved on read (PRD 2.5)."""

from db import today
from utils import add_days_iso

_COMMON = ("id", "created_at", "updated_at", "version")

_FIELDS = {
    "products": ["product_code", "product_class", "term_months", "tier_application",
                 "rate_cap_bp", "allows_promos", "allows_exceptions"],
    "sheets": ["product_id", "market_code", "sheet_version", "effective_date",
               "end_date", "disclosure_lead_days", "margin_floor_bp",
               "source_scan_id", "supersedes_sheet_id", "tiers",
               "total_projected_balance_cents", "status"],
    "scans": ["market_code", "scan_date", "source_name", "entries",
              "benchmark_weighted_bp", "benchmark_simple_bp", "status"],
    "cycles": ["product_id", "market_code", "cadence_days", "last_reviewed_at",
               "next_review_due", "status"],
    "promos": ["product_id", "market_code", "promo_rate_bp", "promo_term_days",
               "enrollment_start", "enrollment_end", "min_opening_balance_cents",
               "rollover_treatment", "status"],
    "exceptions": ["account_id", "sheet_id", "requested_rate_bp", "baseline_rate_bp",
                   "delta_bp", "authority_tier", "term_days", "justification_doc_ref",
                   "submitted_by_user_id", "decided_by_user_id", "status"],
    "accounts": ["customer_ref", "product_id", "market_code", "sheet_id",
                 "balance_cents", "channel", "lifecycle", "rate_source",
                 "promo_offer_id", "promo_end_date", "exception_request_id",
                 "exception_end_date", "base_rate_bp", "bundle_bonus_bp",
                 "exception_rate_bp", "current_rate_bp", "unposted_accrual_milli",
                 "posted_interest_cents", "last_accrual_date", "opened_at"],
    "curves": ["curve_date", "points"],
    "bundles": ["bundle_code", "bonus_bp", "min_combined_balance_cents",
                "required_product_classes", "eligible_product_classes"],
    "enrollments": ["bundle_id", "customer_ref", "qualifying_balance_cents", "status"],
    "notices": ["sheet_id", "account_id", "channel", "notice_type",
                "required_by_date", "sent_at", "is_late", "status"],
    "deployments": ["sheet_id", "channel", "deployed_at", "status"],
    "migrations": ["source_sheet_id", "target_sheet_id", "migrated_count",
                   "skipped_count", "status"],
}


def cycle_next_review_due(cycle):
    if cycle["last_reviewed_at"] is None:
        return None
    return add_days_iso(cycle["last_reviewed_at"], cycle["cadence_days"])


def cycle_status(cycle):
    """repricing_cadence_status: OVERDUE when last_reviewed_at is set and
    logical today >= next_review_due (inclusive boundary)."""
    due = cycle_next_review_due(cycle)
    if due is None:
        return "CURRENT"
    from datetime import date
    return "OVERDUE" if today() >= date.fromisoformat(due) else "CURRENT"


def notice_is_late(n):
    if n["status"] == "SENT":
        return bool(n["is_late"])
    if n["status"] == "PENDING":
        from datetime import date
        return today() > date.fromisoformat(n["required_by_date"])
    return False


def serialize(kind, row):
    out = {}
    for f in _FIELDS[kind]:
        if kind == "cycles" and f == "next_review_due":
            out[f] = cycle_next_review_due(row)
        elif kind == "cycles" and f == "status":
            out[f] = cycle_status(row)
        elif kind == "notices" and f == "is_late":
            out[f] = notice_is_late(row)
        else:
            out[f] = row.get(f)
    for f in _COMMON:
        out[f] = row[f]
    return out


def serialize_many(kind, rows):
    return [serialize(kind, r) for r in rows]
