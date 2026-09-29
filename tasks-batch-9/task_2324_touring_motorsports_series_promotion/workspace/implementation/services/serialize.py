"""Representation builders — derived counters are reconciled at read time."""
from services import derive, flow


def _common(row, out):
    out["created_at"] = row["created_at"]
    out["updated_at"] = row["updated_at"]
    out["version"] = row["version"]
    return out


def season(row):
    allocated = derive.season_marketing_allocated(row)
    out = {
        "id": row["id"],
        "name": row["name"],
        "year": row["year"],
        "season_start_date": row["season_start_date"],
        "season_end_date": row["season_end_date"],
        "market_rotation_cooldown_days": row["market_rotation_cooldown_days"],
        "total_marketing_budget_cents": row["total_marketing_budget_cents"],
        "marketing_allocated_cents": allocated,
        "marketing_unallocated_cents": row["total_marketing_budget_cents"] - allocated,
        "booking_count": derive.season_booking_count(row),
        "settled_stop_count": derive.season_settled_stop_count(row),
        "season_net_cents": derive.season_net_cents(row),
        "status": row["status"],
    }
    return _common(row, out)


def venue(row):
    out = {
        "id": row["id"],
        "name": row["name"],
        "market_code": row["market_code"],
        "city": row["city"],
        "state_code": row["state_code"],
        "seat_capacity": row["seat_capacity"],
        "floor_type": row["floor_type"],
        "catch_fence_max_height_ft": row["catch_fence_max_height_ft"],
        "medical_bay_count": row["medical_bay_count"],
        "load_in_hours_required": row["load_in_hours_required"],
        "staging_bay_count": row["staging_bay_count"],
        "turnaround_hours": row["turnaround_hours"],
    }
    return _common(row, out)


def booking(row):
    out = {
        "id": row["id"],
        "season_id": row["season_id"],
        "venue_id": row["venue_id"],
        "tour_date": row["tour_date"],
        "rental_base_cents": row["rental_base_cents"],
        "revenue_share_pct": row["revenue_share_pct"],
        "per_ticket_facility_fee_cents": row["per_ticket_facility_fee_cents"],
        "load_in_start_utc": row["load_in_start_utc"],
        "tear_down_end_utc": row["tear_down_end_utc"],
        "state": row["state"],
        "negotiation_round": row["negotiation_round"],
        "terms_source": row["terms_source"],
        "last_counter_by_user_id": row["last_counter_by_user_id"],
        "confirmed_at": row["confirmed_at"],
        "withdraw_reason": row["withdraw_reason"],
    }
    return _common(row, out)


def stop(row):
    out = {
        "id": row["id"],
        "season_id": row["season_id"],
        "venue_booking_id": row["venue_booking_id"],
        "preceding_stop_id": row["preceding_stop_id"],
        "market_code": row["market_code"],
        "event_date": row["event_date"],
        "doors_open_utc": row["doors_open_utc"],
        "show_start_utc": row["show_start_utc"],
        "show_window_minutes": row["show_window_minutes"],
        "pit_party_price_cents": row["pit_party_price_cents"],
        "pit_party_capacity": row["pit_party_capacity"],
        "pit_party_sold_count": derive.stop_pit_party_sold_count(row),
        "sales_state": row["sales_state"],
        "safety_state": row["safety_state"],
        "readiness_posture": flow.posture(row),
        "expected_attendance": derive.stop_expected_attendance(row),
        "competition_segment_count": derive.stop_competition_segment_count(row),
        "run_order_end_offset_minutes": derive.stop_run_order_end_offset(row),
        "tickets_sold_count": derive.stop_tickets_sold_count(row),
        "gross_ticket_revenue_cents": derive.stop_gross_ticket_revenue(row),
        "addon_revenue_cents": derive.stop_addon_revenue(row),
        "facility_fee_collected_cents": derive.stop_facility_fee_collected(row),
        "marketing_spend_committed_cents": derive.stop_marketing_committed(row),
        "sponsorship_committed_cents": derive.stop_sponsorship_committed(row),
        "held_hospitality_seat_count": derive.stop_held_hospitality_seats(row),
        "haul_distance_miles": row["haul_distance_miles"],
        "cancel_reason": row["cancel_reason"],
    }
    return _common(row, out)


