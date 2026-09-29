"""Wire representations. Only declared fields are exposed; internal keys start '_'."""

import engine


def _audit(row, out, versioned=True):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    if versioned:
        out["updated_at"] = row.get("updated_at")
        out["version"] = row.get("version")
    return out


def tier(row):
    out = {
        "code": row["code"],
        "name": row["name"],
        "tier_rank": row["tier_rank"],
        "upfront_cost_cents": row["upfront_cost_cents"],
        "annual_dues_cents": row["annual_dues_cents"],
        "entitlement_nights_class_a": row["entitlement_nights_class_a"],
        "entitlement_nights_class_b": row["entitlement_nights_class_b"],
        "entitlement_nights_class_c": row["entitlement_nights_class_c"],
        "annual_total_night_cap": row["annual_total_night_cap"],
        "advance_window_days": row["advance_window_days"],
        "max_consecutive_stay_nights": row["max_consecutive_stay_nights"],
        "min_out_nights_between_stays": row["min_out_nights_between_stays"],
        "affiliate_access_enabled": row["affiliate_access_enabled"],
        "resale_allowed": row["resale_allowed"],
        "transfer_fee_cents": row["transfer_fee_cents"],
    }
    return _audit(row, out)


def member(row):
    out = {
        "full_name": row["full_name"],
        "email": row["email"],
        "home_region": row.get("home_region"),
        "status": row["status"],
    }
    return _audit(row, out)


def membership(row):
    engine.recompute_tenure(row)
    out = {
        "member_id": row["member_id"],
        "tier_id": row["tier_id"],
        "transferred_from_membership_id": row.get("transferred_from_membership_id"),
        "membership_status": row["membership_status"],
        "dues_status": row["dues_status"],
        "suspension_reason": row.get("suspension_reason"),
        "purchased_at": row["purchased_at"],
        "tenure_origin_at": row["tenure_origin_at"],
        "upfront_paid_cents": row["upfront_paid_cents"],
        "entitlement_year_start": row["entitlement_year_start"],
        "nights_used_class_a": row["nights_used_class_a"],
        "nights_used_class_b": row["nights_used_class_b"],
        "nights_used_class_c": row["nights_used_class_c"],
        "annual_nights_used": row["annual_nights_used"],
        "dues_balance_cents": row["dues_balance_cents"],
        "dues_paid_through": row.get("dues_paid_through"),
        "transfer_count": row["transfer_count"],
        "resale_eligible_at": row.get("resale_eligible_at"),
        "tenure_years": row["tenure_years"],
    }
    return _audit(row, out)


def park(row):
    out = {
        "name": row["name"],
        "park_class": row["park_class"],
        "affiliate_agreement_id": row.get("affiliate_agreement_id"),
        "network_type": row["network_type"],
        "total_sites": row["total_sites"],
        "member_allocation_pct": row["member_allocation_pct"],
        "member_pool_sites": row["member_pool_sites"],
        "transient_pool_sites": row["transient_pool_sites"],
        "season_open_date": row["season_open_date"],
        "season_close_date": row["season_close_date"],
        "park_status": row["park_status"],
        "amenity_compliance_status": row["amenity_compliance_status"],
        "rating_score": row["rating_score"],
        "forced_cancellation_count": engine.forced_count(row),
        "funded_capital_cents_ytd": row["funded_capital_cents_ytd"],
        "last_inspection_at": row.get("last_inspection_at"),
    }
    return _audit(row, out)


def reservation(row):
    out = {
        "park_id": row["park_id"],
        "membership_id": row.get("membership_id"),
        "booker_type": row["booker_type"],
        "guest_name": row.get("guest_name"),
        "arrival_date": row["arrival_date"],
        "departure_date": row["departure_date"],
        "scheduled_departure_date": row["scheduled_departure_date"],
        "nights": row["nights"],
        "status": row["status"],
        "pool_charged": row["pool_charged"],
        "entitlement_nights_charged": row["entitlement_nights_charged"],
        "affiliate_nights_charged": row["affiliate_nights_charged"],
        "total_charge_cents": row["total_charge_cents"],
        "extension_count": row["extension_count"],
        "extension_denied_count": row["extension_denied_count"],
        "cancellation_reason": row.get("cancellation_reason"),
        "checked_in_at": row.get("checked_in_at"),
        "checked_out_at": row.get("checked_out_at"),
        "consecutive_run_nights": row["consecutive_run_nights"],
    }
    return _audit(row, out)


