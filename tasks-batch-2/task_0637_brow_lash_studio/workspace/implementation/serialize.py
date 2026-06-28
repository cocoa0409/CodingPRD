"""Serialize internal records into output JSON.

Internal records carry tz-aware datetimes for datetime fields and a private
_seq. Output replaces datetimes with ISO 8601 UTC (3 fractional digits) strings
and drops private keys. Computed fields are reconciled at read time.
"""
from clock import to_iso8601_millis
from db import store
from services import credits, derive


def _dt(v):
    return to_iso8601_millis(v) if v is not None else None


def studio_out(s):
    return {
        "id": s["id"],
        "name": s["name"],
        "deposit_rate_pct": s["deposit_rate_pct"],
        "late_cancel_cutoff_hours": s["late_cancel_cutoff_hours"],
        "noshow_strike_window_days": s["noshow_strike_window_days"],
        "noshow_strike_threshold": s["noshow_strike_threshold"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def service_type_out(st):
    return {
        "id": st["id"],
        "studio_id": st["studio_id"],
        "code": st["code"],
        "name": st["name"],
        "duration_minutes": st["duration_minutes"],
        "base_price_cents": st["base_price_cents"],
        "credit_cost": st["credit_cost"],
        "category": st["category"],
        "requires_patch_test": st["requires_patch_test"],
        "active": st["active"],
        "created_at": st["created_at"],
        "updated_at": st["updated_at"],
        "version": st["version"],
    }


def membership_plan_out(p):
    return {
        "id": p["id"],
        "studio_id": p["studio_id"],
        "tier": p["tier"],
        "monthly_credit_allotment": p["monthly_credit_allotment"],
        "monthly_fee_cents": p["monthly_fee_cents"],
        "rollover_cap_multiplier": p["rollover_cap_multiplier"],
        "loyalty_discount_pct": p["loyalty_discount_pct"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def lash_tech_out(t):
    return {
        "id": t["id"],
        "studio_id": t["studio_id"],
        "full_name": t["full_name"],
        "skill_level": t["skill_level"],
        "station_number": t["station_number"],
        "station_sanitized_through_utc": _dt(derive.station_sanitized_through_utc(t["id"])),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def member_out(m):
    anchor = derive.last_premium_completed_utc(m)
    return {
        "id": m["id"],
        "studio_id": m["studio_id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "noshow_strike_count": derive.noshow_strike_count(m),
        "last_premium_completed_utc": _dt(anchor),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def membership_out(ms):
    return {
        "id": ms["id"],
        "member_id": ms["member_id"],
        "plan_id": ms["plan_id"],
        "credit_balance": credits.credit_balance(ms["id"]),
        "cycle_anchor_utc": _dt(ms["cycle_anchor_utc"]),
        "cycles_closed": ms["cycles_closed"],
        "status": ms["status"],
        "created_at": ms["created_at"],
        "updated_at": ms["updated_at"],
        "version": ms["version"],
    }


def patch_test_out(pt):
    return {
        "id": pt["id"],
        "member_id": pt["member_id"],
        "administered_utc": _dt(pt["administered_utc"]),
        "valid_through_utc": _dt(pt["valid_through_utc"]),
        "consent_signed": pt["consent_signed"],
        "status": derive.effective_patch_test_status(pt),
        "created_at": pt["created_at"],
        "updated_at": pt["updated_at"],
        "version": pt["version"],
    }


def appointment_out(a):
    return {
        "id": a["id"],
        "studio_id": a["studio_id"],
        "member_id": a["member_id"],
        "service_type_id": a["service_type_id"],
        "membership_id": a["membership_id"],
        "lash_tech_id": a["lash_tech_id"],
        "recurring_schedule_id": a["recurring_schedule_id"],
        "start_utc": _dt(a["start_utc"]),
        "end_utc": _dt(a["end_utc"]),
        "pay_with_credits": a["pay_with_credits"],
        "deposit_cents": a["deposit_cents"],
        "credits_charged": a["credits_charged"],
        "deposit_forfeited_cents": a["deposit_forfeited_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def retail_order_out(o):
    return {
        "id": o["id"],
        "member_id": o["member_id"],
        "appointment_id": o["appointment_id"],
        "lines": o["lines"],
        "subtotal_cents": o["subtotal_cents"],
        "peak_surcharge_cents": o["peak_surcharge_cents"],
        "total_cents": o["total_cents"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def recurring_schedule_out(r):
    return {
        "id": r["id"],
        "member_id": r["member_id"],
        "service_type_id": r["service_type_id"],
        "cadence_days": r["cadence_days"],
        "first_start_utc": _dt(r["first_start_utc"]),
        "next_due_utc": _dt(r["next_due_utc"]),
        "spawned_count": r["spawned_count"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def sanitation_log_out(s):
    return {
        "id": s["id"],
        "lash_tech_id": s["lash_tech_id"],
        "performed_by_user_id": s["performed_by_user_id"],
        "sanitized_at_utc": _dt(s["sanitized_at_utc"]),
        "valid_through_utc": _dt(s["valid_through_utc"]),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def credit_ledger_entry_out(e):
    return {
        "id": e["id"],
        "membership_id": e["membership_id"],
        "delta": e["delta"],
        "reason": e["reason"],
        "source_ref_id": e["source_ref_id"],
        "created_at": e["created_at"],
    }
