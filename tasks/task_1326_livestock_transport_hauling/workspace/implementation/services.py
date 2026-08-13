"""Domain helpers: serializers, derived fields, settlement math, cascades."""
from datetime import timedelta

import db
import hos
from util import fmt_dt, dec, round_half_up_int, minutes_between

WASHOUT_VALID_HOURS = 96
MAX_CONFINEMENT_MIN = 1680
REST_UNLOAD_MIN = 300
BACKHAUL_DISCOUNT = dec("0.85")          # 1 - 0.15
BACKHAUL_WINDOW_HOURS = 72
EXCESS_SHRINK_PENALTY_CENTS_PER_LB = dec("2.5")

HEAT_THRESHOLD = {"CATTLE": 95, "SWINE": 85, "SHEEP": 90, "HORSES": 95}
COLD_THRESHOLD = {"CATTLE": 0, "SWINE": 10, "SHEEP": -5, "HORSES": 5}

FINE_BASE_CENTS = {
    "INJURY": 33333,
    "DOWNER": 41667,
    "DEAD_ON_ARRIVAL": 100000,
    "ESCAPE": 25000,
}
SEVERITY_MULT = {"MINOR": dec("1.5"), "MAJOR": dec("2.5"), "CRITICAL": dec("4.0")}

ACTIVE_LOAD_STATUSES = {"ASSIGNED", "IN_TRANSIT", "WEATHER_HOLD", "REST_UNLOAD", "ARRIVED"}


# ================================================================ mutations
def touch(rec):
    """Refresh updated_at and bump version by exactly 1 (PRD 2.4/2.9)."""
    rec["updated_at"] = db.now()
    rec["version"] += 1


def new_common():
    t = db.now()
    return {"id": db.new_id(), "created_at": t, "updated_at": t, "version": 1,
            "seq": db.next_seq()}


def new_immutable():
    return {"id": db.new_id(), "created_at": db.now(), "seq": db.next_seq()}


# ================================================================ lookups
def get_load(load_id):
    return db.store["loads"].get(load_id)


def get_driver(driver_id):
    return db.store["drivers"].get(driver_id)


def get_trailer(trailer_id):
    return db.store["trailers"].get(trailer_id)


def get_settlement_for_load(load_id):
    for st in db.store["settlements"].values():
        if st["load_id"] == load_id:
            return st
    return None


# ================================================================ derived
def compartment_occupied(compartment_id):
    head = 0
    weight = 0
    for a in db.store["allocations"].values():
        if a["trailer_compartment_id"] == compartment_id and a["status"] == "ACTIVE":
            head += a["head_count"]
            weight += a["weight_lb"]
    return head, weight


def load_totals(load_id):
    head = 0
    weight = 0
    for a in db.store["allocations"].values():
        if a["load_id"] == load_id and a["status"] == "ACTIVE":
            head += a["head_count"]
            weight += a["weight_lb"]
    return head, weight


def washout_status(trailer, now):
    dirtied = trailer["dirtied_at"]
    washed = trailer["last_washed_at"]
    if dirtied is not None and (washed is None or dirtied > washed):
        return "DIRTY"
    if washed is None:
        return "DIRTY"
    if now <= washed + timedelta(hours=WASHOUT_VALID_HOURS):
        return "CLEAN"
    return "STALE"


def trailer_reserved_until(trailer_id):
    """Max planned window end over this trailer's active-status loads."""
    best = None
    for ld in db.store["loads"].values():
        if ld["trailer_id"] == trailer_id and ld["status"] in ACTIVE_LOAD_STATUSES:
            end = ld["planned_departure_at"] + timedelta(hours=ld["planned_duration_hours"])
            if best is None or end > best:
                best = end
    return best


