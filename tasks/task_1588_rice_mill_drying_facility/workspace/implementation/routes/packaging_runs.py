"""PackagingRun endpoints (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_LINE_SCHEDULE_CONFLICT,
    ERR_PACKAGING_RUN_INVALID_STATE, ERR_INSUFFICIENT_MILLED_RICE,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_endpoint, get_endpoint, public, require_resource
from services import core
from util import D, new_id, next_seq, parse_dt, fmt_dt
from validate import get_body, req_str, req_enum, req_num, req_int, req_datetime

bp = Blueprint("packaging_runs", __name__)

BUFFER = timedelta(minutes=core.CHANGEOVER_MINUTES)


@bp.route("/mill/packaging-runs", methods=["POST"])
def create_packaging_run():
    authorized(["MillSupervisor"])
    body = get_body()
    season_id = req_str(body, "season_id")
    line_id = req_enum(body, "line_id", ("LINE_1", "LINE_2"))
    brand_label = req_str(body, "brand_label")
    package_size = req_num(body, "package_size_kg", positive=True)
    units_planned = req_int(body, "units_planned", non_negative=True)
    starts_at = req_datetime(body, "starts_at")
    ends_at = req_datetime(body, "ends_at")
    starts = parse_dt(starts_at)
    ends = parse_dt(ends_at)
    if ends <= starts:
        raise_error(ERR_INVALID_REQUEST, "ends_at must be later than starts_at")
    require_resource("seasons", season_id)
    # 30-minute changeover buffer at both ends vs SCHEDULED runs on the same line.
    for other in db["packaging_runs"].values():
        if (other["season_id"] == season_id and other["line_id"] == line_id
                and other["status"] == "SCHEDULED"):
            o_start = parse_dt(other["starts_at"])
            o_end = parse_dt(other["ends_at"])
            if starts < o_end + BUFFER and o_start < ends + BUFFER:
                raise_error(ERR_LINE_SCHEDULE_CONFLICT,
                            "run conflicts with another scheduled run on this line")
    rec = {
        "id": new_id(),
        "_seq": next_seq(),
        "season_id": season_id,
        "line_id": line_id,
        "brand_label": brand_label,
        "package_size_kg": float(package_size),
        "units_planned": units_planned,
        "units_produced": None,
        "head_rice_consumed_cwt": None,
        "starts_at": fmt_dt(starts),
        "ends_at": fmt_dt(ends),
        "status": "SCHEDULED",
    }
    core.touch_new(rec)
    db["packaging_runs"][rec["id"]] = rec
    return success_object(public(rec), 201)


@bp.route("/mill/packaging-runs", methods=["GET"])
def list_packaging_runs():
    return list_endpoint("packaging_runs", ["season_id", "line_id", "status"])


@bp.route("/mill/packaging-runs/<rid>", methods=["GET"])
def get_packaging_run(rid):
    return get_endpoint("packaging_runs", rid)


@bp.route("/mill/packaging-runs/<rid>/complete", methods=["POST"])
def complete_packaging_run(rid):
    authorized(["MillSupervisor"])
    body = get_body()
    units_produced = req_int(body, "units_produced", non_negative=True)
    run = require_resource("packaging_runs", rid)
    if run["status"] != "SCHEDULED":
        raise_error(ERR_PACKAGING_RUN_INVALID_STATE,
                    f"complete requires SCHEDULED; run is {run['status']}")
    consumed = core.packaging_head_rice_cwt(units_produced, D(str(run["package_size_kg"])))
    inv = core.season_inventory(run["season_id"])
    if D(inv["HEAD_RICE"]["available_cwt"]) < consumed:
        raise_error(ERR_INSUFFICIENT_MILLED_RICE,
                    "head-rice inventory cannot cover this packaging run")
    run["units_produced"] = units_produced
    run["head_rice_consumed_cwt"] = consumed
    run["status"] = "COMPLETED"
    core.bump(run)
    return success_object(public(run))


@bp.route("/mill/packaging-runs/<rid>/cancel", methods=["POST"])
def cancel_packaging_run(rid):
    authorized(["MillSupervisor"])
    run = require_resource("packaging_runs", rid)
    if run["status"] != "SCHEDULED":
        raise_error(ERR_PACKAGING_RUN_INVALID_STATE,
                    f"cancel requires SCHEDULED; run is {run['status']}")
    run["status"] = "CANCELLED"
    core.bump(run)
    return success_object(public(run))
