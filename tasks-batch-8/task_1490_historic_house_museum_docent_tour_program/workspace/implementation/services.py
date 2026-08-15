"""Business logic: lookups, serializers, computed fields, cascades, calculations.

All derived figures (seat pools, revenue, staffing, readiness scores) are
recomputed live from the store on every read/mutation (PRD 2.10); only
slot.capacity and booking price fields are creation-time snapshots.
"""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import DB, fmt_dt, fmt_ts, now, today
from errors import ApiError
from util import parse_ymd

# ---------------------------------------------------------------------------
# Generic record helpers
# ---------------------------------------------------------------------------


def stamp(rec):
    """Set created_at/updated_at/version on a freshly created record."""
    ts = fmt_ts(now())
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1


def touch(rec):
    """Register a mutation: bump version and updated_at (PRD 2.4)."""
    rec["updated_at"] = fmt_ts(now())
    rec["version"] += 1


def lookup(store, rid):
    rec = DB[store].get(rid) if isinstance(rid, str) else None
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")
    return rec


def sort_items(items):
    """Default list sort: created_at ascending (insertion order breaks ties)."""
    return sorted(items, key=lambda r: r["created_at"])


# ---------------------------------------------------------------------------
# Live aggregates on TourSlot (PRD 2.10, 3.4, 3.6)
# ---------------------------------------------------------------------------


def slot_bookings(slot_id):
    return [b for b in DB["bookings"].values() if b["slot_id"] == slot_id]


def slot_shifts(slot_id):
    return [s for s in DB["shifts"].values() if s["slot_id"] == slot_id]


def seats_reserved(slot):
    return sum(
        b["party_size"] for b in slot_bookings(slot["id"]) if b["status"] == "RESERVED"
    )


def seats_confirmed(slot):
    return sum(
        b["party_size"] for b in slot_bookings(slot["id"]) if b["status"] == "CONFIRMED"
    )


def seats_available(slot):
    return max(0, slot["capacity"] - seats_reserved(slot) - seats_confirmed(slot))


def revenue_committed(slot):
    return sum(
        b["total_price_cents"]
        for b in slot_bookings(slot["id"])
        if b["status"] == "CONFIRMED"
    )


def revenue_projected(slot):
    committed = revenue_committed(slot)
    reserved_sum = sum(
        b["total_price_cents"]
        for b in slot_bookings(slot["id"])
        if b["status"] == "RESERVED"
    )
    uplift = int(
        (Decimal(reserved_sum) * Decimal("0.8")).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )
    return committed + uplift


def staffing_status(slot):
    shifts = slot_shifts(slot["id"])
    if any(s["shift_role"] == "LEAD" and s["status"] == "CONFIRMED" for s in shifts):
        return "STAFFED"
    if any(s["shift_role"] == "LEAD" and s["status"] == "ASSIGNED" for s in shifts):
        return "NEEDS_LEAD"
    return "UNSTAFFED"


def refresh_full_open(slot):
    """System OPEN<->FULL flip driven by seats_available (PRD 3.4)."""
    if slot["status"] == "OPEN" and seats_available(slot) == 0:
        slot["status"] = "FULL"
        touch(slot)
    elif slot["status"] == "FULL" and seats_available(slot) > 0:
        slot["status"] = "OPEN"
        touch(slot)


# ---------------------------------------------------------------------------
# Docent readiness scores (calculation: docent_readiness_score)
# ---------------------------------------------------------------------------


def readiness_score(docent, w_hours, w_shadow, w_quiz):
    hours_term = Decimal(min(docent["training_hours"], 30)) / Decimal(30)
    shadow_term = Decimal(min(docent["shadow_tours_completed"], 5)) / Decimal(5)
    quiz_term = Decimal(docent["quiz_score"] or 0) / Decimal(100)
    total = Decimal(100) * (
        w_hours * hours_term + w_shadow * shadow_term + w_quiz * quiz_term
    )
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def readiness_standard(docent):
    return readiness_score(docent, Decimal("0.3"), Decimal("0.3"), Decimal("0.4"))


