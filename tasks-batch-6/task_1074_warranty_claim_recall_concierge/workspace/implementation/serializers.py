"""Serialize internal records to API response dicts (strip private fields, add computed)."""
import calc
from util import format_dt

_COMMON = ["id", "created_at", "updated_at", "version"]


def _base(rec, fields):
    out = {}
    for f in _COMMON:
        if f in rec:
            out[f] = rec[f]
    for f in fields:
        out[f] = rec.get(f)
    return out


def household(rec):
    return _base(rec, [
        "primary_email", "display_name", "exposure_scoring_mode",
        "recall_exposure_score", "active_claim_count", "status",
    ])


def member(rec):
    return _base(rec, ["household_id", "full_name", "email", "role", "status"])


def subscription(rec):
    return _base(rec, [
        "household_id", "tier", "status", "period_start", "period_end",
        "claims_used", "auto_renew",
    ])


def manufacturer(rec):
    return _base(rec, ["name", "contact_email", "coordination_enabled", "rma_required"])


def product(rec):
    out = _base(rec, [
        "household_id", "manufacturer_id", "model_number", "serial_number",
        "purchase_date", "purchase_price_cents", "warranty_months",
        "registration_status", "recall_status",
    ])
    out["warranty_expires_at"] = format_dt(calc.warranty_expires_at(rec))
    out["coverage_status"] = calc.coverage_status(rec)
    return out


def recall_notice(rec):
    return _base(rec, [
        "manufacturer_id", "affected_model_number", "serial_range_start",
        "serial_range_end", "severity", "remedy_type", "effective_from",
        "effective_to", "status", "matched_product_count",
    ])


def recall_match(rec):
    return _base(rec, ["recall_notice_id", "product_id", "severity_weight", "status"])


def claim(rec):
    return _base(rec, [
        "product_id", "filed_by_member_id", "recall_match_id", "claim_type",
        "resolution_preference", "issue_description", "shipping_cost_cents",
        "reviewed_by_user_id", "status", "settlement_total_cents",
    ])


def claim_document(rec):
    out = {"id": rec["id"], "created_at": rec["created_at"]}
    for f in ("claim_id", "doc_type", "file_uri"):
        out[f] = rec.get(f)
    return out


def resolution(rec):
    return _base(rec, [
        "claim_id", "replacement_product_id", "mode", "refund_variant",
        "refund_amount_cents", "shipping_cost_cents", "shipping_reimbursement_cents",
        "concierge_fee_cents", "settlement_total_cents", "rma_status",
        "rma_number", "status",
    ])
