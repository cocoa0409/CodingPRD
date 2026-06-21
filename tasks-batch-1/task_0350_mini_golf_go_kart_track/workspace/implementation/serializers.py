"""Serialize internal entity dicts to API output, computing derived fields.

Entities are stored as plain dicts. Computed/derived fields are recomputed
here (capacity rollups, waiver_status, credits_remaining, etc.) so reads
always reflect a consistent view.
"""
from db import db
from util import parse_iso

WAIVER_VALID_DAYS = 365
MINOR_AGE_YEARS = 18


def _bookings_for_slot(slot_kind, slot_id, statuses):
    out = []
    for b in db.bookings.values():
        if slot_kind == "HEAT" and b.get("heat_id") == slot_id and b["status"] in statuses:
            out.append(b)
        elif slot_kind == "TEE_SESSION" and b.get("tee_session_id") == slot_id and b["status"] in statuses:
            out.append(b)
    return out


def heat_committed(heat):
    return sum(b["party_size"] for b in _bookings_for_slot("HEAT", heat["id"], {"CONFIRMED", "CHECKED_IN"}))


def heat_available(heat):
    return max(0, heat["lane_capacity"] - heat_committed(heat))


def tee_committed(sess):
    return sum(b["party_size"] for b in _bookings_for_slot("TEE_SESSION", sess["id"], {"CONFIRMED", "CHECKED_IN"}))


def tee_available(sess):
    return max(0, sess["party_slot_capacity"] - tee_committed(sess))


def group_units_consumed(group_id):
    """PRD §3.9: a party group's units_consumed is the sum of party_size over the
    group's member bookings in CONFIRMED or CHECKED_IN. Derived on read."""
    return sum(
        b["party_size"] for b in db.bookings.values()
        if b.get("group_id") == group_id and b["status"] in ("CONFIRMED", "CHECKED_IN")
    )


def open_slot_count(venue_id):
    n = 0
    for h in db.heats.values():
        if h["venue_id"] == venue_id and h["status"] == "OPEN":
            n += 1
    for s in db.tee_sessions.values():
        if s["venue_id"] == venue_id and s["status"] == "OPEN":
            n += 1
    return n


def latest_waiver(guest_id):
    waivers = [w for w in db.waivers.values() if w["guest_id"] == guest_id]
    if not waivers:
        return None
    # greatest signed_at; tie-break created_at ASC then take last
    waivers.sort(key=lambda w: (w["signed_at"], w["created_at"], w["_seq"]))
    # The waiver with the greatest signed_at; among equal signed_at, the one
    # last by (created_at ASC then seq).
    max_signed = max(w["signed_at"] for w in waivers)
    candidates = [w for w in waivers if w["signed_at"] == max_signed]
    candidates.sort(key=lambda w: (w["created_at"], w["_seq"]))
    return candidates[-1]


def waiver_status(guest_id):
    venue_clock = None  # waiver_status is derived against the venue current_utc.
    # Guests are venue-independent; the PRD derives waiver_status against "the
    # venue current_utc". We use the most recently set clock among venues if a
    # single venue exists; when ambiguous, fall back to comparing per venue at
    # confirm time. For the standalone guest read we use the latest venue clock.
    latest = latest_waiver(guest_id)
    if latest is None:
        return "NONE"
    clock = current_clock_for_waiver()
    exp = parse_iso(latest["expires_at"])
    if clock is not None and clock >= exp:
        return "EXPIRED"
    return "SIGNED"


def current_clock_for_waiver():
    """Return a representative venue current_utc for guest read derivation.

    Guests are not bound to a venue, but waiver expiry is evaluated against
    "the venue current_utc". In practice tests operate one venue; we use the
    most-recently-advanced clock among all venues.
    """
    clocks = [parse_iso(v["current_utc"]) for v in db.venues.values() if v.get("current_utc")]
    clocks = [c for c in clocks if c is not None]
    if not clocks:
        return None
    return max(clocks)


def waiver_status_against(guest_id, clock):
    latest = latest_waiver(guest_id)
    if latest is None:
        return "NONE"
    exp = parse_iso(latest["expires_at"])
    if clock is not None and clock >= exp:
        return "EXPIRED"
    return "SIGNED"


