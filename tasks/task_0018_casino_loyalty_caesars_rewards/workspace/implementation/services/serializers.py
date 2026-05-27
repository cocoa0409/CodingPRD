"""Per-entity serializers — return JSON-ready dicts ordered by the SCAFFOLD field order."""


def member_view(m: dict) -> dict:
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "home_property_id": m["home_property_id"],
        "tier_status": m["tier_status"],
        "tier_credits_ytd": m["tier_credits_ytd"],
        "tier_credits_lifetime": m["tier_credits_lifetime"],
        "exclusion_status": m["exclusion_status"],
        "velocity_status": m["velocity_status"],
        "assigned_host_id": m.get("assigned_host_id"),
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def property_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "name": p["name"],
        "market_segment": p["market_segment"],
        "base_room_rate_cents": p["base_room_rate_cents"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def host_view(h: dict) -> dict:
    return {
        "id": h["id"],
        "employee_email": h["employee_email"],
        "home_property_id": h["home_property_id"],
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def gaming_session_view(g: dict) -> dict:
    return {
        "id": g["id"],
        "member_id": g["member_id"],
        "property_id": g["property_id"],
        "started_at": g["started_at"],
        "ended_at": g["ended_at"],
        "game_type": g["game_type"],
        "theoretical_loss_cents": g["theoretical_loss_cents"],
        "tier_credits_earned": g["tier_credits_earned"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def comp_room_booking_view(b: dict) -> dict:
    return {
        "id": b["id"],
        "member_id": b["member_id"],
        "property_id": b["property_id"],
        "check_in": b["check_in"],
        "check_out": b["check_out"],
        "nights": b["nights"],
        "provisional_rate_cents": b["provisional_rate_cents"],
        "final_rate_cents": b.get("final_rate_cents"),
        "total_charge_cents": b["total_charge_cents"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def self_exclusion_view(s: dict) -> dict:
    return {
        "id": s["id"],
        "member_id": s["member_id"],
        "requested_at": s["requested_at"],
        "exclusion_until": s["exclusion_until"],
        "reason": s["reason"],
        "status": s["status"],
        "created_at": s["created_at"],
    }


def host_assignment_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "member_id": a["member_id"],
        "host_id": a["host_id"],
        "assigned_by_user_id": a["assigned_by_user_id"],
        "approved_by_user_id": a.get("approved_by_user_id"),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def velocity_alert_view(v: dict) -> dict:
    return {
        "id": v["id"],
        "member_id": v["member_id"],
        "window_start": v["window_start"],
        "window_end": v["window_end"],
        "total_theoretical_loss_cents": v["total_theoretical_loss_cents"],
        "severity": v["severity"],
        "created_at": v["created_at"],
    }


def annual_reset_run_view(r: dict) -> dict:
    return {
        "id": r["id"],
        "reset_year": r["reset_year"],
        "scheduled_for": r["scheduled_for"],
        "status": r["status"],
        "members_reset_count": r["members_reset_count"],
        "tier_credits_lifetime_invariant_before_cents": r["tier_credits_lifetime_invariant_before_cents"],
        "tier_credits_lifetime_invariant_after_cents": r["tier_credits_lifetime_invariant_after_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }
