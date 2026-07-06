"""Serializers: produce the JSON-facing representation of each entity, with
derived fields computed at read time (PRD §2.4, §2.8, §3.1, §3.3, §3.8).
"""
import db


# ---------------------------------------------------------------------------
# Derived-field computations
# ---------------------------------------------------------------------------
def venue_open_attraction_count(venue_id):
    """Number of attractions under the venue whose status is OPEN (PRD §3.1)."""
    return sum(
        1 for a in db.attractions.values()
        if a["venue_id"] == venue_id and a["status"] == "OPEN"
    )


def venue_operational_state(venue):
    """Derive operational_state from weather_status (calc venue_operational_state)."""
    ws = venue["weather_status"]
    if ws == "SEVERE":
        return "SHUTDOWN"
    if ws == "ADVISORY":
        return "RESTRICTED"
    return "OPEN"


def slot_demand_ratio(slot):
    """(reserved_count + admitted_count) / capacity (PRD §2.8)."""
    cap = slot["capacity"]
    if cap == 0:
        return 0.0
    return (slot["reserved_count"] + slot["admitted_count"]) / cap


def waiver_effective_status(waiver):
    """SIGNED waivers become EXPIRED once the logical clock reaches/passes
    expires_at (PRD §3.3). REVOKED is a stored terminal state.
    """
    if waiver["status"] == "REVOKED":
        return "REVOKED"
    expires_at = db.parse_iso(waiver["expires_at"])
    if expires_at is not None and db.now() >= expires_at:
        return "EXPIRED"
    return "SIGNED"


def zone_staffing_status(zone):
    """STAFFED iff checked_in_count >= min_actors (PRD §3.8)."""
    return "STAFFED" if zone["checked_in_count"] >= zone["min_actors"] else "UNDERSTAFFED"


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def serialize_venue(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "timezone": v["timezone"],
        "weather_status": v["weather_status"],
        "operational_state": venue_operational_state(v),
        "open_attraction_count": venue_open_attraction_count(v["id"]),
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def serialize_attraction(a):
    return {
        "id": a["id"],
        "venue_id": a["venue_id"],
        "name": a["name"],
        "min_age": a["min_age"],
        "scare_level": a["scare_level"],
        "throughput_per_slot": a["throughput_per_slot"],
        "status": a["status"],
        "requires_waiver": a["requires_waiver"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_time_slot(s):
    return {
        "id": s["id"],
        "attraction_id": s["attraction_id"],
        "window_start": s["window_start"],
        "window_end": s["window_end"],
        "capacity": s["capacity"],
        "reserved_count": s["reserved_count"],
        "admitted_count": s["admitted_count"],
        "demand_ratio": slot_demand_ratio(s),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_pricing_rule(r):
    return {
        "id": r["id"],
        "attraction_id": r["attraction_id"],
        "tier": r["tier"],
        "base_price_cents": r["base_price_cents"],
        "low_demand_max_ratio": r["low_demand_max_ratio"],
        "high_demand_min_ratio": r["high_demand_min_ratio"],
        "mid_surge_pct": r["mid_surge_pct"],
        "high_surge_pct": r["high_surge_pct"],
        "created_at": r["created_at"],
    }


def serialize_guest(g):
    return {
        "id": g["id"],
        "full_name": g["full_name"],
        "age": g["age"],
        "email": g["email"],
        "wallet_credit_cents": g["wallet_credit_cents"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def serialize_waiver(w):
    return {
        "id": w["id"],
        "guest_id": w["guest_id"],
        "max_scare_level": w["max_scare_level"],
        "signed_at": w["signed_at"],
        "expires_at": w["expires_at"],
        "status": waiver_effective_status(w),
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_reservation(r):
    return {
        "id": r["id"],
        "venue_id": r["venue_id"],
        "guest_id": r["guest_id"],
        "pass_id": r["pass_id"],
        "party_size": r["party_size"],
        "entry_status": r["entry_status"],
        "payment_status": r["payment_status"],
        "subtotal_cents": r["subtotal_cents"],
        "discount_cents": r["discount_cents"],
        "total_cents": r["total_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_ticket(t):
    return {
        "id": t["id"],
        "reservation_id": t["reservation_id"],
        "time_slot_id": t["time_slot_id"],
        "guest_age": t["guest_age"],
        "max_scare_level": t["max_scare_level"],
        "tier": t["tier"],
        "price_cents": t["price_cents"],
        "queue_priority": t["queue_priority"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_pass_product(p):
    return {
        "id": p["id"],
        "venue_id": p["venue_id"],
        "kind": p["kind"],
        "price_cents": p["price_cents"],
        "discount_pct": p["discount_pct"],
        "min_party": p["min_party"],
        "max_redemptions": p["max_redemptions"],
        "created_at": p["created_at"],
    }


def serialize_pass(p):
    return {
        "id": p["id"],
        "pass_product_id": p["pass_product_id"],
        "guest_id": p["guest_id"],
        "redemptions_used": p["redemptions_used"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_scare_zone(z):
    return {
        "id": z["id"],
        "attraction_id": z["attraction_id"],
        "name": z["name"],
        "min_actors": z["min_actors"],
        "checked_in_count": z["checked_in_count"],
        "staffing_status": zone_staffing_status(z),
        "created_at": z["created_at"],
        "updated_at": z["updated_at"],
        "version": z["version"],
    }


def serialize_actor_shift(s):
    return {
        "id": s["id"],
        "scare_zone_id": s["scare_zone_id"],
        "actor_user_id": s["actor_user_id"],
        "shift_start": s["shift_start"],
        "shift_end": s["shift_end"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_closure(c):
    return {
        "id": c["id"],
        "attraction_id": c["attraction_id"],
        "reason": c["reason"],
        "opened_reservation_refunds": c["opened_reservation_refunds"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }
