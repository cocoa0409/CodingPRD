"""QuarantineRecord endpoints (PRD §3.6)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import get_auth, require_roles
from response import object_response, array_response
from serializers import quarantine_view
import common as C

bp = Blueprint("quarantines", __name__)

LIST_ROLES = {"FieldTech", "AccountManager", "Dispatcher"}


@bp.post("/aquatics/quarantines")
def create_quarantine():
    _, role = get_auth()
    require_roles(role, {"FieldTech"})
    data = C.require_body(request.get_json(silent=True))
    livestock_id = C.req_str(data, "livestock_id")
    quarantine_tank_id = C.req_str(data, "quarantine_tank_id")
    window_start = C.req_datetime(data, "window_start")
    window_end = C.req_datetime(data, "window_end")
    expected_tank_version = C.req_int(data, "expected_tank_version")

    # existence left-to-right: livestock, then tank
    livestock = store.livestock.get(livestock_id)
    if livestock is None:
        raise ApiError("ERR_NOT_FOUND", "Livestock not found.")
    tank = store.systems.get(quarantine_tank_id)
    if tank is None:
        raise ApiError("ERR_NOT_FOUND", "Quarantine tank not found.")

    s_dt = C.parse_iso(window_start)
    e_dt = C.parse_iso(window_end)

    # tank occupancy overlap (priority 10) — closed intervals, shared endpoint conflicts
    for q in store.quarantines.values():
        if q["quarantine_tank_id"] == quarantine_tank_id and q["status"] == "ACTIVE":
            q_s = C.parse_iso(q["window_start"])
            q_e = C.parse_iso(q["window_end"])
            if C.closed_overlap(s_dt, e_dt, q_s, q_e):
                raise ApiError("ERR_QT_TANK_OCCUPIED", "Quarantine tank already occupied.")

    # freshwater tank constraint (priority 11)
    if tank["system_kind"] != "FRESHWATER":
        raise ApiError("ERR_INVALID_QT_TANK", "Quarantine tank must be a FRESHWATER system.")

    # window ordering (priority 13): window_start <= window_end (closed)
    if not (s_dt <= e_dt):
        raise ApiError("ERR_BAD_WINDOW", "window_start must be at or before window_end.")

    # OCC (priority 15)
    if expected_tank_version != tank["version"]:
        raise ApiError("ERR_STALE_VERSION", "Stale tank version.")

    rec = C.make_record({
        "livestock_id": livestock_id,
        "quarantine_tank_id": quarantine_tank_id,
        "window_start": window_start,
        "window_end": window_end,
        "status": "ACTIVE",
    })
    store.quarantines[rec["id"]] = rec

    # tank version increments on successful open
    C.touch(tank)

    # move livestock to QUARANTINED; recompute home system bioload + alive count
    livestock["status"] = "QUARANTINED"
    C.touch(livestock)
    home = store.systems.get(livestock["system_id"])
    if home is not None:
        C.recompute_system_bioload(home)
        contract = store.contracts.get(home["contract_id"])
        if contract is not None:
            C.recompute_alive_livestock_count(contract)
    return object_response(quarantine_view(rec), 201)


@bp.get("/aquatics/quarantines/<qid>")
def get_quarantine(qid):
    _, role = get_auth()
    require_roles(role, LIST_ROLES)
    rec = store.quarantines.get(qid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Quarantine record not found.")
    return object_response(quarantine_view(rec))


@bp.get("/aquatics/livestock/<lid>/quarantines")
def list_livestock_quarantines(lid):
    _, role = get_auth()
    require_roles(role, LIST_ROLES)
    if lid not in store.livestock:
        raise ApiError("ERR_NOT_FOUND", "Livestock not found.")
    limit, offset = C.parse_pagination(request.args)
    status = request.args.get("status")
    recs = [q for q in store.quarantines.values() if q["livestock_id"] == lid]
    if status is not None:
        recs = [q for q in recs if q["status"] == status]
    page, total = C.paginate(recs, limit, offset)
    return array_response([quarantine_view(r) for r in page], limit, offset, total)


@bp.post("/aquatics/quarantines/<qid>/clear")
def clear_quarantine(qid):
    _, role = get_auth()
    require_roles(role, {"FieldTech"})
    rec = store.quarantines.get(qid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Quarantine record not found.")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE quarantine may be cleared.")
    livestock = store.livestock.get(rec["livestock_id"])
    if livestock is None or livestock["status"] != "QUARANTINED":
        raise ApiError("ERR_INVALID_STATE", "Linked livestock must be QUARANTINED.")
    home = store.systems.get(livestock["system_id"])
    # overstock gate (priority 8): projected bioload if animal returns ALIVE
    if home is not None:
        projected = C.bioload_with_extra(home, make_alive_ids={livestock["id"]})
        if projected > 100.0:
            raise ApiError("ERR_OVERSTOCKED", "Clearing would overstock the home system.")
    rec["status"] = "CLEARED"
    C.touch(rec)
    livestock["status"] = "ALIVE"
    C.touch(livestock)
    if home is not None:
        C.recompute_system_bioload(home)
        contract = store.contracts.get(home["contract_id"])
        if contract is not None:
            C.recompute_alive_livestock_count(contract)
    return object_response(quarantine_view(rec))


@bp.post("/aquatics/quarantines/<qid>/abort")
def abort_quarantine(qid):
    _, role = get_auth()
    require_roles(role, {"FieldTech"})
    rec = store.quarantines.get(qid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", "Quarantine record not found.")
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE quarantine may be aborted.")
    rec["status"] = "ABORTED"
    C.touch(rec)
    livestock = store.livestock.get(rec["livestock_id"])
    if livestock is not None:
        livestock["status"] = "DECEASED"
        C.touch(livestock)
        home = store.systems.get(livestock["system_id"])
        if home is not None:
            C.recompute_system_bioload(home)
            # alive_livestock_count unchanged (QUARANTINED already excluded), but
            # recompute is harmless and keeps it canonical.
            contract = store.contracts.get(home["contract_id"])
            if contract is not None:
                C.recompute_alive_livestock_count(contract)
    return object_response(quarantine_view(rec))
