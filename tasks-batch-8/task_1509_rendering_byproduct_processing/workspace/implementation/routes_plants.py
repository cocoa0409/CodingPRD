"""Clock, Plant, and PeriodSettlement endpoints."""
from flask import Blueprint

import db
from common import (caller, require_role, body_json, v_str, v_int, ok, view,
                    stamp_new, touch, paginate, get_or_404, fail, iso_z, parse_dt)
from logic import (posture_gate, settlement_view, current_settlement,
                   active_permit, plant_decommission_cascade, plant_suspend,
                   RECOVERY_PER_PERIOD, RECOVERY_THRESHOLD, SCORE_CAP)

bp = Blueprint("plants", __name__)


# ---------------- logical clock ----------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    uid, role = caller()
    b = body_json()
    raw = b.get("to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        fail("ERR_INVALID_REQUEST", 400, "to_iso8601 must be an ISO8601 timestamp")
    require_role(role, "PlantManager")
    db.set_now(dt)
    return ok({"current_utc": iso_z(db.now())}, 200)


# ---------------- plants ----------------

@bp.post("/rendering/plants")
def create_plant():
    uid, role = caller()
    b = body_json()
    plant_name = v_str(b, "plant_name")
    location = v_str(b, "location")
    cap = v_int(b, "cooker_capacity", minv=1)
    cost = v_int(b, "standard_cost_cents_per_lb")
    require_role(role, "PlantManager")
    p = {
        "plant_name": plant_name,
        "location": location,
        "cooker_capacity": cap,
        "standard_cost_cents_per_lb": cost,
        "odor_score": 1000,
        "posture": "OPERATING",
        "current_period_index": 1,
    }
    stamp_new(p)
    db.STORES["plants"][p["id"]] = p
    s = {
        "plant_id": p["id"],
        "period_index": 1,
        "pickup_fees_accrued_cents": 0,
        "product_revenue_cents": 0,
        "energy_costs_cents": 0,
        "transport_costs_cents": 0,
        "confirmed_odor_events": 0,
        "closed_by": None,
        "status": "OPEN",
    }
    stamp_new(s)
    db.STORES["settlements"][s["id"]] = s
    return ok(view(p), 201)


@bp.get("/rendering/plants")
def list_plants():
    caller()
    items = db_sorted("plants", {"posture": q("posture")})
    return paginate(items)


@bp.get("/rendering/plants/<pid>")
def get_plant(pid):
    caller()
    p = get_or_404("plants", pid, "ERR_PLANT_NOT_FOUND")
    return ok(view(p), 200)


@bp.post("/rendering/plants/<pid>/decommission")
def decommission_plant(pid):
    uid, role = caller()
    require_role(role, "PlantManager")
    p = get_or_404("plants", pid, "ERR_PLANT_NOT_FOUND")
    if p["posture"] == "DECOMMISSIONED":
        fail("ERR_PLANT_DECOMMISSIONED", 409, "Plant is already DECOMMISSIONED")
    p["posture"] = "DECOMMISSIONED"
    touch(p)
    plant_decommission_cascade(p)
    return ok(view(p), 200)


@bp.post("/rendering/plants/<pid>/advance-period")
def advance_period(pid):
    uid, role = caller()
    require_role(role, "FinanceAnalyst")
    p = get_or_404("plants", pid, "ERR_PLANT_NOT_FOUND")
    posture_gate(p, "admin")
    st = current_settlement(p)
    if st is None or st["status"] != "CLOSED":
        fail("ERR_SETTLEMENT_NOT_CLOSED", 409, "Current period settlement must be CLOSED")
    closing_events = st["confirmed_odor_events"]
    p["current_period_index"] += 1
    new_s = {
        "plant_id": p["id"],
        "period_index": p["current_period_index"],
        "pickup_fees_accrued_cents": 0,
        "product_revenue_cents": 0,
        "energy_costs_cents": 0,
        "transport_costs_cents": 0,
        "confirmed_odor_events": 0,
        "closed_by": None,
        "status": "OPEN",
    }
    stamp_new(new_s)
    db.STORES["settlements"][new_s["id"]] = new_s
    # reset the ACTIVE permit's violation count
    ap = active_permit(p["id"])
    if ap is not None:
        ap["confirmed_violation_count"] = 0
        touch(ap)
    # odor recovery
    if closing_events == 0:
        p["odor_score"] = min(SCORE_CAP, p["odor_score"] + RECOVERY_PER_PERIOD)
    if p["posture"] == "RESTRICTED" and p["odor_score"] >= RECOVERY_THRESHOLD:
        p["posture"] = "OPERATING"
    touch(p)
    # permit expiry processed at calendar advancement
    cur_date = iso_z(db.now())[:10]
    for perm in list(db.STORES["permits"].values()):
        if perm["plant_id"] == p["id"] and perm["status"] == "ACTIVE" and perm["expires_on"] < cur_date:
            perm["status"] = "EXPIRED"
            touch(perm)
            plant_suspend(p)
    return ok(view(p), 200)


# ---------------- settlements ----------------

@bp.get("/rendering/period-settlements")
def list_settlements():
    caller()
    filt = {
        "plant_id": q("plant_id"),
        "status": q("status"),
    }
    raw_pi = q("period_index")
    if raw_pi is not None:
        try:
            filt["period_index"] = int(raw_pi)
        except ValueError:
            fail("ERR_INVALID_REQUEST", 400, "period_index must be an integer")
    items = db_sorted("settlements", filt)
    return paginate(items, viewfn=settlement_view)


@bp.get("/rendering/period-settlements/<sid>")
def get_settlement(sid):
    caller()
    s = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND")
    return ok(settlement_view(s), 200)


@bp.post("/rendering/period-settlements/<sid>/close")
def close_settlement(sid):
    uid, role = caller()
    require_role(role, "FinanceAnalyst")
    s = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND")
    p = get_or_404("plants", s["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(p, "admin")
    if s["status"] not in ("OPEN", "REOPENED"):
        fail("ERR_SETTLEMENT_INVALID_STATE", 409, "Settlement must be OPEN or REOPENED to close")
    s["status"] = "CLOSED"
    s["closed_by"] = uid
    touch(s)
    return ok(settlement_view(s), 200)


@bp.post("/rendering/period-settlements/<sid>/reopen")
def reopen_settlement(sid):
    uid, role = caller()
    require_role(role, "PlantManager")
    s = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND")
    p = get_or_404("plants", s["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(p, "admin")
    if s["status"] != "CLOSED":
        fail("ERR_SETTLEMENT_INVALID_STATE", 409, "Settlement must be CLOSED to reopen")
    if s["period_index"] != p["current_period_index"]:
        fail("ERR_SETTLEMENT_INVALID_STATE", 409, "Only the current period's settlement may be reopened")
    s["status"] = "REOPENED"
    s["closed_by"] = None
    touch(s)
    return ok(settlement_view(s), 200)


@bp.post("/rendering/period-settlements/<sid>/finalize")
def finalize_settlement(sid):
    uid, role = caller()
    require_role(role, "PlantManager")
    s = get_or_404("settlements", sid, "ERR_SETTLEMENT_NOT_FOUND")
    p = get_or_404("plants", s["plant_id"], "ERR_PLANT_NOT_FOUND")
    posture_gate(p, "admin")
    if s["status"] != "CLOSED":
        fail("ERR_SETTLEMENT_INVALID_STATE", 409, "Settlement must be CLOSED to finalize")
    if s["closed_by"] is not None and s["closed_by"] == uid:
        fail("ERR_SOD_VIOLATION", 403, "Finalizer must differ from the closer")
    s["status"] = "FINALIZED"
    touch(s)
    return ok(settlement_view(s), 200)


# helpers local to this module (avoid circulars)
from flask import request as _request


def q(name):
    return _request.args.get(name)


def db_sorted(store, filters):
    from common import sorted_items
    return sorted_items(store, filters)
