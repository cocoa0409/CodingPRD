"""Entity serializers — field names per SCAFFOLD §1.1. Common fields
(id/created_at/updated_at/version) per PRD §2.4; AsRunEntry is the deliberate
exception (id + created_at only, append-only)."""

from helpers import fmt_ts


def _common(rec):
    return {
        "id": rec["id"],
        "created_at": fmt_ts(rec["created_at"]),
        "updated_at": fmt_ts(rec["updated_at"]),
        "version": rec["version"],
    }


def ser_advertiser(r):
    return {
        **_common(r),
        "name": r["name"],
        "agency_name": r["agency_name"],
        "product_category": r["product_category"],
        "credit_limit_cents": r["credit_limit_cents"],
    }


def ser_program(r):
    return {
        **_common(r),
        "title": r["title"],
        "daypart_code": r["daypart_code"],
        "airs_weekday": r["airs_weekday"],
        "start_time_local": r["start_time_local"],
        "duration_minutes": r["duration_minutes"],
        "rating_estimate": r["rating_estimate"],
        "is_political_window": r["is_political_window"],
    }


def ser_avail_week(r):
    return {
        **_common(r),
        "week_start_date": r["week_start_date"],
        "status": r["status"],
    }


def ser_avail_unit(r):
    return {
        **_common(r),
        "avail_week_id": r["avail_week_id"],
        "program_id": r["program_id"],
        "air_date": r["air_date"],
        "break_position": r["break_position"],
        "total_seconds": r["total_seconds"],
        "reserved_political_seconds": r["reserved_political_seconds"],
        "booked_commercial_seconds": r["booked_commercial_seconds"],
        "booked_political_seconds": r["booked_political_seconds"],
    }


def ser_order(r):
    return {
        **_common(r),
        "advertiser_id": r["advertiser_id"],
        "flight_start_date": r["flight_start_date"],
        "flight_end_date": r["flight_end_date"],
        "status": r["status"],
        "gross_budget_cents": r["gross_budget_cents"],
        "revision_no": r["revision_no"],
    }


def ser_order_line(r):
    return {
        **_common(r),
        "order_id": r["order_id"],
        "program_id": r["program_id"],
        "weeks_requested": r["weeks_requested"],
        "spots_per_week": r["spots_per_week"],
        "spot_length_seconds": r["spot_length_seconds"],
        "gross_rate_cents": r["gross_rate_cents"],
        "guaranteed_rating": r["guaranteed_rating"],
        "status": r["status"],
    }


def ser_copy_instruction(r):
    return {
        **_common(r),
        "advertiser_id": r["advertiser_id"],
        "length_seconds": r["length_seconds"],
        "rotation_weight": r["rotation_weight"],
        "status": r["status"],
    }


def ser_spot(r):
    return {
        **_common(r),
        "order_line_id": r["order_line_id"],
        "avail_unit_id": r["avail_unit_id"],
        "copy_instruction_id": r["copy_instruction_id"],
        "spot_class": r["spot_class"],
        "scheduled_air_date": r["scheduled_air_date"],
        "status": r["status"],
        "preempt_reason": r["preempt_reason"],
        "make_good_of_spot_id": r["make_good_of_spot_id"],
    }


def ser_log_day(r):
    return {
        **_common(r),
        "avail_week_id": r["avail_week_id"],
        "log_date": r["log_date"],
        "status": r["status"],
    }


def ser_as_run_entry(r):
    # Append-only reconciliation record: id + created_at only (PRD §2.4).
    return {
        "id": r["id"],
        "created_at": fmt_ts(r["created_at"]),
        "log_day_id": r["log_day_id"],
        "spot_id": r["spot_id"],
        "aired": r["aired"],
        "actual_rating": r["actual_rating"],
    }
