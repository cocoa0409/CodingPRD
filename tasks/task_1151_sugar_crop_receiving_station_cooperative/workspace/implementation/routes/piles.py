from flask import Blueprint

import db
import response
import serializers
import services.cascade as cascade
from errors import raise_err
from middleware import require_roles
from routes._common import as_decimal, body, req_field
from services.calc import D

bp = Blueprint("piles", __name__)


@bp.post("/api/piles")
def create_pile():
    require_roles(["STATION_OPERATOR"])
    data = body()
    station_id = req_field(data, "station_id")
    cap = as_decimal(req_field(data, "capacity_tons"), "capacity_tons")
    st = db.stations.get(station_id)
    if not st:
        raise_err("ERR_NOT_FOUND", "Station not found")
    if cap <= 0:
        raise_err("ERR_INVALID_REQUEST", "capacity_tons must be > 0")
    p = db.stamp_new({
        "station_id": station_id,
        "capacity_tons": cap,
        "fill_status": "FILLING",
        "condition_status": "SOUND",
        "stored_lbs": D("0"),
        "sealed_stored_lbs": None,
        "sealed_at": None,
        "reclaim_started_at": None,
    })
    db.piles[p["id"]] = p
    cascade.recompute_station(station_id)
    return response.success(serializers.pile(p), 201)


@bp.get("/api/piles/<pile_id>")
def get_pile(pile_id):
    require_roles(["COOP_ADMIN", "STATION_OPERATOR", "SCHEDULER", "POOL_ACCOUNTANT", "MEMBER"])
    p = db.piles.get(pile_id)
    if not p:
        raise_err("ERR_NOT_FOUND", "Pile not found")
    return response.success(serializers.pile(p), 200)


@bp.post("/api/piles/<pile_id>/seal")
def seal_pile(pile_id):
    require_roles(["STATION_OPERATOR"])
    p = db.piles.get(pile_id)
    if not p:
        raise_err("ERR_NOT_FOUND", "Pile not found")
    if p["fill_status"] != "FILLING":
        raise_err("ERR_INVALID_STATE", "Pile is not FILLING")
    p["fill_status"] = "SEALED"
    p["sealed_stored_lbs"] = D(p["stored_lbs"])
    p["sealed_at"] = db.now()
    db.touch(p)
    return response.success(serializers.pile(p), 200)


@bp.post("/api/piles/<pile_id>/begin-reclaim")
def begin_reclaim(pile_id):
    require_roles(["STATION_OPERATOR"])
    p = db.piles.get(pile_id)
    if not p:
        raise_err("ERR_NOT_FOUND", "Pile not found")
    if p["fill_status"] != "SEALED":
        raise_err("ERR_INVALID_STATE", "Pile is not SEALED")
    now = db.now()
    for e in db.loss_events.values():
        if e["pile_id"] != pile_id:
            continue
        if e["status"] in ("DRAFT", "CONFIRMED"):
            if e["window_start"] <= now <= e["window_end"]:
                raise_err("ERR_SURVEY_BLACKOUT", "Survey blackout window contains the logical clock")
    p["fill_status"] = "RECLAIMING"
    p["reclaim_started_at"] = now
    db.touch(p)
    return response.success(serializers.pile(p), 200)


@bp.post("/api/piles/<pile_id>/complete-reclaim")
def complete_reclaim(pile_id):
    require_roles(["STATION_OPERATOR"])
    data = body()
    shipped = as_decimal(req_field(data, "shipped_lbs"), "shipped_lbs")
    p = db.piles.get(pile_id)
    if not p:
        raise_err("ERR_NOT_FOUND", "Pile not found")
    if p["fill_status"] != "RECLAIMING":
        raise_err("ERR_INVALID_STATE", "Pile is not RECLAIMING")
    total_remaining = sum(
        (D(a["remaining_lbs"]) for a in db.pile_allocations.values()
         if a["pile_id"] == pile_id and a["status"] == "ACTIVE"),
        D("0"),
    )
    if shipped != total_remaining:
        raise_err("ERR_SHIPPED_WEIGHT_MISMATCH", "shipped_lbs must equal sum of remaining_lbs over ACTIVE allocations")
    for a in db.pile_allocations.values():
        if a["pile_id"] == pile_id and a["status"] == "ACTIVE":
            a["status"] = "DEPLETED"
            db.touch(a)
    p["fill_status"] = "EMPTY"
    cascade.recompute_pile_stored(pile_id)
    db.touch(p)
    cascade.recompute_station(p["station_id"])
    return response.success(serializers.pile(p), 200)


@bp.get("/api/piles/<pile_id>/loss-events")
def list_pile_loss_events(pile_id):
    require_roles(["COOP_ADMIN", "STATION_OPERATOR", "POOL_ACCOUNTANT"])
    p = db.piles.get(pile_id)
    if not p:
        raise_err("ERR_NOT_FOUND", "Pile not found")
    events = [e for e in db.loss_events.values() if e["pile_id"] == pile_id]
    events.sort(key=lambda e: (e["created_at"], e["id"]))
    return response.success_list([serializers.loss_event(e) for e in events], len(events), len(events), 0, 200)
