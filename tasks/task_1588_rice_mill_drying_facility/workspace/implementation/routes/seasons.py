"""HarvestSeason endpoints (PRD §3.1)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_SEASON_STATE,
    ERR_SEASON_REOPEN_BLOCKED, ERR_UNRESOLVED_INTAKE_WORK,
    ERR_ACTIVE_HOLD_BLOCKS_OPERATION, ERR_UNPAID_SETTLEMENTS_EXIST,
    ERR_OPEN_BYPRODUCT_ORDERS,
)
from middleware import authorized, ALL_ROLES
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import new_id, next_seq, parse_dt, fmt_dt, DEFAULT_CLOCK_ISO, D
from validate import get_body, req_str, req_date, req_int, req_datetime

bp = Blueprint("seasons", __name__)


@bp.route("/mill/seasons", methods=["POST"])
def create_season():
    authorized(["MillAdmin"])
    body = get_body()
    name = req_str(body, "name")
    start = req_date(body, "intake_start_date")
    end = req_date(body, "intake_end_date")
    cap = req_int(body, "spot_daily_cap", non_negative=True)
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "name": name,
        "intake_start_date": start,
        "intake_end_date": end,
        "spot_daily_cap": cap,
        "current_clock_iso": DEFAULT_CLOCK_ISO,  # client-supplied clock ignored
        "status": "SETUP",
    }
    core.touch_new(rec)
    db["seasons"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/mill/seasons", methods=["GET"])
def list_seasons():
    return list_endpoint("seasons", ["status"])


@bp.route("/mill/seasons/<sid>", methods=["GET"])
def get_season(sid):
    return get_endpoint("seasons", sid)


def _transition(sid, from_status, to_status):
    authorized(["MillAdmin"])
    season = require_resource("seasons", sid)
    if season["status"] != from_status:
        raise_error(ERR_INVALID_SEASON_STATE,
                    f"season status {season['status']} does not allow this transition")
    season["status"] = to_status
    core.bump(season)
    return success_object(public(season))


@bp.route("/mill/seasons/<sid>/open-intake", methods=["POST"])
def open_intake(sid):
    return _transition(sid, "SETUP", "INTAKE_OPEN")


@bp.route("/mill/seasons/<sid>/close-intake", methods=["POST"])
def close_intake(sid):
    return _transition(sid, "INTAKE_OPEN", "INTAKE_CLOSED")


@bp.route("/mill/seasons/<sid>/reopen-intake", methods=["POST"])
def reopen_intake(sid):
    authorized(["MillAdmin"])
    season = require_resource("seasons", sid)
    if season["status"] != "INTAKE_CLOSED":
        raise_error(ERR_INVALID_SEASON_STATE,
                    f"season status {season['status']} does not allow reopen-intake")
    for s in db["settlements"].values():
        if s["season_id"] == sid and s["status"] in ("PROVISIONAL_ISSUED", "APPROVED", "PAID"):
            raise_error(ERR_SEASON_REOPEN_BLOCKED,
                        "a settlement in this season has advanced past DRAFT")
    season["status"] = "INTAKE_OPEN"
    core.bump(season)
    return success_object(public(season))


@bp.route("/mill/seasons/<sid>/begin-settlement-review", methods=["POST"])
def begin_settlement_review(sid):
    authorized(["MillAdmin"])
    season = require_resource("seasons", sid)
    if season["status"] != "INTAKE_CLOSED":
        raise_error(ERR_INVALID_SEASON_STATE,
                    f"season status {season['status']} does not allow begin-settlement-review")
    for lot in db["lots"].values():
        if lot["season_id"] == sid and lot["status"] in ("WEIGHED", "GRADED"):
            raise_error(ERR_UNRESOLVED_INTAKE_WORK,
                        "lots still in WEIGHED or GRADED status")
    for r in db["drying_runs"].values():
        if r["season_id"] == sid and r["status"] == "PLANNED":
            raise_error(ERR_UNRESOLVED_INTAKE_WORK, "a drying run is still PLANNED")
    for r in db["mill_runs"].values():
        if r["season_id"] == sid and r["status"] == "IN_PROCESS":
            raise_error(ERR_UNRESOLVED_INTAKE_WORK, "a mill run is IN_PROCESS")
    if core.any_active_hold_in_season(sid):
        raise_error(ERR_ACTIVE_HOLD_BLOCKS_OPERATION,
                    "an ACTIVE food-safety hold blocks settlement review")
    season["status"] = "SETTLEMENT_REVIEW"
    core.bump(season)
    return success_object(public(season))


@bp.route("/mill/seasons/<sid>/settle", methods=["POST"])
def settle_season(sid):
    authorized(["MillAdmin"])
    season = require_resource("seasons", sid)
    if season["status"] != "SETTLEMENT_REVIEW":
        raise_error(ERR_INVALID_SEASON_STATE,
                    f"season status {season['status']} does not allow settle")
    for s in db["settlements"].values():
        if s["season_id"] == sid and s["status"] != "PAID":
            raise_error(ERR_UNPAID_SETTLEMENTS_EXIST,
                        "a settlement in this season is not PAID")
    for o in db["byproduct_orders"].values():
        if o["season_id"] == sid and o["status"] in ("OPEN", "RESERVED"):
            raise_error(ERR_OPEN_BYPRODUCT_ORDERS,
                        "a byproduct order is still OPEN or RESERVED")
    # Cascade: under-delivered contracts default.
    for c in db["contracts"].values():
        if (c["season_id"] == sid and c["status"] in ("OPEN", "PARTIALLY_FULFILLED")
                and D(c["fulfilled_cwt"]) < D(c["contracted_cwt"])):
            c["status"] = "DEFAULTED"
            core.bump(c)
    season["status"] = "SETTLED"
    core.bump(season)
    return success_object(public(season))


@bp.route("/mill/seasons/<sid>/clock/set", methods=["POST"])
def set_clock(sid):
    authorized(["MillAdmin"])
    body = get_body()
    to_iso = req_datetime(body, "to_iso8601")
    season = require_resource("seasons", sid)
    season["current_clock_iso"] = fmt_dt(parse_dt(to_iso))
    core.bump(season)
    return success_object(public(season))


@bp.route("/mill/seasons/<sid>/byproduct-inventory", methods=["GET"])
def byproduct_inventory(sid):
    authorized(ALL_ROLES)
    require_resource("seasons", sid)
    return success_object(core.season_inventory(sid))
