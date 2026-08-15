"""EMR forecast snapshots (PRD 3.9): OCC-guarded immutable valuations."""

from flask import Blueprint, request

import db
from clock import CLOCK
from errors import ApiError
from middleware import auth, paginate, FORECAST_READ_ROLES
from response import ok, ok_list
from services import calc, core

bp = Blueprint("forecasts", __name__)


@bp.route("/safety/emr-forecasts", methods=["POST"])
def create_forecast():
    auth(["EHSAdmin", "SafetyManager"])
    body = core.body_json()
    program_id = core.req_str(body, "program_id")
    expected = core.req_int(body, "expected_program_version")
    as_of = core.opt_datetime(body, "as_of", default=None)
    p = core.get_or_404("programs", program_id, "SafetyProgram")
    if expected != p["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_program_version does not match the program version")
    if as_of is None:
        as_of = CLOCK.now()
    snap = calc.emr_snapshot(p, as_of)
    f = core.stamp_new({
        "id": core.new_id(),
        "program_id": p["id"],
        "as_of": as_of,
        **snap,
    }, with_version=False)
    db.DB["forecasts"][f["id"]] = f
    # Successful forecast creation advances the program version by one (PRD 2.8).
    core.touch(p)
    return ok(core.forecast_view(f), 201)


@bp.route("/safety/emr-forecasts", methods=["GET"])
def list_forecasts():
    auth(FORECAST_READ_ROLES)
    program_id = request.args.get("program_id")
    items = list(db.DB["forecasts"].values())
    if program_id is not None:
        items = [f for f in items if f["program_id"] == program_id]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.forecast_view(f) for f in page], total, limit, offset)


@bp.route("/safety/emr-forecasts/<fid>", methods=["GET"])
def get_forecast(fid):
    auth(FORECAST_READ_ROLES)
    f = core.get_or_404("forecasts", fid, "EMRForecast")
    return ok(core.forecast_view(f))