def competitor(row):
    out = {
        "id": row["id"],
        "team_name": row["team_name"],
        "driver_name": row["driver_name"],
        "home_market_code": row["home_market_code"],
        "vehicle_class": row["vehicle_class"],
        "entry_count": derive.competitor_entry_count(row),
    }
    return _common(row, out)


def entry(row):
    out = {
        "id": row["id"],
        "competitor_id": row["competitor_id"],
        "tour_stop_id": row["tour_stop_id"],
        "vehicle_number": row["vehicle_number"],
        "vehicle_weight_lbs": row["vehicle_weight_lbs"],
        "haul_distance_miles": row["haul_distance_miles"],
        "scheduled_arrival_utc": row["scheduled_arrival_utc"],
        "actual_arrival_utc": row["actual_arrival_utc"],
        "staging_bay_index": row["staging_bay_index"],
        "logistics_state": row["logistics_state"],
        "tech_status": row["tech_status"],
        "tech_attempt_count": derive.entry_tech_attempt_count(row),
        "failed_attempt_count": derive.entry_failed_attempt_count(row),
        "readiness_score": row["readiness_score"],
        "readiness_variant": row["readiness_variant"],
        "branding_slots_committed": derive.entry_branding_slots_committed(row),
    }
    return _common(row, out)


def inspection(row):
    return {
        "id": row["id"],
        "vehicle_entry_id": row["vehicle_entry_id"],
        "attempt_no": row["attempt_no"],
        "result": row["result"],
        "defect_severity": row["defect_severity"],
        "notes": row["notes"],
        "inspected_by_user_id": row["inspected_by_user_id"],
        "created_at": row["created_at"],
    }


def segment(row):
    out = {
        "id": row["id"],
        "tour_stop_id": row["tour_stop_id"],
        "featured_vehicle_entry_id": row["featured_vehicle_entry_id"],
        "segment_type": row["segment_type"],
        "title": row["title"],
        "run_order_position": row["run_order_position"],
        "duration_minutes": row["duration_minutes"],
        "start_offset_minutes": row["start_offset_minutes"],
        "end_offset_minutes": row["end_offset_minutes"],
        "reset_gap_minutes": row["reset_gap_minutes"],
    }
    return _common(row, out)


def tier(row):
    out = {
        "id": row["id"],
        "tour_stop_id": row["tour_stop_id"],
        "tier_code": row["tier_code"],
        "price_cents": row["price_cents"],
        "allotment": row["allotment"],
        "reserved_seat_count": derive.tier_reserved(row),
        "sold_seat_count": derive.tier_sold(row),
        "held_seat_count": derive.tier_held(row),
        "available_seat_count": derive.tier_available(row),
        "group_min_qty": row["group_min_qty"],
        "group_discount_pct": row["group_discount_pct"],
        "on_sale_start_utc": row["on_sale_start_utc"],
        "on_sale_end_utc": row["on_sale_end_utc"],
    }
    return _common(row, out)


def order(row):
    out = {
        "id": row["id"],
        "tour_stop_id": row["tour_stop_id"],
        "ticket_tier_id": row["ticket_tier_id"],
        "purchaser_name": row["purchaser_name"],
        "purchaser_email": row["purchaser_email"],
        "qty": row["qty"],
        "is_group": row["is_group"],
        "pit_party_addon_qty": row["pit_party_addon_qty"],
        "status": row["status"],
        "line_subtotal_cents": row["line_subtotal_cents"],
        "group_discount_cents": row["group_discount_cents"],
        "addon_subtotal_cents": row["addon_subtotal_cents"],
        "addon_discount_cents": row["addon_discount_cents"],
        "facility_fee_cents": row["facility_fee_cents"],
        "total_cents": row["total_cents"],
        "paid_at": row["paid_at"],
        "refunded_at": row["refunded_at"],
        "void_reason": row["void_reason"],
    }
    return _common(row, out)


