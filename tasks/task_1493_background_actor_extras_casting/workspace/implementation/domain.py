"""Entity constructors, serializers, and derived (computed) field logic.

Derived fields (slot accounting, active counts, projected counts, batch totals,
production exposure, holding occupancy, reliability) are computed fresh at
serialization time so every read reflects the current store; frozen snapshots
(projected_compliant at lock, actual_* at wrap, voucher pay fields at issue)
are stored on the entity at the moment the specification pins them.
"""
from db import STORE, fmt_dt, fmt_wall, new_id, next_seq, wall_now

ACTIVE_BOOKING_STATES = ("OFFERED", "CONFIRMED", "CHECKED_IN", "WRAPPED")
BOOKING_TERMINAL_STATES = ("WRAPPED", "DECLINED", "EXPIRED", "CANCELLED", "NO_SHOW")

UNION_STATUSES = ("SAG_AFTRA", "NONUNION")
LOOK_CATEGORIES = (
    "WARDROBE_OWN",
    "FORMAL_WEAR",
    "PERIOD_COSTUME",
    "HAIR_MAKEUP",
    "PROPS_OWN",
    "SPECIAL_ABILITY",
)
EVENT_TYPES = ("CHECK_IN", "MEAL_OUT", "MEAL_IN", "WRAP_OUT")
BATCH_OUTCOMES = ("ACCEPTED", "REJECTED")