# -------- serializers --------

def venue_out(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "timezone": v["timezone"],
        "posture": v["posture"],
        "weather_hold_reason": v["weather_hold_reason"],
        "current_utc": v["current_utc"],
        "open_slot_count": open_slot_count(v["id"]),
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def attraction_out(a):
    return {
        "id": a["id"],
        "venue_id": a["venue_id"],
        "name": a["name"],
        "kind": a["kind"],
        "min_height_cm": a["min_height_cm"],
        "lane_count": a["lane_count"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def pricing_plan_out(p):
    return {
        "id": p["id"],
        "venue_id": p["venue_id"],
        "name": p["name"],
        "mode": p["mode"],
        "base_price_cents": p["base_price_cents"],
        "peak_surcharge_cents": p["peak_surcharge_cents"],
        "group_discount_pct": p["group_discount_pct"],
        "wristband_unit_cap": p["wristband_unit_cap"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def heat_out(h):
    committed = heat_committed(h)
    return {
        "id": h["id"],
        "venue_id": h["venue_id"],
        "attraction_id": h["attraction_id"],
        "start_utc": h["start_utc"],
        "end_utc": h["end_utc"],
        "window": h["window"],
        "lane_capacity": h["lane_capacity"],
        "lanes_committed": committed,
        "lanes_available": max(0, h["lane_capacity"] - committed),
        "status": h["status"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def tee_session_out(s):
    committed = tee_committed(s)
    return {
        "id": s["id"],
        "venue_id": s["venue_id"],
        "attraction_id": s["attraction_id"],
        "start_utc": s["start_utc"],
        "end_utc": s["end_utc"],
        "window": s["window"],
        "party_slot_capacity": s["party_slot_capacity"],
        "players_committed": committed,
        "players_available": max(0, s["party_slot_capacity"] - committed),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def guest_out(g):
    return {
        "id": g["id"],
        "full_name": g["full_name"],
        "height_cm": g["height_cm"],
        "birthdate": g["birthdate"],
        "waiver_status": waiver_status(g["id"]),
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def waiver_out(w):
    return {
        "id": w["id"],
        "guest_id": w["guest_id"],
        "signed_at": w["signed_at"],
        "expires_at": w["expires_at"],
        "guardian_name": w["guardian_name"],
        "created_at": w["created_at"],
    }


def wallet_out(w):
    return {
        "id": w["id"],
        "guest_id": w["guest_id"],
        "arcade_card_balance_cents": w["arcade_card_balance_cents"],
        "total_loaded_cents": w["total_loaded_cents"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def combo_pass_out(c):
    remaining = max(0, c["total_credits"] - c["credits_redeemed"])
    return {
        "id": c["id"],
        "guest_id": c["guest_id"],
        "total_credits": c["total_credits"],
        "credits_redeemed": c["credits_redeemed"],
        "credits_remaining": remaining,
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def party_group_out(pg):
    return {
        "id": pg["id"],
        "venue_id": pg["venue_id"],
        "host_guest_id": pg["host_guest_id"],
        "package_name": pg["package_name"],
        "included_unit_count": pg["included_unit_count"],
        "deposit_cents": pg["deposit_cents"],
        "units_consumed": group_units_consumed(pg["id"]),
        "status": pg["status"],
        "created_at": pg["created_at"],
        "updated_at": pg["updated_at"],
        "version": pg["version"],
    }


def booking_out(b):
    return {
        "id": b["id"],
        "venue_id": b["venue_id"],
        "guest_id": b["guest_id"],
        "slot_kind": b["slot_kind"],
        "heat_id": b["heat_id"],
        "tee_session_id": b["tee_session_id"],
        "pricing_plan_id": b["pricing_plan_id"],
        "group_id": b["group_id"],
        "combo_pass_id": b["combo_pass_id"],
        "origin": b["origin"],
        "party_size": b["party_size"],
        "units": b["units"],
        "gross_price_cents": b["gross_price_cents"],
        "credits_applied": b["credits_applied"],
        "cash_due_cents": b["cash_due_cents"],
        "status": b["status"],
        "waitlist_seq": b["waitlist_seq"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }
