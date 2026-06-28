"""Entity serializers — project stored records into API output shapes.

Field names and computed roll-ups follow SCAFFOLD §1.1 exactly. Internal-only
keys (e.g. _seq) are stripped.
"""

from db import db


def venue_out(v):
    return {
        "id": v["id"],
        "name": v["name"],
        "bay_count": v["bay_count"],
        "open_minute_of_day": v["open_minute_of_day"],
        "close_minute_of_day": v["close_minute_of_day"],
        "base_rate_cents_per_half_hour": v["base_rate_cents_per_half_hour"],
        "peak_demand_factor": v["peak_demand_factor"],
        "open_queue_length": _open_queue_length(v["id"]),
        "available_bay_count": _available_bay_count(v),
        "created_at": v["created_at"],
        "updated_at": v["updated_at"],
        "version": v["version"],
    }


def _open_queue_length(venue_id):
    return sum(
        1 for t in db.queue_tickets.values()
        if t["venue_id"] == venue_id and t["status"] == "WAITING"
    )


def _available_bay_count(v):
    """PRD §2.10: the venue's `bay_count` minus the number of its bays that are
    `OCCUPIED` or `OUT_OF_SERVICE`. The base is the declared `bay_count`, not the
    count of created Bay entities."""
    bays = [b for b in db.bays.values() if b["venue_id"] == v["id"]]
    occupied = sum(1 for b in bays if b["status"] in ("OCCUPIED", "OUT_OF_SERVICE"))
    return v["bay_count"] - occupied


def bay_out(b):
    return {
        "id": b["id"],
        "venue_id": b["venue_id"],
        "label": b["label"],
        "floor_level": b["floor_level"],
        "has_target_tech": b["has_target_tech"],
        "status": b["status"],
        "current_session_id": b["current_session_id"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def member_out(m):
    return {
        "id": m["id"],
        "email": m["email"],
        "full_name": m["full_name"],
        "tier": m["tier"],
        "wallet_balance_cents": m["wallet_balance_cents"],
        "loyalty_points": m["loyalty_points"],
        "pending_loyalty_points": m["pending_loyalty_points"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def game_card_out(c):
    return {
        "id": c["id"],
        "member_id": c["member_id"],
        "credits_total": c["credits_total"],
        "credits_remaining": c["credits_remaining"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def gift_card_out(g):
    return {
        "id": g["id"],
        "face_value_cents": g["face_value_cents"],
        "remaining_cents": g["remaining_cents"],
        "redeemed_total_cents": g["redeemed_total_cents"],
        "status": g["status"],
        "created_at": g["created_at"],
    }


def reservation_out(r):
    return {
        "id": r["id"],
        "venue_id": r["venue_id"],
        "bay_id": r["bay_id"],
        "member_id": r["member_id"],
        "start_utc": r["start_utc"],
        "end_utc": r["end_utc"],
        "day_type": r["day_type"],
        "time_band": r["time_band"],
        "pay_source": r["pay_source"],
        "quoted_price_cents": r["quoted_price_cents"],
        "status": r["status"],
        "hold_expires_utc": r["hold_expires_utc"],
        "charge_id": r["charge_id"],
        "no_show_fee_cents": r["no_show_fee_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def session_out(s):
    return {
        "id": s["id"],
        "bay_id": s["bay_id"],
        "member_id": s["member_id"],
        "reservation_id": s["reservation_id"],
        "queue_ticket_id": s["queue_ticket_id"],
        "play_status": s["play_status"],
        "billing_status": s["billing_status"],
        "total_score": s["total_score"],
        "shot_count": s["shot_count"],
        "shots": [{"seq": sh["seq"], "points": sh["points"]} for sh in s["shots"]],
        "charge_id": s["charge_id"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def event_out(e):
    return {
        "id": e["id"],
        "venue_id": e["venue_id"],
        "organizer_member_id": e["organizer_member_id"],
        "headcount_estimate": e["headcount_estimate"],
        "actual_attendee_count": e["actual_attendee_count"],
        "per_head_package_cents": e["per_head_package_cents"],
        "bay_block_cents": e["bay_block_cents"],
        "deposit_cents": e["deposit_cents"],
        "estimated_total_cents": e["estimated_total_cents"],
        "final_total_cents": e["final_total_cents"],
        "deposit_refund_cents": e["deposit_refund_cents"],
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def fb_tab_out(t):
    return {
        "id": t["id"],
        "session_id": t["session_id"],
        "event_package_id": t["event_package_id"],
        "line_items": [
            {"seq": li["seq"], "name": li["name"],
             "unit_price_cents": li["unit_price_cents"], "qty": li["qty"]}
            for li in t["line_items"]
        ],
        "subtotal_cents": t["subtotal_cents"],
        "gratuity_cents": t["gratuity_cents"],
        "tax_cents": t["tax_cents"],
        "total_cents": t["total_cents"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def queue_ticket_out(t):
    return {
        "id": t["id"],
        "venue_id": t["venue_id"],
        "member_id": t["member_id"],
        "game_card_id": t["game_card_id"],
        "party_size": t["party_size"],
        "position": _ticket_position(t),
        "status": t["status"],
        "assigned_bay_id": t["assigned_bay_id"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def _ticket_position(ticket):
    """1-based rank among the venue's WAITING tickets by created_at ASC.

    Non-WAITING tickets carry position 0 (they are not in the queue).
    """
    if ticket["status"] != "WAITING":
        return 0
    waiting = [
        t for t in db.queue_tickets.values()
        if t["venue_id"] == ticket["venue_id"] and t["status"] == "WAITING"
    ]
    waiting.sort(key=lambda t: (t["created_at"], t["_seq"]))
    for idx, t in enumerate(waiting, start=1):
        if t["id"] == ticket["id"]:
            return idx
    return 0


def lesson_out(le):
    return {
        "id": le["id"],
        "venue_id": le["venue_id"],
        "bay_id": le["bay_id"],
        "member_id": le["member_id"],
        "kind": le["kind"],
        "start_utc": le["start_utc"],
        "end_utc": le["end_utc"],
        "seats": le["seats"],
        "status": le["status"],
        "created_at": le["created_at"],
        "updated_at": le["updated_at"],
        "version": le["version"],
    }


def charge_out(c):
    return {
        "id": c["id"],
        "member_id": c["member_id"],
        "kind": c["kind"],
        "amount_cents": c["amount_cents"],
        "pay_source": c["pay_source"],
        "status": c["status"],
        "created_at": c["created_at"],
    }