def agreement(row):
    out = {
        "partner_name": row["partner_name"],
        "status": row["status"],
        "effective_from": row["effective_from"],
        "effective_to": row["effective_to"],
        "annual_member_night_quota": row["annual_member_night_quota"],
        "reciprocity_ratio": row["reciprocity_ratio"],
        "min_tier_rank": row["min_tier_rank"],
        "advance_window_cap_days": row["advance_window_cap_days"],
        "per_stay_night_cap": row["per_stay_night_cap"],
        "settlement_rate_cents_per_night": row["settlement_rate_cents_per_night"],
        "nights_consumed_ytd": row["nights_consumed_ytd"],
        "settlement_owed_cents": row["settlement_owed_cents"],
    }
    return _audit(row, out)


def invoice(row):
    out = {
        "membership_id": row["membership_id"],
        "cycle_year": row["cycle_year"],
        "amount_cents": row["amount_cents"],
        "base_dues_cents": row["base_dues_cents"],
        "capital_assessment_cents": row["capital_assessment_cents"],
        "loyalty_credit_cents": row["loyalty_credit_cents"],
        "late_fee_cents": row["late_fee_cents"],
        "paid_amount_cents": row["paid_amount_cents"],
        "due_date": row["due_date"],
        "paid_at": row.get("paid_at"),
        "status": row["status"],
        "days_past_due": row["days_past_due"],
    }
    return _audit(row, out)


def transfer_request(row):
    out = {
        "membership_id": row["membership_id"],
        "from_member_id": row["from_member_id"],
        "to_member_id": row["to_member_id"],
        "transfer_type": row["transfer_type"],
        "sale_price_cents": row["sale_price_cents"],
        "status": row["status"],
        "transfer_fee_cents": row["transfer_fee_cents"],
        "successor_membership_id": row.get("successor_membership_id"),
        "decided_by_user_id": row.get("decided_by_user_id"),
        "decided_at": row.get("decided_at"),
        "rejection_reason": row.get("rejection_reason"),
    }
    return _audit(row, out)


def inspection(row):
    out = {
        "park_id": row["park_id"],
        "inspected_at": row["inspected_at"],
        "inspector_user_id": row["inspector_user_id"],
        "restroom_score": row["restroom_score"],
        "hookup_score": row["hookup_score"],
        "utility_score": row["utility_score"],
        "road_score": row["road_score"],
        "composite_score": row["composite_score"],
        "result": row["result"],
    }
    return _audit(row, out, versioned=False)


def survey(row):
    out = {
        "reservation_id": row["reservation_id"],
        "park_id": row["park_id"],
        "membership_id": row["membership_id"],
        "overall_rating": row["overall_rating"],
        "cleanliness_rating": row["cleanliness_rating"],
        "staff_rating": row["staff_rating"],
        "value_rating": row["value_rating"],
        "weighted_score": row["weighted_score"],
        "submitted_at": row["submitted_at"],
    }
    return _audit(row, out, versioned=False)


def capital_project(row):
    out = {
        "park_id": row["park_id"],
        "title": row["title"],
        "category": row["category"],
        "requested_cost_cents": row["requested_cost_cents"],
        "fiscal_year": row["fiscal_year"],
        "status": row["status"],
        "priority_score": row["priority_score"],
        "funded_amount_cents": row["funded_amount_cents"],
        "requested_by_user_id": row["requested_by_user_id"],
        "decided_by_user_id": row.get("decided_by_user_id"),
    }
    return _audit(row, out)


def occupancy_exception(row):
    out = {
        "reservation_id": row["reservation_id"],
        "requested_run_nights": row["requested_run_nights"],
        "tier_limit_nights": row["tier_limit_nights"],
        "reason": row["reason"],
        "status": row["status"],
        "granted_run_nights": row["granted_run_nights"],
        "requested_by_user_id": row["requested_by_user_id"],
        "decided_by_user_id": row.get("decided_by_user_id"),
        "decision_note": row.get("decision_note"),
    }
    return _audit(row, out)


def maintenance_window(row):
    out = {
        "park_id": row["park_id"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "work_type": row["work_type"],
        "status": row["status"],
        "cancelled_reservation_count": row["cancelled_reservation_count"],
    }
    return _audit(row, out)