def readiness_apprentice(docent):
    return readiness_score(docent, Decimal("0.5"), Decimal("0.4"), Decimal("0.1"))


# ---------------------------------------------------------------------------
# Room occupancy windows (calculation: room_occupancy_windows)
# ---------------------------------------------------------------------------


def room_windows(route, start_dt, end_dt):
    """Per-room half-open occupation windows for a slot of this route."""
    room_ids = route["room_ids"]
    n = len(room_ids)
    per = route["duration_minutes"] // n
    wins = {}
    for i, rid in enumerate(room_ids):
        w_start = start_dt + timedelta(minutes=per * i)
        w_end = end_dt if i == n - 1 else start_dt + timedelta(minutes=per * (i + 1))
        wins[rid] = (w_start, w_end)
    return wins


def check_occupancy_conflict(route, start_dt, end_dt, exclude_slot_id=None):
    cand = room_windows(route, start_dt, end_dt)
    for other in DB["slots"].values():
        if other["id"] == exclude_slot_id:
            continue
        if other["status"] not in ("SCHEDULED", "OPEN", "FULL", "IN_PROGRESS"):
            continue
        oroute = DB["routes"].get(other["route_id"])
        if oroute is None:
            continue
        shared = set(route["room_ids"]) & set(oroute["room_ids"])
        if not shared:
            continue
        owins = room_windows(oroute, other["_start_dt"], other["_end_dt"])
        for rid in shared:
            a_start, a_end = cand[rid]
            b_start, b_end = owins[rid]
            # Half-open overlap: touching endpoints are NOT a conflict.
            if a_start < b_end and b_start < a_end:
                raise ApiError(
                    "ERR_ROOM_OCCUPANCY_CONFLICT",
                    409,
                    "Room occupation window collides with another slot",
                )