def touch(entity):
    """Version/updated_at maintenance: every mutation bumps both (PRD section 2.4)."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = wall_now()


def _common(entity):
    return {
        "id": entity["id"],
        "created_at": fmt_wall(entity["created_at"]),
        "updated_at": fmt_wall(entity["updated_at"]),
        "version": entity["version"],
    }


def _base():
    now = wall_now()
    return {"id": new_id(), "created_at": now, "updated_at": now, "version": 1, "_seq": next_seq()}


# ---------------------------------------------------------------------------
# Derived lookups
# ---------------------------------------------------------------------------

def call_bookings(call_id):
    return [b for b in STORE.bookings.values() if b["casting_call_id"] == call_id]


def call_active_bookings(call_id):
    return [b for b in call_bookings(call_id) if b["status"] in ACTIVE_BOOKING_STATES]


def call_union_active(call_id):
    return sum(1 for b in call_active_bookings(call_id) if b["slot_type"] == "UNION")


def call_nonunion_active(call_id):
    return sum(1 for b in call_active_bookings(call_id) if b["slot_type"] == "NONUNION")


def batch_vouchers(batch_id):
    return [v for v in STORE.vouchers.values() if v.get("payroll_batch_id") == batch_id]


def batch_gross(batch_id):
    return sum(v.get("gross_total_cents") or 0 for v in batch_vouchers(batch_id))


def production_exposure(production_id):
    total = 0
    for batch in STORE.payroll_batches.values():
        if batch["production_id"] == production_id:
            total += batch_gross(batch["id"])
    return total


def area_occupancy(area_id):
    return sum(
        1
        for b in STORE.bookings.values()
        if b.get("holding_area_id") == area_id and b["status"] == "CHECKED_IN"
    )


def reliability_of(actor):
    return max(0, 100 - 20 * actor.get("no_show_count", 0))


def required_union_slots(call):
    return call["union_slots"] - call.get("approved_waiver_reduction", 0)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def ser_production(p):
    out = _common(p)
    out.update(
        {
            "title": p["title"],
            "studio_code": p["studio_code"],
            "payroll_company_name": p["payroll_company_name"],
            "status": p["status"],
            "compliance_index": p["compliance_index"],
            "payroll_exposure_cents": production_exposure(p["id"]),
        }
    )
    return out


def ser_actor(a):
    out = _common(a)
    out.update(
        {
            "legal_name": a["legal_name"],
            "union_status": a["union_status"],
            "special_abilities": a["special_abilities"],
            "sizes": a["sizes"],
            "status": a["status"],
            "no_show_count": a["no_show_count"],
            "reliability_score": reliability_of(a),
        }
    )
    return out


def ser_call(c):
    out = _common(c)
    active = call_active_bookings(c["id"])
    union_active = sum(1 for b in active if b["slot_type"] == "UNION")
    out.update(
        {
            "production_id": c["production_id"],
            "shoot_date": c["shoot_date"],
            "general_call_time": fmt_dt(c["general_call_time"]),
            "scheduled_duration_minutes": c["scheduled_duration_minutes"],
            "location": c["location"],
            "union_slots": c["union_slots"],
            "nonunion_slots": c["nonunion_slots"],
            "union_rate_cents": c["union_rate_cents"],
            "nonunion_rate_cents": c["nonunion_rate_cents"],
            "wardrobe_notes": c["wardrobe_notes"],
            "status": c["status"],
            "approved_waiver_reduction": c["approved_waiver_reduction"],
            "required_union_slots": required_union_slots(c),
            "slots_available": c["union_slots"] + c["nonunion_slots"] - len(active),
            "union_bookings_active": union_active,
            "nonunion_bookings_active": len(active) - union_active,
            "projected_union_count": union_active,
            "projected_compliant": c.get("projected_compliant"),
            "actual_union_checkins": c.get("actual_union_checkins"),
            "actual_compliant": c.get("actual_compliant"),
        }
    )
    return out


def ser_look(lr):
    # LookRequirement is immutable: id + created_at only (no updated_at/version).
    return {
        "id": lr["id"],
        "created_at": fmt_wall(lr["created_at"]),
        "casting_call_id": lr["casting_call_id"],
        "category": lr["category"],
        "description": lr["description"],
        "bump_amount_cents": lr["bump_amount_cents"],
        "mandatory": lr["mandatory"],
    }


def ser_area(a):
    out = _common(a)
    out.update(
        {
            "casting_call_id": a["casting_call_id"],
            "name": a["name"],
            "capacity": a["capacity"],
            "current_occupancy": area_occupancy(a["id"]),
        }
    )
    return out


def ser_booking(b):
    out = _common(b)
    out.update(
        {
            "casting_call_id": b["casting_call_id"],
            "actor_id": b["actor_id"],
            "replacement_case_id": b["replacement_case_id"],
            "replaces_booking_id": b["replaces_booking_id"],
            "is_replacement": b["is_replacement"],
            "slot_type": b["slot_type"],
            "daily_rate_cents": b["daily_rate_cents"],
            "call_time": fmt_dt(b["call_time"]),
            "expected_wrap_time": fmt_dt(b["expected_wrap_time"]),
            "offer_expires_at": fmt_dt(b["offer_expires_at"]),
            "holding_area_id": b["holding_area_id"],
            "status": b["status"],
        }
    )
    return out


def ser_event(e):
    # TimeEvent is an append-only ledger record: id + created_at only.
    return {
        "id": e["id"],
        "created_at": fmt_wall(e["created_at"]),
        "booking_id": e["booking_id"],
        "event_type": e["event_type"],
        "occurred_at": fmt_dt(e["occurred_at"]),
        "corrects_event_id": e["corrects_event_id"],
        "recorded_by": e["recorded_by"],
    }


def ser_voucher(v):
    out = _common(v)
    out.update(
        {
            "booking_id": v["booking_id"],
            "payroll_batch_id": v["payroll_batch_id"],
            "status": v["status"],
            "check_in_at": fmt_dt(v.get("check_in_at")),
            "wrap_out_at": fmt_dt(v.get("wrap_out_at")),
            "gross_elapsed_minutes": v.get("gross_elapsed_minutes"),
            "net_work_minutes": v.get("net_work_minutes"),
            "ot_tier1_minutes": v.get("ot_tier1_minutes"),
            "ot_tier2_minutes": v.get("ot_tier2_minutes"),
            "meal_penalty_count": v.get("meal_penalty_count"),
            "base_wages_cents": v.get("base_wages_cents"),
            "ot_wages_cents": v.get("ot_wages_cents"),
            "meal_penalty_cents": v.get("meal_penalty_cents"),
            "bumps_total_cents": v.get("bumps_total_cents"),
            "gross_total_cents": v.get("gross_total_cents"),
            "issued_by_user_id": v.get("issued_by_user_id"),
            "adjusted_by_user_id": v.get("adjusted_by_user_id"),
            "issued_at": fmt_dt(v.get("issued_at")),
        }
    )
    return out


def ser_bump(b):
    out = _common(b)
    out.update(
        {
            "voucher_id": b["voucher_id"],
            "category": b["category"],
            "amount_cents": b["amount_cents"],
            "justification": b["justification"],
            "requested_by_user_id": b["requested_by_user_id"],
            "decided_by_user_id": b["decided_by_user_id"],
            "status": b["status"],
        }
    )
    return out


def ser_batch(b):
    out = _common(b)
    members = batch_vouchers(b["id"])
    out.update(
        {
            "production_id": b["production_id"],
            "period_label": b["period_label"],
            "status": b["status"],
            "gross_total_cents": sum(v.get("gross_total_cents") or 0 for v in members),
            "voucher_count": len(members),
            "submitted_by_user_id": b["submitted_by_user_id"],
            "acknowledged_by_user_id": b["acknowledged_by_user_id"],
            "submitted_at": fmt_dt(b.get("submitted_at")),
        }
    )
    return out


def ser_case(c):
    out = _common(c)
    out.update(
        {
            "casting_call_id": c["casting_call_id"],
            "original_booking_id": c["original_booking_id"],
            "required_slot_type": c["required_slot_type"],
            "reason": c["reason"],
            "deadline_at": fmt_dt(c["deadline_at"]),
            "excluded_actor_ids": c["excluded_actor_ids"],
            "offered_booking_id": c["offered_booking_id"],
            "offered_actor_id": c["offered_actor_id"],
            "attempts_count": c["attempts_count"],
            "status": c["status"],
        }
    )
    return out


def ser_standby(s):
    out = _common(s)
    out.update(
        {
            "casting_call_id": s["casting_call_id"],
            "actor_id": s["actor_id"],
            "slot_type": s["slot_type"],
            "status": s["status"],
        }
    )
    return out


def ser_waiver(w):
    out = _common(w)
    out.update(
        {
            "casting_call_id": w["casting_call_id"],
            "union_slot_reduction": w["union_slot_reduction"],
            "justification": w["justification"],
            "requested_by_user_id": w["requested_by_user_id"],
            "decided_by_user_id": w["decided_by_user_id"],
            "status": w["status"],
        }
    )
    return out
