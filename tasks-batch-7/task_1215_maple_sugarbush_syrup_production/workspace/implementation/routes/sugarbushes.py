"""Sugarbush endpoints."""

from flask import Blueprint, request

import db
from middleware import authenticate, require_role
from response import success_object, success_list
from util import (body_json, check_unknown_fields, require_fields, as_int, as_str,
                  parse_pagination, paginate)
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SEASON_NOT_OPEN,
                    ERR_SEASON_SUSPENDED, ERR_LEASE_NOT_ACTIVE, ERR_TAP_LINES_NOT_READY)
from services import core

bp = Blueprint("sugarbushes", __name__)

ALL_ROLES = {"SugarhouseManager", "FieldCrew", "SugarMaker", "CertInspector"}
MGR = {"SugarhouseManager"}


def get_bush_or_404(bid):
    b = db.sugarbushes.get(bid)
    if not b:
        raise_err(ERR_NOT_FOUND, f"sugarbush {bid} not found")
    return b


def _require_season_open_for_bush(bush):
    """Begin-tapping season gate: OPEN required; SUSPENDED -> ERR_SEASON_SUSPENDED."""
    season = db.seasons.get(bush["season_id"])
    if not season:
        raise_err(ERR_NOT_FOUND, f"season {bush['season_id']} not found")
    if season["status"] == "SUSPENDED":
        raise_err(ERR_SEASON_SUSPENDED, "season is SUSPENDED")
    if season["status"] != "OPEN":
        raise_err(ERR_SEASON_NOT_OPEN, f"season is {season['status']}, expected OPEN")
    return season


def _require_lease_active_for_bush(bush):
    if bush["active_lease_id"] is not None:
        lease = db.leases.get(bush["active_lease_id"])
        if not lease or lease["status"] != "ACTIVE":
            raise_err(ERR_LEASE_NOT_ACTIVE, "bush's lease is not ACTIVE")


@bp.post("/sugarhouse/sugarbushes")
def create_bush():
    caller = authenticate()
    require_role(caller, MGR)
    data = body_json()
    check_unknown_fields(data, {"season_id", "name", "tap_capacity"})
    require_fields(data, ["season_id", "name", "tap_capacity"])
    season_id = as_str(data["season_id"], "season_id")
    name = as_str(data["name"], "name")
    tap_capacity = as_int(data["tap_capacity"], "tap_capacity", minimum=1)
    if season_id not in db.seasons:
        raise_err(ERR_NOT_FOUND, f"season {season_id} not found")
    b = core.new_sugarbush(season_id, name, tap_capacity)
    db.sugarbushes[b["id"]] = b
    return success_object(core.ser_sugarbush(b), status=201)


@bp.get("/sugarhouse/sugarbushes/<bid>")
def get_bush(bid):
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    b = get_bush_or_404(bid)
    return success_object(core.ser_sugarbush(b))


@bp.get("/sugarhouse/sugarbushes")
def list_bushes():
    caller = authenticate()
    require_role(caller, ALL_ROLES)
    limit, offset = parse_pagination(request.args)
    season_id = request.args.get("season_id")
    active_lease_id = request.args.get("active_lease_id")
    status = request.args.get("status")
    rows = list(db.sugarbushes.values())
    if season_id is not None:
        rows = [r for r in rows if r["season_id"] == season_id]
    if active_lease_id is not None:
        rows = [r for r in rows if r["active_lease_id"] == active_lease_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    page, total = paginate(rows, limit, offset)
    return success_list([core.ser_sugarbush(r) for r in page], limit, offset, total)


@bp.post("/sugarhouse/sugarbushes/<bid>/begin-tapping")
def begin_tapping(bid):
    caller = authenticate()
    require_role(caller, MGR)
    b = get_bush_or_404(bid)
    if b["status"] != "PREP":
        raise_err(ERR_INVALID_STATE, f"sugarbush is {b['status']}, expected PREP")
    _require_season_open_for_bush(b)
    _require_lease_active_for_bush(b)
    b["status"] = "TAPPING"
    core.bump(b)
    return success_object(core.ser_sugarbush(b))


@bp.post("/sugarhouse/sugarbushes/<bid>/go-live")
def go_live(bid):
    caller = authenticate()
    require_role(caller, MGR)
    b = get_bush_or_404(bid)
    if b["status"] != "TAPPING":
        raise_err(ERR_INVALID_STATE, f"sugarbush is {b['status']}, expected TAPPING")
    non_pulled = [l for l in core.lines_of_bush(b["id"]) if l["status"] != "PULLED"]
    if not non_pulled:
        raise_err(ERR_TAP_LINES_NOT_READY, "no non-PULLED tap lines on this bush")
    for l in non_pulled:
        if l["status"] != "ACTIVE":
            raise_err(ERR_TAP_LINES_NOT_READY,
                      f"tap line {l['id']} is {l['status']}, expected ACTIVE")
    _require_lease_active_for_bush(b)
    b["status"] = "LIVE"
    core.bump(b)
    return success_object(core.ser_sugarbush(b))


@bp.post("/sugarhouse/sugarbushes/<bid>/shutdown")
def shutdown(bid):
    caller = authenticate()
    require_role(caller, MGR)
    b = get_bush_or_404(bid)
    if b["status"] not in ("TAPPING", "LIVE"):
        raise_err(ERR_INVALID_STATE,
                  f"sugarbush is {b['status']}, expected TAPPING or LIVE")
    core.shutdown_bush_cascade(b, bump_bush=True)
    return success_object(core.ser_sugarbush(b))
