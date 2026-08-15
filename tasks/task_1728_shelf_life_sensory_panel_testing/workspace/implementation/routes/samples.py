"""SampleUnit custody lifecycle and the retain sweep (PRD §3.3)."""
import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_SAMPLE_STATE,
    ERR_INVALID_SESSION_STATE,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import ser_unit
from util import body, opt_str, paginate, sort_created, touch

bp = Blueprint("samples", __name__)


def get_unit(unit_id):
    u = db.store["sample_units"].get(unit_id)
    if u is None:
        raise_err(ERR_NOT_FOUND, f"SampleUnit {unit_id} not found")
    return u


@bp.route("/sample-units", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_units():
    items = sort_created(db.store["sample_units"].values())
    for field in ("study_id", "arm_id", "chamber_id", "time_point_id",
                  "session_id", "status", "unit_purpose"):
        v = request.args.get(field)
        if v is not None:
            items = [u for u in items if u[field] == v]
    page, pagination = paginate(items)
    return respond_list([ser_unit(u) for u in page], pagination)


@bp.route("/sample-units/<unit_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_unit(unit_id):
    return respond(ser_unit(get_unit(unit_id)), 200)


@bp.route("/sample-units/<unit_id>/checkout", methods=["POST"])
@require_roles("PanelCoordinator")
def checkout_unit(unit_id):
    unit = get_unit(unit_id)
    b = body()
    session_id = opt_str(b, "session_id", default=None)
    if unit["status"] != "STORED":
        raise_err(ERR_INVALID_SAMPLE_STATE,
                  "checkout requires status STORED")
    # An EVALUATION unit must name a same-study session in PLANNED/OPEN;
    # omitting it or naming an ineligible session is ERR_INVALID_SESSION_STATE.
    if unit["unit_purpose"] == "EVALUATION" and session_id is None:
        raise_err(ERR_INVALID_SESSION_STATE,
                  "checkout of an EVALUATION unit requires a session_id")
    if session_id is not None:
        sess = db.store["sessions"].get(session_id)
        if (sess is None or sess["study_id"] != unit["study_id"]
                or sess["status"] not in ("PLANNED", "OPEN")):
            raise_err(ERR_INVALID_SESSION_STATE,
                      "session_id must reference an evaluation session of "
                      "the same study in PLANNED or OPEN")
    unit["status"] = "CHECKED_OUT"
    unit["session_id"] = session_id
    touch(unit)
    return respond(ser_unit(unit), 200)


@bp.route("/sample-units/<unit_id>/return", methods=["POST"])
@require_roles("PanelCoordinator")
def return_unit(unit_id):
    unit = get_unit(unit_id)
    if unit["status"] != "CHECKED_OUT":
        raise_err(ERR_INVALID_SAMPLE_STATE,
                  "return requires status CHECKED_OUT")
    unit["status"] = "STORED"
    unit["session_id"] = None
    touch(unit)
    return respond(ser_unit(unit), 200)


@bp.route("/sample-units/<unit_id>/consume", methods=["POST"])
@require_roles("PanelCoordinator")
def consume_unit(unit_id):
    unit = get_unit(unit_id)
    if unit["status"] != "CHECKED_OUT":
        raise_err(ERR_INVALID_SAMPLE_STATE,
                  "consume requires status CHECKED_OUT")
    chamber = db.store["chambers"][unit["chamber_id"]]
    unit["status"] = "CONSUMED"
    unit["session_id"] = None
    touch(unit)
    touch(chamber)  # occupancy decreased
    return respond(ser_unit(unit), 200)


@bp.route("/sample-units/<unit_id>/discard", methods=["POST"])
@require_roles("LabDirector")
def discard_unit_endpoint(unit_id):
    unit = get_unit(unit_id)
    if unit["status"] not in ("STORED", "CHECKED_OUT"):
        raise_err(ERR_INVALID_SAMPLE_STATE,
                  "discard requires status STORED or CHECKED_OUT")
    chamber = db.store["chambers"][unit["chamber_id"]]
    unit["status"] = "DISCARDED"
    unit["session_id"] = None
    touch(unit)
    touch(chamber)  # occupancy decreased
    return respond(ser_unit(unit), 200)


@bp.route("/retain-sweeps", methods=["POST"])
@require_roles("LabDirector")
def retain_sweep():
    now = clock.now()
    expired = []
    for unit in sort_created(db.store["sample_units"].values()):
        if (unit["unit_purpose"] == "RETAIN"
                and unit["status"] == "STORED"
                and unit["retention_until_utc"] is not None
                and unit["retention_until_utc"] < now):
            chamber = db.store["chambers"][unit["chamber_id"]]
            unit["status"] = "EXPIRED"
            touch(unit)
            touch(chamber)  # occupancy decreased
            expired.append(unit["id"])
    return respond({
        "expired_count": len(expired),
        "expired_unit_ids": expired,
    }, 200)