def sponsor(row):
    out = {
        "id": row["id"],
        "company_name": row["company_name"],
        "category": row["category"],
        "contact_email": row["contact_email"],
        "exclusive_category": row["exclusive_category"],
    }
    return _common(row, out)


def activation(row):
    out = {
        "id": row["id"],
        "sponsor_id": row["sponsor_id"],
        "tour_stop_id": row["tour_stop_id"],
        "hospitality_tier_id": row["hospitality_tier_id"],
        "branded_vehicle_entry_id": row["branded_vehicle_entry_id"],
        "fee_cents": row["fee_cents"],
        "vehicle_branding_slots": row["vehicle_branding_slots"],
        "signage_units": row["signage_units"],
        "hospitality_seat_count": row["hospitality_seat_count"],
        "state": row["state"],
        "obligations_fulfilled_at": row["obligations_fulfilled_at"],
        "recognized_fee_cents": row["recognized_fee_cents"],
    }
    return _common(row, out)


def plan(row):
    out = {
        "id": row["id"],
        "tour_stop_id": row["tour_stop_id"],
        "state": row["state"],
        "barrier_linear_feet": row["barrier_linear_feet"],
        "catch_fence_height_ft": row["catch_fence_height_ft"],
        "medical_als_staff_count": row["medical_als_staff_count"],
        "medical_bls_staff_count": row["medical_bls_staff_count"],
        "ambulance_count": row["ambulance_count"],
        "emergency_access_lanes": row["emergency_access_lanes"],
        "required_als_staff_count": row["required_als_staff_count"],
        "required_bls_staff_count": row["required_bls_staff_count"],
        "required_ambulance_count": row["required_ambulance_count"],
        "required_catch_fence_height_ft": row["required_catch_fence_height_ft"],
        "required_emergency_access_lanes": row["required_emergency_access_lanes"],
        "required_barrier_linear_feet": row["required_barrier_linear_feet"],
        "safety_cost_cents": row["safety_cost_cents"],
        "authored_by_user_id": row["authored_by_user_id"],
        "certified_by_user_id": row["certified_by_user_id"],
        "return_count": row["return_count"],
        "return_reason": row["return_reason"],
    }
    return _common(row, out)


def allocation(row):
    out = {
        "id": row["id"],
        "tour_stop_id": row["tour_stop_id"],
        "channel": row["channel"],
        "amount_cents": row["amount_cents"],
        "state": row["state"],
        "released_at": row["released_at"],
    }
    return _common(row, out)


def settlement(row):
    out = {
        "id": row["id"],
        "tour_stop_id": row["tour_stop_id"],
        "state": row["state"],
        "variant": row["variant"],
        "prepared_by_user_id": row["prepared_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "ticket_revenue_cents": row["ticket_revenue_cents"],
        "addon_revenue_cents": row["addon_revenue_cents"],
        "facility_fee_cents": row["facility_fee_cents"],
        "sponsorship_revenue_cents": row["sponsorship_revenue_cents"],
        "marketing_spend_cents": row["marketing_spend_cents"],
        "safety_cost_cents": row["safety_cost_cents"],
        "purse_cents": row["purse_cents"],
        "rental_due_pre_credit_cents": row["rental_due_pre_credit_cents"],
        "coop_credit_pct": row["coop_credit_pct"],
        "coop_credit_cents": row["coop_credit_cents"],
        "venue_due_cents": row["venue_due_cents"],
        "collected_cash_cents": row["collected_cash_cents"],
        "net_to_promoter_cents": row["net_to_promoter_cents"],
        "payout_venue_cents": row["payout_venue_cents"],
        "payout_safety_cents": row["payout_safety_cents"],
        "payout_marketing_cents": row["payout_marketing_cents"],
        "payout_purse_cents": row["payout_purse_cents"],
        "promoter_remainder_cents": row["promoter_remainder_cents"],
        "shortfall_cents": row["shortfall_cents"],
        "profitability_margin_pct": row["profitability_margin_pct"],
        "dispute_reason": row["dispute_reason"],
        "dispute_count": row["dispute_count"],
    }
    return _common(row, out)
