"""Resource serialisation. Derived aggregates are computed at read time."""
import db
from services import calc, ledger
from util import fmt_dt


def _common(rec):
    return {"id": rec["id"],
            "created_at": fmt_dt(rec["created_at"]),
            "updated_at": fmt_dt(rec["updated_at"]),
            "version": rec["version"]}


def market(rec):
    out = {
        "market_code": rec["market_code"],
        "name": rec["name"],
        "currency_code": rec["currency_code"],
        "strategic_positioning": rec["strategic_positioning"],
        "strategic_index_target_bp": rec["strategic_index_target_bp"],
        "index_tolerance_bp": rec["index_tolerance_bp"],
        "observed_index_bp": rec["observed_index_bp"],
        "positioning_gap_bp": rec["positioning_gap_bp"],
        "insufficient_data_report_count": rec["insufficient_data_report_count"],
        "pricing_posture": rec["pricing_posture"],
    }
    out.update(_common(rec))
    return out


def competitor(rec):
    confirmed = calc.confirmed_match_count(rec["id"])
    stale = calc.stale_match_count(rec["id"])
    out = {
        "market_id": rec["market_id"],
        "competitor_code": rec["competitor_code"],
        "name": rec["name"],
        "collection_method": rec["collection_method"],
        "tier": rec["tier"],
        "price_match_eligible": rec["price_match_eligible"],
        "status": rec["status"],
        "suspension_reason": rec["suspension_reason"],
        "confirmed_match_count": confirmed,
        "stale_match_count": stale,
        "stale_share_bp": calc.stale_share_bp(rec["id"]),
    }
    out.update(_common(rec))
    return out


def product(rec):
    out = {
        "market_id": rec["market_id"],
        "sku": rec["sku"],
        "category_code": rec["category_code"],
        "brand": rec["brand"],
        "own_price_cents": rec["own_price_cents"],
        "unit_cost_cents": rec["unit_cost_cents"],
        "margin_floor_pct": rec["margin_floor_pct"],
        "map_floor_cents": rec["map_floor_cents"],
        "brand_repricing_restricted": rec["brand_repricing_restricted"],
        "index_weight_bp": rec["index_weight_bp"],
        "status": rec["status"],
        "last_price_change_at": fmt_dt(rec["last_price_change_at"]),
        "price_change_count": calc.price_change_count(rec["id"]),
        "effective_floor_cents": calc.effective_floor_cents(rec),
    }
    out.update(_common(rec))
    return out


def store(rec):
    used = ledger.label_slots_used_today(rec)
    out = {
        "market_id": rec["market_id"],
        "store_code": rec["store_code"],
        "override_authority_cents": rec["override_authority_cents"],
        "label_printer_capacity_per_day": rec["label_printer_capacity_per_day"],
        "label_slots_used_today": used,
        "label_slots_remaining_today": rec["label_printer_capacity_per_day"] - used,
        "override_budget_used_cents": ledger.override_budget_used_cents(rec),
        "override_budget_remaining_cents": ledger.override_budget_remaining_cents(rec),
    }
    out.update(_common(rec))
    return out


def link(rec):
    out = {
        "product_id": rec["product_id"],
        "competitor_id": rec["competitor_id"],
        "match_method": rec["match_method"],
        "competitor_identifier": rec["competitor_identifier"],
        "identifier_score": rec["identifier_score"],
        "attribute_score": rec["attribute_score"],
        "image_score": rec["image_score"],
        "confidence_bp": rec["confidence_bp"],
        "confidence_variant": rec["confidence_variant"],
        "match_grade": rec["match_grade"],
        "review_round": rec["review_round"],
        "status": rec["status"],
        "latest_effective_price_cents": rec["latest_effective_price_cents"],
        "selected_observation_id": rec["selected_observation_id"],
        "data_status": rec["data_status"],
        "gap_bp": rec["gap_bp"],
        "gap_stale": rec["gap_stale"],
    }
    out.update(_common(rec))
    return out


def observation(rec):
    out = {
        "link_id": rec["link_id"],
        "observed_price_cents": rec["observed_price_cents"],
        "collection_method": rec["collection_method"],
        "observed_at": fmt_dt(rec["observed_at"]),
        "in_stock": rec["in_stock"],
        "promo_flag": rec["promo_flag"],
        "status": rec["status"],
        "void_reason": rec["void_reason"],
    }
    out.update(_common(rec))
    return out


