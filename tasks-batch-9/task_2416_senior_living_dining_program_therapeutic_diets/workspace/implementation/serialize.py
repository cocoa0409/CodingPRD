"""Response serializers -- one per entity, with the exact declared field set."""
from decimal import Decimal

from services import derive


def _num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _versioned(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def _append_only(row):
    return {"id": row["id"], "created_at": row["created_at"]}


def community(row):
    out = _versioned(row)
    out.update({
        "name": row["name"],
        "care_levels_offered": list(row["care_levels_offered"]),
        "guest_meal_sponsor_cap_cents": row["guest_meal_sponsor_cap_cents"],
        "variance_tolerance_cents": row["variance_tolerance_cents"],
        "pending_dietitian_review_count": derive.pending_dietitian_review_count(row["id"]),
        "active_menu_cycle_id": derive.active_menu_cycle_id(row["id"]),
    })
    return out


def venue(row):
    out = _versioned(row)
    out.update({
        "community_id": row["community_id"],
        "name": row["name"],
        "venue_kind": row["venue_kind"],
        "seat_capacity": row["seat_capacity"],
        "seating_turn_minutes": row["seating_turn_minutes"],
        "turnover_buffer_minutes": row["turnover_buffer_minutes"],
        "care_levels_served": list(row["care_levels_served"]),
        "temp_compliance_posture": row["temp_compliance_posture"],
        "consecutive_temp_violation_count": row["consecutive_temp_violation_count"],
        "status": row["status"],
    })
    return out


def resident(row):
    out = _versioned(row)
    out.update({
        "community_id": row["community_id"],
        "full_name": row["full_name"],
        "care_level": row["care_level"],
        "dining_status": row["dining_status"],
        "baseline_weight_kg": _num(row["baseline_weight_kg"]),
        "current_weight_kg": _num(row["current_weight_kg"]),
        "rolling_30d_weight_change_pct": _num(row["rolling_30d_weight_change_pct"]),
        "baseline_weight_change_pct": _num(row["baseline_weight_change_pct"]),
        "avg_intake_pct_7d": _num(row["avg_intake_pct_7d"]),
        "intake_risk_score": _num(row["intake_risk_score"]),
        "allergens": list(row["allergens"]),
        "dislikes": list(row["dislikes"]),
        "preference_strictness": row["preference_strictness"],
        "guest_meal_charge_balance_cents": row["guest_meal_charge_balance_cents"],
        "tray_card_state": row["tray_card_state"],
    })
    return out


def diet_order(row):
    out = _versioned(row)
    out.update({
        "resident_id": row["resident_id"],
        "supersedes_order_id": row["supersedes_order_id"],
        "texture_level": row["texture_level"],
        "liquid_consistency": row["liquid_consistency"],
        "therapeutic_codes": list(row["therapeutic_codes"]),
        "clinical_status": row["clinical_status"],
        "review_status": row["review_status"],
        "review_round": row["review_round"],
        "ordered_by_user_id": row["ordered_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "reviewer_note": row["reviewer_note"],
        "activated_at": row["activated_at"],
    })
    return out


def substitution_rule(row):
    out = _versioned(row)
    out.update({
        "resident_id": row["resident_id"],
        "trigger_type": row["trigger_type"],
        "match_value": row["match_value"],
        "replacement_item_code": row["replacement_item_code"],
        "priority_rank": row["priority_rank"],
        "status": row["status"],
    })
    return out


def reservation(row):
    out = _versioned(row)
    out.update({
        "resident_id": row["resident_id"],
        "venue_id": row["venue_id"],
        "service_date": row["service_date"],
        "meal_period": row["meal_period"],
        "seat_start_utc": row["seat_start_utc"],
        "seat_end_utc": row["seat_end_utc"],
        "party_size": row["party_size"],
        "allow_waitlist": row["allow_waitlist"],
        "status": row["status"],
        "suspension_hold": row["suspension_hold"],
        "seated_at": row["seated_at"],
    })
    return out


def menu_cycle(row):
    out = _versioned(row)
    out.update({
        "community_id": row["community_id"],
        "cycle_number": row["cycle_number"],
        "week_count": row["week_count"],
        "effective_start_date": row["effective_start_date"],
        "effective_end_date": row["effective_end_date"],
        "status": row["status"],
        "refresh_index": _num(row["refresh_index"]),
        "refresh_tier": row["refresh_tier"],
        "refresh_round": row["refresh_round"],
        "refresh_reason": row["refresh_reason"],
        "signed_off_by_user_id": row["signed_off_by_user_id"],
    })
    return out


def menu_item(row):
    out = _versioned(row)
    out.update({
        "menu_cycle_id": row["menu_cycle_id"],
        "item_code": row["item_code"],
        "name": row["name"],
        "day_index": row["day_index"],
        "meal_period": row["meal_period"],
        "base_texture": row["base_texture"],
        "allergen_tags": list(row["allergen_tags"]),
        "required_therapeutic_codes": list(row["required_therapeutic_codes"]),
        "extension_coverage_status": row["extension_coverage_status"],
    })
    return out


def extension(row):
    out = _versioned(row)
    out.update({
        "menu_item_id": row["menu_item_id"],
        "diet_code": row["diet_code"],
        "nutrient_overrides": row["nutrient_overrides"],
        "review_status": row["review_status"],
        "review_round": row["review_round"],
        "authored_by_user_id": row["authored_by_user_id"],
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "reviewer_note": row["reviewer_note"],
    })
    return out


def ticket(row):
    out = _versioned(row)
    out.update({
        "venue_id": row["venue_id"],
        "resident_id": row["resident_id"],
        "reservation_id": row["reservation_id"],
        "billed_reconciliation_id": row["billed_reconciliation_id"],
        "ticket_type": row["ticket_type"],
        "service_date": row["service_date"],
        "meal_period": row["meal_period"],
        "billed_amount_cents": row["billed_amount_cents"],
        "voided_amount_cents": row["voided_amount_cents"],
        "status": row["status"],
        "issued_by_user_id": row["issued_by_user_id"],
    })
    return out


def reconciliation(row):
    out = _versioned(row)
    out.update({
        "community_id": row["community_id"],
        "period_start_date": row["period_start_date"],
        "period_end_date": row["period_end_date"],
        "ticket_ledger_total_cents": row["ticket_ledger_total_cents"],
        "census_projection_total_cents": row["census_projection_total_cents"],
        "variance_cents": row["variance_cents"],
        "ledger_meal_counts": dict(row["ledger_meal_counts"]),
        "census_meal_counts": dict(row["census_meal_counts"]),
        "void_credit_cents": row["void_credit_cents"],
        "pre_fee_base_cents": row["pre_fee_base_cents"],
        "administrative_fee_cents": row["administrative_fee_cents"],
        "net_billable_total_cents": row["net_billable_total_cents"],
        "variance_note": row["variance_note"],
        "status": row["status"],
        "finalized_by_user_id": row["finalized_by_user_id"],
    })
    return out


def observation(row):
    out = _append_only(row)
    out.update({
        "resident_id": row["resident_id"],
        "observation_date": row["observation_date"],
        "meal_period": row["meal_period"],
        "intake_pct": row["intake_pct"],
        "weight_kg": _num(row["weight_kg"]),
        "recorded_by_user_id": row["recorded_by_user_id"],
    })
    return out


def review(row):
    out = _versioned(row)
    out.update({
        "resident_id": row["resident_id"],
        "trigger_observation_id": row["trigger_observation_id"],
        "trigger_reason": row["trigger_reason"],
        "risk_score_at_open": _num(row["risk_score_at_open"]),
        "status": row["status"],
        "outcome": row["outcome"],
        "completed_by_user_id": row["completed_by_user_id"],
    })
    return out


def temperature_log(row):
    out = _append_only(row)
    out.update({
        "venue_id": row["venue_id"],
        "probe_point": row["probe_point"],
        "temperature_f": _num(row["temperature_f"]),
        "corrective_action_code": row["corrective_action_code"],
        "logged_at_utc": row["logged_at_utc"],
        "in_range": row["in_range"],
        "violation_sequence_index": row["violation_sequence_index"],
        "logged_by_user_id": row["logged_by_user_id"],
    })
    return out


def feedback(row):
    out = _append_only(row)
    out.update({
        "menu_cycle_id": row["menu_cycle_id"],
        "resident_id": row["resident_id"],
        "menu_item_code": row["menu_item_code"],
        "sentiment": row["sentiment"],
        "vote_weight": row["vote_weight"],
        "status": row["status"],
    })
    return out


def many(fn, rows):
    return [fn(row) for row in rows]
