"""Airspace approvals and TFR restrictions (PRD 3.4)."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import (
    cancel_slot_by_tfr,
    get_approval,
    get_route,
    get_tfr,
    new_record,
    pub,
    sorted_created,
    touch,
)
from util import as_bool, as_date, as_iso_dt, as_str, body, pagination_args, required

bp = Blueprint("compliance", __name__, url_prefix="/btaa")

APPROVAL_READ = ["PlatformAdmin", "Dispatcher", "ComplianceOfficer", "Client", "Pilot"]


def _list(recs, filters):
    items = sorted_created(recs)
    for key, val in filters.items():
        if val is not None:
            items = [r for r in items if r.get(key) == val]
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([pub(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# Airspace approvals
# ---------------------------------------------------------------------------
@bp.post("/routes/<rid>/airspace_approvals")
def create_approval(rid):
    auth(["Dispatcher", "PlatformAdmin"])
    route = get_route(rid)
    data = body()
    date_local, date_d = as_date(required(data, "date_local"), "date_local")
    ws_raw, ws_dt = as_iso_dt(required(data, "window_start_utc"), "window_start_utc")
    we_raw, we_dt = as_iso_dt(required(data, "window_end_utc"), "window_end_utc")
    if not we_dt > ws_dt:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "window_end_utc must be strictly later than window_start_utc",
        )
    waiver = False
    if "stadium_tfr_waiver" in data and data["stadium_tfr_waiver"] is not None:
        waiver = as_bool(data["stadium_tfr_waiver"], "stadium_tfr_waiver")
    rec = new_record()
    rec.update(
        {
            "route_id": route["id"],
            "date_local": date_local,
            "window_start_utc": ws_raw,
            "window_end_utc": we_raw,
            "stadium_tfr_waiver": waiver,
            "status": "PENDING",
            "_window_start_dt": ws_dt,
            "_window_end_dt": we_dt,
            "_granted_by": None,
        }
    )
    DB["airspace_approvals"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.get("/routes/<rid>/airspace_approvals")
def list_approvals(rid):
    auth(APPROVAL_READ)
    route = get_route(rid)
    recs = [a for a in DB["airspace_approvals"].values() if a["route_id"] == route["id"]]
    return _list(
        recs,
        {
            "status": request.args.get("status"),
            "date_local": request.args.get("date_local"),
        },
    )


@bp.get("/airspace_approvals/<aid>")
def get_one_approval(aid):
    auth(APPROVAL_READ)
    return ok(pub(get_approval(aid)))


@bp.post("/airspace_approvals/<aid>/grant")
def grant_approval(aid):
    user_id, role = auth(["ComplianceOfficer"])
    a = get_approval(aid)
    if a["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "AirspaceApproval is not in a state permitting grant",
        )
    a["status"] = "GRANTED"
    # Record the granting officer for the segregation-of-duties rule (PRD 2.1).
    a["_granted_by"] = user_id
    touch(a)
    return ok(pub(a))


@bp.post("/airspace_approvals/<aid>/deny")
def deny_approval(aid):
    auth(["ComplianceOfficer"])
    a = get_approval(aid)
    if a["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "AirspaceApproval is not in a state permitting deny",
        )
    a["status"] = "DENIED"
    touch(a)
    return ok(pub(a))


@bp.post("/airspace_approvals/<aid>/revoke")
def revoke_approval(aid):
    auth(["ComplianceOfficer"])
    a = get_approval(aid)
    if a["status"] != "GRANTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "AirspaceApproval is not in a state permitting revoke",
        )
    a["status"] = "REVOKED"
    touch(a)
    # Cascade: every slot referencing this approval still in
    # BOOKED/SCHEDULED/WEATHER_HOLD -> CANCELLED_TFR (PRD 3.4).
    for s in list(DB["flight_slots"].values()):
        if s.get("airspace_approval_id") == a["id"] and s["status"] in (
            "BOOKED",
            "SCHEDULED",
            "WEATHER_HOLD",
        ):
            cancel_slot_by_tfr(s)
    return ok(pub(a))


# ---------------------------------------------------------------------------
# TFR restrictions
# ---------------------------------------------------------------------------
@bp.post("/tfr_restrictions")
def create_tfr():
    auth(["ComplianceOfficer", "PlatformAdmin"])
    data = body()
    route_id = as_str(required(data, "route_id"), "route_id")
    route = get_route(route_id)
    st_raw, st_dt = as_iso_dt(required(data, "starts_utc"), "starts_utc")
    en_raw, en_dt = as_iso_dt(required(data, "ends_utc"), "ends_utc")
    reason = as_str(required(data, "reason"), "reason")
    if not en_dt > st_dt:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "ends_utc must be strictly later than starts_utc",
        )
    rec = new_record()
    rec.update(
        {
            "route_id": route["id"],
            "starts_utc": st_raw,
            "ends_utc": en_raw,
            "reason": reason,
            "status": "PUBLISHED",
            "_starts_dt": st_dt,
            "_ends_dt": en_dt,
        }
    )
    DB["tfr_restrictions"][rec["id"]] = rec
    return ok(pub(rec), status=201)


@bp.get("/routes/<rid>/tfr_restrictions")
def list_tfrs(rid):
    auth(APPROVAL_READ)
    route = get_route(rid)
    recs = [t for t in DB["tfr_restrictions"].values() if t["route_id"] == route["id"]]
    return _list(recs, {"status": request.args.get("status")})


@bp.get("/tfr_restrictions/<tid>")
def get_one_tfr(tid):
    auth(APPROVAL_READ)
    return ok(pub(get_tfr(tid)))


@bp.post("/tfr_restrictions/<tid>/cancel")
def cancel_tfr(tid):
    auth(["ComplianceOfficer"])
    t = get_tfr(tid)
    if t["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "TFRRestriction is not in a state permitting cancel",
        )
    t["status"] = "CANCELLED"
    touch(t)
    return ok(pub(t))
