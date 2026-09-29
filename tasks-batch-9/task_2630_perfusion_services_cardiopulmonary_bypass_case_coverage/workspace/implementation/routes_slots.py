"""Call rotation slots and the logical clock."""

from flask import Blueprint, request

import constants as C
import serialize
import svc
import valid as V
from auth import ROLE_CHIEF, ROLE_CONTRACT_ADMIN, ROLE_PERFUSIONIST, endpoint
from envelope import iso_instant, ok, ok_list
from errors import ApiError
from store import db, insert, ordered, stamp_new

bp = Blueprint("slots", __name__)

SLOT_READ = (ROLE_CONTRACT_ADMIN, ROLE_CHIEF, ROLE_PERFUSIONIST)


@bp.post("/call-rotation-slots")
@endpoint([ROLE_CONTRACT_ADMIN, ROLE_CHIEF])
def create_slot(actor):
    body = V.payload()
    V.require(body, "contract_id", "perfusionist_id", "slot_type", "window_start", "window_end")
    row = {
        "contract_id": V.vstr(body, "contract_id", required=True),
        "perfusionist_id": V.vstr(body, "perfusionist_id", required=True),
        "slot_type": V.venum(body, "slot_type", C.SLOT_TYPES, required=True),
        "window_start": V.vdt(body, "window_start", required=True),
        "window_end": V.vdt(body, "window_end", required=True),
        "status": "SCHEDULED",
        "consumed": False,
    }
    contract = svc.get_contract(row["contract_id"])
    perf = svc.get_perfusionist(row["perfusionist_id"])
    if perf["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PERFUSIONIST_NOT_ACTIVE")
    if row["slot_type"] == "ECMO_RELIEF" and not perf["ecmo_privileged"]:
        raise ApiError("ERR_ECMO_PRIVILEGE_REQUIRED")
    if row["window_end"] <= row["window_start"]:
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    for other in db.call_rotation_slots.values():
        if other["perfusionist_id"] != row["perfusionist_id"]:
            continue
        if other["status"] not in C.LIVE_SLOT_STATUSES:
            continue
        if svc.intervals_overlap(row["window_start"], row["window_end"],
                                 other["window_start"], other["window_end"]):
            raise ApiError("ERR_ROTATION_SLOT_OVERLAP")

    stamp_new(row)
    insert("call_rotation_slots", row)
    svc.recompute_coverage_posture(contract)
    return ok(serialize.slot(row), 201)


@bp.get("/call-rotation-slots/<sid>")
@endpoint(SLOT_READ)
def read_slot(actor, sid):
    return ok(serialize.slot(svc.get_slot(sid)))


@bp.get("/call-rotation-slots")
@endpoint(SLOT_READ)
def list_slots(actor):
    limit, offset = V.pagination()
    rows = ordered("call_rotation_slots")
    for key in ("contract_id", "perfusionist_id", "slot_type", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    return ok_list([serialize.slot(r) for r in V.page(rows, limit, offset)],
                   limit, offset, len(rows))


@bp.post("/_clock/set_current_utc")
@endpoint([ROLE_CONTRACT_ADMIN])
def set_clock(actor):
    body = V.payload()
    V.require(body, "current_utc")
    target = V.vdt(body, "current_utc", required=True)
    if target < db.now():
        raise ApiError("ERR_CLOCK_NOT_MONOTONIC")
    lapsed, relief, contracts = svc.advance_clock(target)
    return ok({
        "current_utc": iso_instant(db.now()),
        "lapsed_certification_count": lapsed,
        "relief_pending_run_count": relief,
        "recomputed_contract_count": contracts,
    })
