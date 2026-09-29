"""Response serialisers -- one per entity, with the exact declared field set.

Numbers stored as Decimal are rendered as JSON numbers.  Timestamps are rendered
ISO 8601 UTC with exactly three fractional digits and date-typed fields as plain
YYYY-MM-DD strings (PRD 2.4).  Property.total_rooms, Property.
outstanding_incentive_points and RoomType.room_count are counted live from the
store, so they never drift from their definitions.
"""

from numeric import jsonnum
from store import common_out
from timeutil import format_iso_date, format_iso_datetime

import derive


def _ts(value):
    return format_iso_datetime(value)


def _d(value):
    return format_iso_date(value)


def property_out(store, row):
    out = common_out(row)
    out.update({
        "name": row["name"],
        "ordinance_profile": row["ordinance_profile"],
        "credit_minute_value": row["credit_minute_value"],
        "standard_shift_minutes": row["standard_shift_minutes"],
        "pre_post_shift_minutes": row["pre_post_shift_minutes"],
        "min_daily_paid_minutes": row["min_daily_paid_minutes"],
        "max_daily_credits": jsonnum(row["max_daily_credits"]),
        "max_daily_square_feet": row["max_daily_square_feet"],
        "laundry_sla_minutes": row["laundry_sla_minutes"],
        "laundry_capacity_sets": row["laundry_capacity_sets"],
        "reclean_threshold_score": jsonnum(row["reclean_threshold_score"]),
        "inspection_sample_rate": jsonnum(row["inspection_sample_rate"]),
        "probation_sample_rate": jsonnum(row["probation_sample_rate"]),
        "rest_buffer_minutes": row["rest_buffer_minutes"],
        "total_rooms": derive.property_total_rooms(store, row["id"]),
        "outstanding_incentive_points": derive.property_outstanding_incentive_points(
            store, row["id"]
        ),
    })
    return out


def room_type_out(store, row):
    out = common_out(row)
    out.update({
        "property_id": row["property_id"],
        "code": row["code"],
        "square_feet": row["square_feet"],
        "checkout_credits": jsonnum(row["checkout_credits"]),
        "stayover_credits": jsonnum(row["stayover_credits"]),
        "deep_clean_credits": jsonnum(row["deep_clean_credits"]),
        "linen_sets_per_room": row["linen_sets_per_room"],
        "room_count": derive.room_type_room_count(store, row["id"]),
    })
    return out


def room_out(store, row):
    out = common_out(row)
    out.update({
        "property_id": row["property_id"],
        "room_type_id": row["room_type_id"],
        "room_number": row["room_number"],
        "floor": row["floor"],
        "service_program": row["service_program"],
        "occupancy_state": row["occupancy_state"],
        "cleanliness_status": row["cleanliness_status"],
        "last_serviced_business_date": _d(row["last_serviced_business_date"]),
        "last_deep_cleaned_business_date": _d(row["last_deep_cleaned_business_date"]),
    })
    return out


def attendant_out(store, row):
    out = common_out(row)
    out.update({
        "property_id": row["property_id"],
        "employee_code": row["employee_code"],
        "full_name": row["full_name"],
        "seniority_date": _d(row["seniority_date"]),
        "hourly_rate_cents": row["hourly_rate_cents"],
        "can_inspect": row["can_inspect"],
        "restricted_duty": row["restricted_duty"],
        "status": row["status"],
        "quality_probation": row["quality_probation"],
        "lifetime_fail_count": row["lifetime_fail_count"],
    })
    return out


def forecast_day_out(store, row):
    out = common_out(row)
    out.update({
        "property_id": row["property_id"],
        "business_date": _d(row["business_date"]),
        "forecast_occupied_rooms": row["forecast_occupied_rooms"],
        "forecast_arrivals": row["forecast_arrivals"],
        "forecast_departures": row["forecast_departures"],
        "planned_deep_clean_rooms": row["planned_deep_clean_rooms"],
        "status": row["status"],
        "projected_required_credits": jsonnum(row["projected_required_credits"]),
        "required_attendants": row["required_attendants"],
        "allocated_credits_total": jsonnum(row["allocated_credits_total"]),
        "actual_reconciled_credits": jsonnum(row["actual_reconciled_credits"]),
        "credit_variance_pct": jsonnum(row["credit_variance_pct"]),
    })
    return out