# ================================================================ serializers
def shipper_json(s):
    return {
        "id": s["id"], "name": s["name"], "contact_email": s["contact_email"],
        "default_shrink_allowance_pct": s["default_shrink_allowance_pct"],
        "created_at": fmt_dt(s["created_at"]), "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def driver_json(d, now=None):
    now = now or db.now()
    f = hos.hos_snapshot(d["id"], now)
    return {
        "id": d["id"], "name": d["name"], "license_no": d["license_no"],
        "status": d["status"],
        "session_driving_minutes": f["session_driving_minutes"],
        "calendar_day_driving_minutes": f["calendar_day_driving_minutes"],
        "cycle_on_duty_minutes_8d": f["cycle_on_duty_minutes_8d"],
        "driving_since_break_minutes": f["driving_since_break_minutes"],
        "duty_window_expires_at": fmt_dt(f["duty_window_expires_at"]),
        "hos_status": f["hos_status"],
        "critical_incident_count_90d": f["critical_incident_count_90d"],
        "created_at": fmt_dt(d["created_at"]), "updated_at": fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def duty_event_json(e):
    return {
        "id": e["id"], "driver_id": e["driver_id"], "event_type": e["event_type"],
        "occurred_at": fmt_dt(e["occurred_at"]), "source": e["source"],
        "load_id": e["load_id"], "created_at": fmt_dt(e["created_at"]),
    }


def trailer_json(t, now=None):
    now = now or db.now()
    washed = t["last_washed_at"]
    return {
        "id": t["id"], "trailer_no": t["trailer_no"],
        "max_gross_weight_lb": t["max_gross_weight_lb"],
        "washout_status": washout_status(t, now),
        "last_washed_at": fmt_dt(washed),
        "washout_valid_until": fmt_dt(washed + timedelta(hours=WASHOUT_VALID_HOURS)) if washed else None,
        "dirtied_at": fmt_dt(t["dirtied_at"]),
        "reserved_until": fmt_dt(trailer_reserved_until(t["id"])),
        "created_at": fmt_dt(t["created_at"]), "updated_at": fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def compartment_json(c):
    head, weight = compartment_occupied(c["id"])
    return {
        "id": c["id"], "trailer_id": c["trailer_id"],
        "compartment_index": c["compartment_index"],
        "max_head_count": c["max_head_count"], "max_weight_lb": c["max_weight_lb"],
        "occupied_head_count": head, "occupied_weight_lb": weight,
        "created_at": fmt_dt(c["created_at"]), "updated_at": fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def load_json(ld):
    head, weight = load_totals(ld["id"])
    return {
        "id": ld["id"], "shipper_id": ld["shipper_id"], "species": ld["species"],
        "declared_head_count": ld["declared_head_count"],
        "declared_weight_lb": ld["declared_weight_lb"],
        "origin": ld["origin"], "destination": ld["destination"],
        "planned_departure_at": fmt_dt(ld["planned_departure_at"]),
        "planned_duration_hours": ld["planned_duration_hours"],
        "rate_per_loaded_mile_cents": ld["rate_per_loaded_mile_cents"],
        "loaded_miles": ld["loaded_miles"],
        "shrink_allowance_pct": ld["shrink_allowance_pct"],
        "effective_shrink_pct": ld["effective_shrink_pct"],
        "backhaul_of_load_id": ld["backhaul_of_load_id"],
        "is_backhaul": ld["backhaul_of_load_id"] is not None,
        "driver_id": ld["driver_id"], "trailer_id": ld["trailer_id"],
        "status": ld["status"],
        "allocated_head_count": head, "allocated_weight_lb": weight,
        "confinement_anchor_at": fmt_dt(ld["confinement_anchor_at"]),
        "rest_unload_started_at": fmt_dt(ld["rest_unload_started_at"]),
        "departed_at": fmt_dt(ld["departed_at"]),
        "arrived_at": fmt_dt(ld["arrived_at"]),
        "delivered_at": fmt_dt(ld["delivered_at"]),
        "created_at": fmt_dt(ld["created_at"]), "updated_at": fmt_dt(ld["updated_at"]),
        "version": ld["version"],
    }


def allocation_json(a):
    return {
        "id": a["id"], "load_id": a["load_id"],
        "trailer_compartment_id": a["trailer_compartment_id"],
        "head_count": a["head_count"], "avg_weight_lb": a["avg_weight_lb"],
        "weight_lb": a["weight_lb"], "status": a["status"],
        "release_reason": a["release_reason"],
        "created_at": fmt_dt(a["created_at"]), "updated_at": fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def health_paper_json(p):
    return {
        "id": p["id"], "load_id": p["load_id"], "cert_number": p["cert_number"],
        "species": p["species"], "head_count_listed": p["head_count_listed"],
        "issued_at": fmt_dt(p["issued_at"]), "expires_at": fmt_dt(p["expires_at"]),
        "status": p["status"], "created_by_user_id": p["created_by_user_id"],
        "verified_by_user_id": p["verified_by_user_id"],
        "created_at": fmt_dt(p["created_at"]), "updated_at": fmt_dt(p["updated_at"]),
        "version": p["version"],
    }


def brand_inspection_json(b):
    return {
        "id": b["id"], "load_id": b["load_id"], "inspection_no": b["inspection_no"],
        "inspected_at": fmt_dt(b["inspected_at"]), "brand_owner": b["brand_owner"],
        "head_count_inspected": b["head_count_inspected"], "status": b["status"],
        "created_by_user_id": b["created_by_user_id"],
        "verified_by_user_id": b["verified_by_user_id"],
        "created_at": fmt_dt(b["created_at"]), "updated_at": fmt_dt(b["updated_at"]),
        "version": b["version"],
    }


def washout_json(w):
    return {
        "id": w["id"], "trailer_id": w["trailer_id"],
        "washed_at": fmt_dt(w["washed_at"]), "method": w["method"],
        "operator_note": w["operator_note"], "created_at": fmt_dt(w["created_at"]),
    }


def ticket_json(t):
    return {
        "id": t["id"], "load_id": t["load_id"], "ticket_type": t["ticket_type"],
        "gross_lb": t["gross_lb"], "tare_lb": t["tare_lb"],
        "net_weight_lb": t["net_weight_lb"], "weighed_at": fmt_dt(t["weighed_at"]),
        "created_at": fmt_dt(t["created_at"]),
    }


def settlement_json(s):
    return {
        "id": s["id"], "load_id": s["load_id"], "status": s["status"],
        "base_amount_cents": s["base_amount_cents"],
        "provisional_amount_cents": s["provisional_amount_cents"],
        "shrink_allowance_lb": s["shrink_allowance_lb"],
        "delivered_weight_lb": s["delivered_weight_lb"],
        "effective_delivered_weight_lb": s["effective_delivered_weight_lb"],
        "shrink_lb": s["shrink_lb"], "excess_shrink_lb": s["excess_shrink_lb"],
        "shrink_penalty_cents": s["shrink_penalty_cents"],
        "welfare_deduction_cents": s["welfare_deduction_cents"],
        "dispute_adjustment_cents": s["dispute_adjustment_cents"],
        "final_amount_cents": s["final_amount_cents"],
        "dispute_deadline_at": fmt_dt(s["dispute_deadline_at"]),
        "disputed_weight_lb": s["disputed_weight_lb"],
        "counter_weight_lb": s["counter_weight_lb"],
        "paid_at": fmt_dt(s["paid_at"]),
        "created_at": fmt_dt(s["created_at"]), "updated_at": fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def incident_json(i):
    return {
        "id": i["id"], "load_id": i["load_id"], "driver_id": i["driver_id"],
        "incident_type": i["incident_type"], "severity": i["severity"],
        "head_count_affected": i["head_count_affected"],
        "occurred_at": fmt_dt(i["occurred_at"]), "description": i["description"],
        "status": i["status"], "fine_cents": i["fine_cents"],
        "fine_waived": i["fine_waived"], "closed_at": fmt_dt(i["closed_at"]),
        "created_at": fmt_dt(i["created_at"]), "updated_at": fmt_dt(i["updated_at"]),
        "version": i["version"],
    }


def hold_json(h):
    return {
        "id": h["id"], "load_id": h["load_id"], "hold_type": h["hold_type"],
        "temperature_f": h["temperature_f"], "reason": h["reason"],
        "status": "ACTIVE" if h["released_at"] is None else "RELEASED",
        "released_at": fmt_dt(h["released_at"]),
        "created_at": fmt_dt(h["created_at"]), "updated_at": fmt_dt(h["updated_at"]),
        "version": h["version"],
    }


# ================================================================ duty events
def insert_duty_event(driver_id, event_type, occurred_at, source, load_id=None):
    rec = new_immutable()
    rec.update({
        "driver_id": driver_id, "event_type": event_type,
        "occurred_at": occurred_at, "source": source, "load_id": load_id,
    })
    db.store["duty_events"][rec["id"]] = rec
    return rec


def append_system_event(driver_id, event_type, at, load_id):
    """Append a SYSTEM duty event, keeping the sub-state machine consistent.

    Guards mirror the transition rules: DUTY_ON only while off duty (a
    DRIVING_ON request while off duty first anchors DUTY_ON), DRIVING_ON only
    while on duty and not driving, DRIVING_OFF only while driving, DUTY_OFF
    only while on duty.
    """
    state = hos.duty_sub_state(driver_id, at)
    if event_type == "DUTY_ON":
        if state != hos.OFF:
            return None
    elif event_type == "DRIVING_ON":
        if state == hos.OFF:
            insert_duty_event(driver_id, "DUTY_ON", at, "SYSTEM", load_id)
            state = hos.DUTY
        if state != hos.DUTY:
            return None
    elif event_type == "DRIVING_OFF":
        if state != hos.DRIVING:
            return None
    elif event_type == "DUTY_OFF":
        if state == hos.OFF:
            return None
    return insert_duty_event(driver_id, event_type, at, "SYSTEM", load_id)


# ================================================================ settlement math
def compute_base_amount(load):
    """Round rate*miles first, then backhaul discount, then round again."""
    base = round_half_up_int(dec(load["rate_per_loaded_mile_cents"]) * dec(load["loaded_miles"]))
    if load["backhaul_of_load_id"] is not None:
        base = round_half_up_int(dec(base) * BACKHAUL_DISCOUNT)
    return base


def shrink_fields(load, effective_weight_lb):
    allowed = round_half_up_int(
        dec(load["declared_weight_lb"]) * dec(load["effective_shrink_pct"]) / dec(100))
    shrink = max(0, load["declared_weight_lb"] - effective_weight_lb)
    excess = max(0, shrink - allowed)
    penalty = round_half_up_int(dec(excess) * EXCESS_SHRINK_PENALTY_CENTS_PER_LB)
    return allowed, shrink, excess, penalty


def welfare_deduction(load_id):
    total = 0
    for inc in db.store["incidents"].values():
        if inc["load_id"] == load_id and inc["status"] == "CLOSED" and not inc["fine_waived"]:
            total += inc["fine_cents"] or 0
    return total


def recompute_settlement_final(st):
    """Apply money identity: final = max(0, provisional - penalty - welfare)."""
    st["welfare_deduction_cents"] = welfare_deduction(st["load_id"])
    st["final_amount_cents"] = max(
        0,
        st["provisional_amount_cents"]
        - (st["shrink_penalty_cents"] or 0)
        - st["welfare_deduction_cents"],
    )


def apply_weight_basis(st, load, effective_weight_lb):
    """Recompute shrink chain on a given effective delivered weight."""
    allowed, shrink, excess, penalty = shrink_fields(load, effective_weight_lb)
    st["shrink_allowance_lb"] = allowed
    st["shrink_lb"] = shrink
    st["excess_shrink_lb"] = excess
    st["shrink_penalty_cents"] = penalty
    recompute_settlement_final(st)


def latest_delivery_ticket(load_id):
    best = None
    for t in db.store["weight_tickets"].values():
        if t["load_id"] == load_id and t["ticket_type"] == "DELIVERY":
            if best is None or (t["weighed_at"], t["seq"]) > (best["weighed_at"], best["seq"]):
                best = t
    return best


def compute_fine_cents(incident_type, severity, head_count_affected):
    return round_half_up_int(
        dec(FINE_BASE_CENTS[incident_type]) * dec(head_count_affected) * SEVERITY_MULT[severity])


# ================================================================ cascades
def release_allocations(load, reason):
    for a in db.store["allocations"].values():
        if a["load_id"] == load["id"] and a["status"] == "ACTIVE":
            a["status"] = "RELEASED"
            a["release_reason"] = reason
            touch(a)


def force_unassign_driver_loads(driver_id):
    """Force-unassign every ASSIGNED load of the driver -> PAPERWORK_VERIFIED."""
    for ld in db.store["loads"].values():
        if ld["driver_id"] == driver_id and ld["status"] == "ASSIGNED":
            ld["driver_id"] = None
            ld["status"] = "PAPERWORK_VERIFIED"
            touch(ld)


def maybe_suspend_driver(driver):
    """Chain link 2/3 of incident close: suspend at >=2 closed CRITICAL in 90d."""
    f = hos.hos_snapshot(driver["id"], db.now())
    if f["critical_incident_count_90d"] >= hos.SUSPENSION_CRITICAL_COUNT and driver["status"] == "ACTIVE":
        driver["status"] = "SUSPENDED"
        touch(driver)
        force_unassign_driver_loads(driver["id"])
