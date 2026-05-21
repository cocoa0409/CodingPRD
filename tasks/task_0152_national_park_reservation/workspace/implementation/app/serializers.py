"""Resource serializers — produce JSON-safe dicts in fixed field order."""
from __future__ import annotations

from typing import Any, Dict


def _common_full(entity: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": entity["id"],
        "created_at": entity["created_at"],
        "updated_at": entity["updated_at"],
        "version": entity["version"],
    }


def _common_minimal(entity: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": entity["id"], "created_at": entity["created_at"]}


def serialize_park(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_full(p),
        "name": p["name"],
        "code": p["code"],
        "timezone": p["timezone"],
        "timed_entry_daily_capacity": p["timed_entry_daily_capacity"],
        "timed_entry_window_minutes": p["timed_entry_window_minutes"],
        "status": p["status"],
    }


def serialize_visitor(v: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_full(v),
        "email": v["email"],
        "full_name": v["full_name"],
        "wallet_balance_cents": v["wallet_balance_cents"],
        "lottery_strikes": v["lottery_strikes"],
    }


def serialize_pass(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_full(p),
        "visitor_id": p["visitor_id"],
        "pass_type": p["pass_type"],
        "serial": p["serial"],
        "valid_from": p["valid_from"],
        "valid_until": p["valid_until"],
        "status": p["status"],
    }


def serialize_campground(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_full(c),
        "park_id": c["park_id"],
        "name": c["name"],
        "standard_site_count": c["standard_site_count"],
        "group_site_count": c["group_site_count"],
        "nightly_standard_fee_cents": c["nightly_standard_fee_cents"],
        "nightly_group_fee_cents": c["nightly_group_fee_cents"],
        "max_consecutive_nights": c["max_consecutive_nights"],
        "waitlist_window_hours": c["waitlist_window_hours"],
    }


def serialize_zone(z: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_full(z),
        "park_id": z["park_id"],
        "name": z["name"],
        "nightly_quota_people": z["nightly_quota_people"],
        "ranger_buffer_minutes": z["ranger_buffer_minutes"],
        "per_party_fee_cents": z["per_party_fee_cents"],
    }


def serialize_lottery_permit(lp: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_full(lp),
        "park_id": lp["park_id"],
        "name": lp["name"],
        "lottery_open_at": lp["lottery_open_at"],
        "lottery_close_at": lp["lottery_close_at"],
        "draw_at": lp["draw_at"],
        "hike_date": lp["hike_date"],
        "daily_slot_count": lp["daily_slot_count"],
        "per_application_max_party": lp["per_application_max_party"],
        "application_fee_cents": lp["application_fee_cents"],
        "permit_fee_cents": lp["permit_fee_cents"],
        "status": lp["status"],
    }


def serialize_timed_entry(t: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_full(t),
        "park_id": t["park_id"],
        "visitor_id": t["visitor_id"],
        "vehicle_plate": t["vehicle_plate"],
        "entry_date_local": t["entry_date_local"],
        "window_start_local": t["window_start_local"],
        "window_end_local": t["window_end_local"],
        "pass_id": t.get("pass_id"),
        "entry_fee_cents": t["entry_fee_cents"],
        "status": t["status"],
        "held_until": t.get("held_until"),
    }


def serialize_campground_reservation(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_full(r),
        "campground_id": r["campground_id"],
        "visitor_id": r["visitor_id"],
        "site_kind": r["site_kind"],
        "party_size": r["party_size"],
        "check_in_date_local": r["check_in_date_local"],
        "check_out_date_local": r["check_out_date_local"],
        "nights": r["nights"],
        "nightly_rate_cents": r["nightly_rate_cents"],
        "total_fee_cents": r["total_fee_cents"],
        "status": r["status"],
        "held_until": r.get("held_until"),
        "refund_cents": r.get("refund_cents", 0),
    }


def serialize_waitlist_entry(w: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_minimal(w),
        "campground_id": w["campground_id"],
        "visitor_id": w["visitor_id"],
        "site_kind": w["site_kind"],
        "check_in_date_local": w["check_in_date_local"],
        "nights": w["nights"],
        "priority_score": w["priority_score"],
        "status": w["status"],
        "promoted_reservation_id": w.get("promoted_reservation_id"),
    }


def serialize_lottery_application(a: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_full(a),
        "lottery_permit_id": a["lottery_permit_id"],
        "visitor_id": a["visitor_id"],
        "party_size": a["party_size"],
        "rank_seed": a["rank_seed"],
        "application_fee_cents": a["application_fee_cents"],
        "status": a["status"],
        "award_expires_at": a.get("award_expires_at"),
    }


def serialize_backcountry_permit(b: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_full(b),
        "zone_id": b["zone_id"],
        "visitor_id": b["visitor_id"],
        "party_size": b["party_size"],
        "entry_datetime_local": b["entry_datetime_local"],
        "exit_datetime_local": b["exit_datetime_local"],
        "nights": b["nights"],
        "fee_cents": b["fee_cents"],
        "status": b["status"],
        "held_until": b.get("held_until"),
    }


def serialize_ledger_entry(l: Dict[str, Any]) -> Dict[str, Any]:
    return {
        **_common_minimal(l),
        "visitor_id": l["visitor_id"],
        "kind": l["kind"],
        "amount_cents": l["amount_cents"],
        "reference_kind": l["reference_kind"],
        "reference_id": l.get("reference_id"),
    }