def report(rec):
    out = {
        "market_id": rec["market_id"],
        "category_code": rec["category_code"],
        "basis": rec["basis"],
        "index_bp": rec["index_bp"],
        "candidate_product_count": rec["candidate_product_count"],
        "matched_product_count": rec["matched_product_count"],
        "imputed_product_count": rec["imputed_product_count"],
        "excluded_product_count": rec["excluded_product_count"],
        "data_sufficiency": rec["data_sufficiency"],
        "positioning_gap_bp": rec["positioning_gap_bp"],
        "positioning_verdict": rec["positioning_verdict"],
        "perception_survey_index_bp": rec["perception_survey_index_bp"],
        "perception_validation": rec["perception_validation"],
        "status": rec["status"],
        "published_at": fmt_dt(rec["published_at"]),
    }
    out.update(_common(rec))
    return out


def rule(rec):
    out = {
        "market_id": rec["market_id"],
        "category_code": rec["category_code"],
        "target_position_bp": rec["target_position_bp"],
        "max_change_pct": rec["max_change_pct"],
        "change_frequency_limit_days": rec["change_frequency_limit_days"],
        "priority": rec["priority"],
        "brand_exclusions": list(rec["brand_exclusions"]),
        "status": rec["status"],
        "applied_order_count": calc.applied_order_count(rec["id"]),
    }
    out.update(_common(rec))
    return out


def order(rec):
    out = {
        "product_id": rec["product_id"],
        "market_id": rec["market_id"],
        "rule_id": rec["rule_id"],
        "source_claim_id": rec["source_claim_id"],
        "signage_store_id": rec["signage_store_id"],
        "supersedes_order_id": rec["supersedes_order_id"],
        "label_batch_id": rec["label_batch_id"],
        "origin": rec["origin"],
        "requested_price_cents": rec["requested_price_cents"],
        "benchmark_price_cents": rec["benchmark_price_cents"],
        "target_price_cents": rec["target_price_cents"],
        "banded_price_cents": rec["banded_price_cents"],
        "effective_floor_cents": rec["effective_floor_cents"],
        "proposed_price_cents": rec["proposed_price_cents"],
        "floor_binding": rec["floor_binding"],
        "band_breach": rec["band_breach"],
        "effective_from": fmt_dt(rec["effective_from"]),
        "effective_until": fmt_dt(rec["effective_until"]),
        "status": rec["status"],
        "signage_status": rec["signage_status"],
        "authored_by_user_id": rec["authored_by_user_id"],
        "decided_by_user_id": rec["decided_by_user_id"],
    }
    out.update(_common(rec))
    return out


def policy(rec):
    out = {
        "market_id": rec["market_id"],
        "eligible_competitor_tiers": list(rec["eligible_competitor_tiers"]),
        "excluded_category_codes": list(rec["excluded_category_codes"]),
        "verification_required": rec["verification_required"],
        "max_match_discount_pct": rec["max_match_discount_pct"],
        "daily_override_budget_cents": rec["daily_override_budget_cents"],
        "claim_window_hours": rec["claim_window_hours"],
        "status": rec["status"],
        "honored_claim_count": calc.honored_claim_count(rec["id"]),
    }
    out.update(_common(rec))
    return out


def claim(rec):
    out = {
        "policy_id": rec["policy_id"],
        "product_id": rec["product_id"],
        "competitor_id": rec["competitor_id"],
        "store_id": rec["store_id"],
        "verification_link_id": rec["verification_link_id"],
        "claimed_price_cents": rec["claimed_price_cents"],
        "claimed_observed_at": fmt_dt(rec["claimed_observed_at"]),
        "competitor_evidence_ref": rec["competitor_evidence_ref"],
        "beat_bonus_cents": rec["beat_bonus_cents"],
        "honored_price_cents": rec["honored_price_cents"],
        "discount_cents": rec["discount_cents"],
        "required_approval_tier": rec["required_approval_tier"],
        "evidence_round": rec["evidence_round"],
        "status": rec["status"],
        "rejection_reason": rec["rejection_reason"],
        "reversal_reason": rec["reversal_reason"],
    }
    out.update(_common(rec))
    return out


def batch(rec):
    out = {
        "store_id": rec["store_id"],
        "window_start": fmt_dt(rec["window_start"]),
        "window_end": fmt_dt(rec["window_end"]),
        "reserved_item_count": rec["reserved_item_count"],
        "queued_order_ids": list(rec["queued_order_ids"]),
        "item_count": ledger.batch_item_count(rec),
        "status": rec["status"],
        "cancel_reason": rec["cancel_reason"],
    }
    out.update(_common(rec))
    return out


def override_log(rec):
    return {
        "id": rec["id"],
        "claim_id": rec["claim_id"],
        "direction": rec["direction"],
        "approval_tier": rec["approval_tier"],
        "approved_by_role": rec["approved_by_role"],
        "approved_by_user_id": rec["approved_by_user_id"],
        "approved_discount_cents": rec["approved_discount_cents"],
        "honored_price_cents": rec["honored_price_cents"],
        "created_at": fmt_dt(rec["created_at"]),
    }