def check_shift_overlap(docent_id, cand_start, cand_end, exclude_slot_id=None):
    """Thirty-minute-buffer double-booking guard (PRD 3.4).

    The docent's existing non-terminal shift windows, each padded by 30
    minutes on both sides, must not overlap the candidate slot window.
    """
    buffer = timedelta(minutes=30)
    for sh in DB["shifts"].values():
        if sh["docent_id"] != docent_id:
            continue
        if sh["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        if exclude_slot_id is not None and sh["slot_id"] == exclude_slot_id:
            continue
        other = DB["slots"].get(sh["slot_id"])
        if other is None:
            continue
        w_start = other["_start_dt"] - buffer
        w_end = other["_end_dt"] + buffer
        if cand_start < w_end and w_start < cand_end:
            raise ApiError(
                "ERR_SHIFT_OVERLAP",
                409,
                "Docent holds a conflicting shift within the 30-minute buffer",
            )


# ---------------------------------------------------------------------------
# Pricing and refunds (calculations: booking_total_price_cents, refund_cents)
# ---------------------------------------------------------------------------


def unit_price_for(route):
    unit = route["base_price_cents"]
    if route["kind"] == "CANDLELIGHT":
        unit = int(
            (Decimal(unit) * Decimal("1.5")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    return unit


def chaperone_divisor(route):
    tiers = [DB["rooms"][rid]["collection_tier"] for rid in route["room_ids"]]
    return 8 if "HIGH_VALUE" in tiers else 10


def ceil_div(a, b):
    return -(-a // b)


def school_total(route, student_count, chaperone_count):
    s = student_count
    charge = 800 * min(s, 15) + 700 * min(max(s - 15, 0), 15) + 600 * max(s - 30, 0)
    free_chaperones = ceil_div(s, chaperone_divisor(route))
    extra = max(0, chaperone_count - free_chaperones)
    return charge + extra * 1000


def time_tier_refund(booking, slot):
    """Manual-cancel refund tiers measured in whole hours before start."""
    total = booking["total_price_cents"]
    if total == 0:
        return 0
    hours = Decimal(str((slot["_start_dt"] - now()).total_seconds())) / Decimal(3600)
    if hours >= 48:
        return total
    if hours >= 24:
        return int(
            (Decimal(total) * Decimal("0.5")).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    return 0


# ---------------------------------------------------------------------------
# Cascades (PRD 3.3, 3.4, 3.7)
# ---------------------------------------------------------------------------


def cancel_slot_cascade(slot, full_refund):
    """Slot -> CANCELLED; its live bookings and shifts cancelled with it."""
    slot["status"] = "CANCELLED"
    touch(slot)
    for b in slot_bookings(slot["id"]):
        if b["status"] in ("RESERVED", "CONFIRMED"):
            if b["status"] == "CONFIRMED":
                b["refund_cents"] = (
                    b["total_price_cents"]
                    if full_refund
                    else time_tier_refund(b, slot)
                )
            else:
                b["refund_cents"] = 0
            b["status"] = "CANCELLED"
            touch(b)
    for s in slot_shifts(slot["id"]):
        if s["status"] in ("ASSIGNED", "CONFIRMED"):
            s["status"] = "CANCELLED"
            touch(s)


def fire_critical_cascade(room):
    """CRITICAL incident: close the room, cancel its future slots (3 hops)."""
    if room["status"] == "OPEN":
        room["status"] = "CLOSED_RESTORATION"
        touch(room)
    t = now()
    for slot in list(DB["slots"].values()):
        if slot["status"] not in ("SCHEDULED", "OPEN", "FULL"):
            continue
        if slot["_start_dt"] <= t:
            continue
        route = DB["routes"].get(slot["route_id"])
        if route is not None and room["id"] in route["room_ids"]:
            cancel_slot_cascade(slot, full_refund=True)


def resolve_incident_side_effects(incident):
    """Reopen the room when no other REPORTED CRITICAL incident references it."""
    if incident["severity"] != "CRITICAL":
        return
    room = DB["rooms"].get(incident["room_id"])
    if room is None or room["status"] != "CLOSED_RESTORATION":
        return
    for other in DB["incidents"].values():
        if (
            other["id"] != incident["id"]
            and other["room_id"] == incident["room_id"]
            and other["severity"] == "CRITICAL"
            and other["status"] == "REPORTED"
        ):
            return
    room["status"] = "OPEN"
    touch(room)


def deactivate_docent_cascade(docent):
    """Cancel this docent's future live shifts; staffing recomputes on read."""
    t = now()
    for sh in DB["shifts"].values():
        if sh["docent_id"] != docent["id"]:
            continue
        if sh["status"] not in ("ASSIGNED", "CONFIRMED"):
            continue
        slot = DB["slots"].get(sh["slot_id"])
        if slot is not None and slot["_start_dt"] > t:
            sh["status"] = "CANCELLED"
            touch(sh)


# ---------------------------------------------------------------------------
# Periodic sweep (PRD 3.5, 3.6)
# ---------------------------------------------------------------------------


def run_epoch():
    t = now()
    d = today()
    expired = 0
    for b in list(DB["bookings"].values()):
        if b["status"] == "RESERVED" and t >= b["_hold_dt"]:
            b["status"] = "EXPIRED"
            touch(b)
            expired += 1
            slot = DB["slots"].get(b["slot_id"])
            if slot is not None:
                refresh_full_open(slot)
    # Snapshot both sets before mutating: one transition per member per epoch.
    lapsing = [
        m
        for m in DB["members"].values()
        if m["status"] == "ACTIVE" and parse_ymd(m["renews_on"]) < d
    ]
    expiring = [
        m
        for m in DB["members"].values()
        if m["status"] == "LAPSED"
        and parse_ymd(m["renews_on"]) + timedelta(days=30) < d
    ]
    for m in lapsing:
        m["status"] = "LAPSED"
        touch(m)
    for m in expiring:
        m["status"] = "EXPIRED"
        touch(m)
    return expired, len(lapsing)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def ser_room(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "floor": r["floor"],
        "capacity_max": r["capacity_max"],
        "safety_max_party": r["safety_max_party"],
        "collection_tier": r["collection_tier"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_route(r):
    return {
        "id": r["id"],
        "name": r["name"],
        "kind": r["kind"],
        "room_ids": list(r["room_ids"]),
        "duration_minutes": r["duration_minutes"],
        "base_price_cents": r["base_price_cents"],
        "status": r["status"],
        "published_script_id": r["published_script_id"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def ser_script(s):
    return {
        "id": s["id"],
        "route_id": s["route_id"],
        "version_no": s["version_no"],
        "content_text": s["content_text"],
        "curriculum_standards": list(s["curriculum_standards"]),
        "status": s["status"],
        "accuracy_score": s["accuracy_score"],
        "reviewer_notes": s["reviewer_notes"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_slot(s):
    return {
        "id": s["id"],
        "route_id": s["route_id"],
        "start_at": fmt_dt(s["_start_dt"]),
        "end_at": fmt_dt(s["_end_dt"]),
        "capacity": s["capacity"],
        "seats_reserved": seats_reserved(s),
        "seats_confirmed": seats_confirmed(s),
        "seats_available": seats_available(s),
        "revenue_committed_cents": revenue_committed(s),
        "revenue_projected_cents": revenue_projected(s),
        "staffing_status": staffing_status(s),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_docent(d):
    return {
        "id": d["id"],
        "full_name": d["full_name"],
        "email": d["email"],
        "status": d["status"],
        "training_hours": d["training_hours"],
        "shadow_tours_completed": d["shadow_tours_completed"],
        "quiz_score": d["quiz_score"],
        "certified_route_ids": list(d["certified_route_ids"]),
        "readiness_standard_score": readiness_standard(d),
        "readiness_apprentice_score": readiness_apprentice(d),
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_shift(s):
    return {
        "id": s["id"],
        "docent_id": s["docent_id"],
        "slot_id": s["slot_id"],
        "shift_role": s["shift_role"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_member(m):
    return {
        "id": m["id"],
        "full_name": m["full_name"],
        "email": m["email"],
        "member_number": m["member_number"],
        "renews_on": m["renews_on"],
        "status": m["status"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


def ser_booking(b):
    return {
        "id": b["id"],
        "slot_id": b["slot_id"],
        "member_id": b["member_id"],
        "booking_kind": b["booking_kind"],
        "visitor_name": b["visitor_name"],
        "party_size": b["party_size"],
        "student_count": b["student_count"],
        "chaperone_count": b["chaperone_count"],
        "grade_level": b["grade_level"],
        "curriculum_standard": b["curriculum_standard"],
        "unit_price_cents": b["unit_price_cents"],
        "total_price_cents": b["total_price_cents"],
        "refund_cents": b["refund_cents"],
        "hold_expires_at": fmt_dt(b["_hold_dt"]),
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


def ser_incident(i):
    return {
        "id": i["id"],
        "room_id": i["room_id"],
        "slot_id": i["slot_id"],
        "severity": i["severity"],
        "description": i["description"],
        "status": i["status"],
        "created_at": i["created_at"],
        "updated_at": i["updated_at"],
        "version": i["version"],
    }


def ser_survey(s):
    # Surveys carry only id and created_at — no updated_at, no version (PRD 2.4).
    return {
        "id": s["id"],
        "booking_id": s["booking_id"],
        "slot_id": s["slot_id"],
        "overall_rating": s["overall_rating"],
        "interpretation_clarity": s["interpretation_clarity"],
        "would_recommend": s["would_recommend"],
        "comment": s["comment"],
        "status": s["status"],
        "created_at": s["created_at"],
    }
