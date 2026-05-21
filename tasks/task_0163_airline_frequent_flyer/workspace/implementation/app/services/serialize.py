"""Serialization helpers — turn internal dicts into API payloads.

These helpers also handle on-the-fly recomputations (e.g. Flight.load_factor,
Flight.upgrade_inventory_*, Member.points_balance and Member.projected_tier_eoy)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from ..store import store
from ..timeutil import iso_now, parse_iso, day_of_year
from . import tier as tier_svc


def _ts(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        return iso_now(value)
    return value


def serialize_member(m: dict, now: datetime | None = None) -> dict:
    """Return the public representation of a Member, recomputing balance/projection."""
    if now is None:
        from ..timeutil import clock
        now = clock.now()
    balance = compute_points_balance(m["id"], now)
    cur_year = now.year
    qs, qp = compute_qualifying_ytd(m["id"], cur_year)
    projected = tier_svc.projected_tier_eoy(qs, qp, now)
    out = {
        "id": m["id"],
        "email": m["email"],
        "display_name": m["display_name"],
        "home_region": m["home_region"],
        "status": m["status"],
        "tier": m["tier"],
        "tier_source": m["tier_source"],
        "tier_valid_through_year": m.get("tier_valid_through_year"),
        "points_balance": balance,
        "current_year_qualifying_segments": qs,
        "current_year_qualifying_points": qp,
        "current_membership_year": cur_year,
        "last_activity_at": _ts(m.get("last_activity_at")),
        "projected_tier_eoy": projected,
        "created_at": _ts(m["created_at"]),
        "updated_at": _ts(m["updated_at"]),
        "version": m["version"],
    }
    return out


def serialize_flight(f: dict) -> dict:
    load_factor = compute_load_factor(f)
    inv_b = compute_upgrade_inventory(f, "BUSINESS")
    inv_f = compute_upgrade_inventory(f, "FIRST")
    out = {
        "id": f["id"],
        "flight_number": f["flight_number"],
        "origin": f["origin"],
        "destination": f["destination"],
        "distance_miles": f["distance_miles"],
        "route_region": f["route_region"],
        "departure_at": _ts(f["departure_at"]),
        "status": f["status"],
        "base_fare_cents": f["base_fare_cents"],
        "capacity_economy": f["capacity_economy"],
        "capacity_business": f["capacity_business"],
        "capacity_first": f["capacity_first"],
        "upgrade_inventory_business": inv_b,
        "upgrade_inventory_first": inv_f,
        "load_factor": round(load_factor, 4),
        "created_at": _ts(f["created_at"]),
        "updated_at": _ts(f["updated_at"]),
        "version": f["version"],
    }
    return out


def serialize_segment(s: dict) -> dict:
    return {
        "id": s["id"],
        "member_id": s["member_id"],
        "flight_id": s["flight_id"],
        "booked_cabin": s["booked_cabin"],
        "flown_cabin": s.get("flown_cabin"),
        "status": s["status"],
        "flown_year": s.get("flown_year"),
        "qualifying_points_earned": s.get("qualifying_points_earned"),
        "created_at": _ts(s["created_at"]),
        "updated_at": _ts(s["updated_at"]),
        "version": s["version"],
    }


def serialize_points_transaction(t: dict) -> dict:
    out = {
        "id": t["id"],
        "member_id": t["member_id"],
        "created_at": _ts(t["created_at"]),
        "kind": t["kind"],
        "points_delta": t["points_delta"],
        "qualifying_points": t.get("qualifying_points", 0),
        "posted_at": _ts(t["posted_at"]),
        "expires_at": _ts(t.get("expires_at")),
        "remaining_unredeemed": t.get("remaining_unredeemed"),
        "related_segment_id": t.get("related_segment_id"),
        "related_booking_id": t.get("related_booking_id"),
        "related_certificate_id": t.get("related_certificate_id"),
        "counterparty_member_id": t.get("counterparty_member_id"),
        "idempotency_key": t.get("idempotency_key"),
    }
    return out


def serialize_upgrade_request(u: dict) -> dict:
    return {
        "id": u["id"],
        "member_id": u["member_id"],
        "flight_segment_id": u["flight_segment_id"],
        "flight_id": u["flight_id"],
        "target_cabin": u["target_cabin"],
        "points_offered": u["points_offered"],
        "status": u["status"],
        "waitlist_join_seq": u["waitlist_join_seq"],
        "priority_score": u["priority_score"],
        "held_points": u.get("held_points", 0),
        "created_at": _ts(u["created_at"]),
        "updated_at": _ts(u["updated_at"]),
        "version": u["version"],
    }


def serialize_award_booking(b: dict) -> dict:
    return {
        "id": b["id"],
        "member_id": b["member_id"],
        "flight_id": b["flight_id"],
        "cabin": b["cabin"],
        "pricing_mode": b["pricing_mode"],
        "points_cost": b["points_cost"],
        "cash_taxes_cents": b.get("cash_taxes_cents", 0),
        "status": b["status"],
        "held_until": _ts(b["held_until"]),
        "companion_certificate_id": b.get("companion_certificate_id"),
        "linked_segment_id": b.get("linked_segment_id"),
        "created_at": _ts(b["created_at"]),
        "updated_at": _ts(b["updated_at"]),
        "version": b["version"],
    }


def serialize_certificate(c: dict) -> dict:
    return {
        "id": c["id"],
        "member_id": c["member_id"],
        "status": c["status"],
        "issued_at": _ts(c["issued_at"]),
        "expires_at": _ts(c["expires_at"]),
        "reserved_for_booking_id": c.get("reserved_for_booking_id"),
        "used_on_booking_id": c.get("used_on_booking_id"),
        "issued_reason": c["issued_reason"],
        "created_at": _ts(c["created_at"]),
        "updated_at": _ts(c["updated_at"]),
        "version": c["version"],
    }


def serialize_status_match(r: dict) -> dict:
    return {
        "id": r["id"],
        "member_id": r["member_id"],
        "competitor_program": r["competitor_program"],
        "competitor_tier": r["competitor_tier"],
        "evidence_url": r["evidence_url"],
        "status": r["status"],
        "granted_tier": r.get("granted_tier"),
        "granted_at": _ts(r.get("granted_at")),
        "activated_at": _ts(r.get("activated_at")),
        "expires_at": _ts(r.get("expires_at")),
        "cooling_off_until": _ts(r.get("cooling_off_until")),
        "created_at": _ts(r["created_at"]),
        "updated_at": _ts(r["updated_at"]),
        "version": r["version"],
    }


def serialize_membership_year(y: dict) -> dict:
    return {
        "id": y["id"],
        "member_id": y["member_id"],
        "year": y["year"],
        "qualifying_segments_final": y["qualifying_segments_final"],
        "qualifying_points_final": y["qualifying_points_final"],
        "starting_tier": y["starting_tier"],
        "awarded_tier": y["awarded_tier"],
        "created_at": _ts(y["created_at"]),
    }


# -------------------------------------------------------------------------
# Computed-field helpers (live recomputation).
# -------------------------------------------------------------------------

def compute_points_balance(member_id: str, now: datetime) -> int:
    """Member.points_balance = signed sum of every points_delta with posted_at <= now."""
    total = 0
    for t in store.points_transactions.values():
        if t["member_id"] != member_id:
            continue
        posted = t["posted_at"]
        if posted is None:
            continue
        if posted <= now:
            total += t["points_delta"]
    return total


def compute_qualifying_ytd(member_id: str, year: int) -> tuple[int, int]:
    """(qualifying_segments, qualifying_points) for current year — based on FLOWN segments
    with flown_year == year. PRD §3.1: rollover "resets the two year-scoped counters
    to zero", so any segment whose flown was counted in a prior rollover snapshot for
    this member is excluded by comparing against Member.qualifying_counter_reset_at."""
    m = store.members.get(member_id)
    reset_at = m.get("qualifying_counter_reset_at") if m else None
    segs = 0
    pts = 0
    for s in store.segments.values():
        if s["member_id"] != member_id:
            continue
        if s["status"] == "FLOWN" and s.get("flown_year") == year:
            # Exclude segments whose FLOWN was committed before the last rollover reset.
            if reset_at is not None and s["updated_at"] <= reset_at:
                continue
            segs += 1
            pts += s.get("qualifying_points_earned", 0) or 0
    return segs, pts


def compute_load_factor(flight: dict) -> float:
    total_cap = (
        flight["capacity_economy"]
        + flight["capacity_business"]
        + flight["capacity_first"]
    )
    if total_cap <= 0:
        return 0.0
    confirmed = 0
    for s in store.segments.values():
        if s["flight_id"] == flight["id"] and s["status"] in ("BOOKED", "FLOWN"):
            confirmed += 1
    lf = confirmed / total_cap
    if lf < 0.0:
        lf = 0.0
    if lf > 1.0:
        lf = 1.0
    return lf


def compute_upgrade_inventory(flight: dict, cabin: str) -> int:
    """upgrade_inventory_{cabin} = capacity_{cabin}
        - count(BOOKED/FLOWN segments with booked_cabin == cabin)
        - count(CONFIRMED UpgradeRequests with target_cabin == cabin) for this flight."""
    cap_field = {
        "BUSINESS": "capacity_business",
        "FIRST": "capacity_first",
        "ECONOMY": "capacity_economy",
    }[cabin]
    cap = flight[cap_field]
    booked = 0
    for s in store.segments.values():
        if s["flight_id"] != flight["id"]:
            continue
        if s["status"] not in ("BOOKED", "FLOWN"):
            continue
        if s["booked_cabin"] == cabin:
            booked += 1
    upgraded_in = 0
    for u in store.upgrade_requests.values():
        if u["flight_id"] != flight["id"]:
            continue
        if u["status"] != "CONFIRMED":
            continue
        if u["target_cabin"] == cabin:
            upgraded_in += 1
    return cap - booked - upgraded_in