def roster_out(store, row):
    out = common_out(row)
    out.update({
        "forecast_day_id": row["forecast_day_id"],
        "attendant_id": row["attendant_id"],
        "planned_start_at": _ts(row["planned_start_at"]),
        "status": row["status"],
        "compliance_state": row["compliance_state"],
        "waiver_state": row["waiver_state"],
        "waiver_requested_credits": jsonnum(row["waiver_requested_credits"]),
        "waiver_requested_by_user_id": row["waiver_requested_by_user_id"],
        "waiver_decided_by_user_id": row["waiver_decided_by_user_id"],
        "assigned_credits": jsonnum(row["assigned_credits"]),
        "assigned_square_feet": row["assigned_square_feet"],
        "effective_credit_cap": jsonnum(row["effective_credit_cap"]),
        "effective_sqft_cap": row["effective_sqft_cap"],
        "worked_minutes": row["worked_minutes"],
        "break_minutes": row["break_minutes"],
        "paid_minutes": row["paid_minutes"],
        "overtime_minutes": row["overtime_minutes"],
        "rooms_completed_gross": row["rooms_completed_gross"],
        "rooms_credited_net": row["rooms_credited_net"],
        "minutes_per_room_gross": jsonnum(row["minutes_per_room_gross"]),
        "minutes_per_room_net": jsonnum(row["minutes_per_room_net"]),
        "target_minutes_per_room": jsonnum(row["target_minutes_per_room"]),
        "productivity_flag": row["productivity_flag"],
        "required_inspection_samples": row["required_inspection_samples"],
        "inspections_completed": row["inspections_completed"],
        "base_wage_cents": row["base_wage_cents"],
        "ordinance_premium_cents": row["ordinance_premium_cents"],
        "total_labor_cost_cents": row["total_labor_cost_cents"],
    })
    return out


def assignment_out(store, row):
    out = common_out(row)
    out.update({
        "roster_id": row["roster_id"],
        "room_id": row["room_id"],
        "supersedes_assignment_id": row["supersedes_assignment_id"],
        "service_type": row["service_type"],
        "credits": jsonnum(row["credits"]),
        "reclean_generation": row["reclean_generation"],
        "status": row["status"],
        "started_at": _ts(row["started_at"]),
        "completed_at": _ts(row["completed_at"]),
        "actual_minutes": row["actual_minutes"],
        "square_feet_snapshot": row["square_feet_snapshot"],
        "linen_sets_debited": row["linen_sets_debited"],
        "roster_version_after": row["roster_version_after"],
    })
    return out


def inspection_out(store, row):
    # PRD 2.4: an Inspection is immutable -- it carries only id and created_at, and
    # neither updated_at nor version appears in its payload.
    out = common_out(row)
    out.update({
        "assignment_id": row["assignment_id"],
        "inspector_attendant_id": row["inspector_attendant_id"],
        "bathroom_points": row["bathroom_points"],
        "linen_points": row["linen_points"],
        "dust_points": row["dust_points"],
        "amenity_points": row["amenity_points"],
        "floor_points": row["floor_points"],
        "score_pct": jsonnum(row["score_pct"]),
        "critical_fail": row["critical_fail"],
        "result": row["result"],
        "generated_reclean_assignment_id": row["generated_reclean_assignment_id"],
    })
    return out


def linen_item_out(store, row):
    out = common_out(row)
    out.update({
        "property_id": row["property_id"],
        "linen_type": row["linen_type"],
        "total_owned_sets": row["total_owned_sets"],
        "on_hand_clean": row["on_hand_clean"],
        "in_laundry": row["in_laundry"],
        "soiled_queue": row["soiled_queue"],
        "par_required_sets": row["par_required_sets"],
        "coverage_ratio": jsonnum(row["coverage_ratio"]),
        "shortage_status": row["shortage_status"],
    })
    return out


def laundry_cycle_out(store, row):
    out = common_out(row)
    out.update({
        "linen_item_id": row["linen_item_id"],
        "batch_sets": row["batch_sets"],
        "dispatched_at": _ts(row["dispatched_at"]),
        "expected_return_at": _ts(row["expected_return_at"]),
        "returned_at": _ts(row["returned_at"]),
        "returned_sets": row["returned_sets"],
        "status": row["status"],
        "turnaround_minutes": row["turnaround_minutes"],
        "sla_breach": row["sla_breach"],
        "linen_item_version_after": row["linen_item_version_after"],
    })
    return out


def lost_found_out(store, row):
    out = common_out(row)
    out.update({
        "property_id": row["property_id"],
        "room_id": row["room_id"],
        "found_by_attendant_id": row["found_by_attendant_id"],
        "description": row["description"],
        "category": row["category"],
        "logged_at": _ts(row["logged_at"]),
        "storage_bin": row["storage_bin"],
        "stored_at": _ts(row["stored_at"]),
        "retention_days": row["retention_days"],
        "retention_expires_at": _ts(row["retention_expires_at"]),
        "status": row["status"],
        "claimant_name": row["claimant_name"],
        "claimant_contact": row["claimant_contact"],
        "proof_kind": row["proof_kind"],
        "claim_attempt_count": row["claim_attempt_count"],
        "denial_reason": row["denial_reason"],
        "tracking_code": row["tracking_code"],
    })
    return out


def enrollment_out(store, row):
    out = common_out(row)
    out.update({
        "room_id": row["room_id"],
        "reservation_code": row["reservation_code"],
        "program": row["program"],
        "nights": row["nights"],
        "points_per_skip": row["points_per_skip"],
        "skips_accrued": row["skips_accrued"],
        "points_accrued": row["points_accrued"],
        "status": row["status"],
    })
    return out
