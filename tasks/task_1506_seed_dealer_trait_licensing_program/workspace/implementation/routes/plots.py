"""PlotTrial endpoints: planning with occupancy overlap, field execution,
publication with the replication gate."""

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_PLOT_WINDOW_OVERLAP,
    ERR_INSUFFICIENT_PLOT_REPLICATIONS,
)
from middleware import authenticate
from response import success_obj, success_list
from routes import make_blueprint
from util import body_json, check_shape, pagination_params, paginate, apply_filters, require_fk, exist_body_fks, dt_of

bp = make_blueprint("plots")

ALL_ROLES = ["DealerAdmin", "SalesRep", "Agronomist", "Grower", "ClaimsAdjuster"]
OCCUPYING = ("PLANNED", "PLANTED", "HARVESTED")


@bp.post("/plot-trials")
def create_trial():
    authenticate(["Agronomist"])
    body = body_json()
    exist_body_fks(body, {
        "program_id": ("programs", "program"),
        "variety_id": ("varieties", "variety"),
        "field_id": ("fields", "field"),
    })
    check_shape(body, {
        "program_id": {"type": "string", "required": True},
        "variety_id": {"type": "string", "required": True},
        "field_id": {"type": "string", "required": True},
        "planting_date": {"type": "datetime", "required": True},
        "expected_harvest_date": {"type": "datetime", "required": True},
        "replication_index": {"type": "integer", "required": True, "min": 1},
    })
    planting = dt_of(body, "planting_date")
    harvest = dt_of(body, "expected_harvest_date")
    if not (harvest > planting):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_harvest_date must be after planting_date")
    for other in db.all_of("plot_trials"):
        if other["field_id"] != body["field_id"] or other["status"] not in OCCUPYING:
            continue
        o_start = dt_of(other, "planting_date")
        o_end = dt_of(other, "expected_harvest_date")
        # Half-open intervals [start, end): overlap iff start < other_end and other_start < end.
        if planting < o_end and o_start < harvest:
            raise ApiError(ERR_PLOT_WINDOW_OVERLAP, 409, "plot occupancy interval overlaps an existing trial on the field")
    trial = db.new_entity("plot_trials", {
        "program_id": body["program_id"],
        "variety_id": body["variety_id"],
        "field_id": body["field_id"],
        "planting_date": body["planting_date"],
        "expected_harvest_date": body["expected_harvest_date"],
        "replication_index": body["replication_index"],
        "yield_bu_per_acre": None,
        "moisture_pct": None,
        "actual_harvest_date": None,
        "status": "PLANNED",
    })
    return success_obj(db.public(trial), 201)


@bp.get("/plot-trials/<tid>")
def get_trial(tid):
    authenticate(ALL_ROLES)
    return success_obj(db.public(require_fk("plot_trials", tid, "plot trial")), 200)


@bp.get("/plot-trials")
def list_trials():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("plot_trials"), ["program_id", "variety_id", "field_id", "status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(t) for t in page], limit, offset, total, has_more)


@bp.post("/plot-trials/<tid>/record_planting")
def record_planting(tid):
    authenticate(["Agronomist"])
    trial = require_fk("plot_trials", tid, "plot trial")
    if trial["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a PLANNED trial can be marked planted")
    trial["status"] = "PLANTED"
    db.touch(trial)
    return success_obj(db.public(trial), 200)


@bp.post("/plot-trials/<tid>/record_harvest")
def record_harvest(tid):
    authenticate(["Agronomist"])
    trial = require_fk("plot_trials", tid, "plot trial")
    body = body_json()
    check_shape(body, {
        "yield_bu_per_acre": {"type": "number", "required": True},
        "moisture_pct": {"type": "number", "required": True},
    })
    if trial["status"] != "PLANTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a PLANTED trial can be harvested")
    trial["yield_bu_per_acre"] = body["yield_bu_per_acre"]
    trial["moisture_pct"] = body["moisture_pct"]
    trial["actual_harvest_date"] = db.fmt_ts(db.now())
    trial["status"] = "HARVESTED"
    db.touch(trial)
    return success_obj(db.public(trial), 200)


@bp.post("/plot-trials/<tid>/publish")
def publish_trial(tid):
    authenticate(["Agronomist", "DealerAdmin"])
    trial = require_fk("plot_trials", tid, "plot trial")
    if trial["status"] != "HARVESTED":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a HARVESTED trial can be published")
    program = db.get("programs", trial["program_id"])
    count = sum(
        1 for t in db.all_of("plot_trials")
        if t["program_id"] == trial["program_id"]
        and t["variety_id"] == trial["variety_id"]
        and t["status"] in ("HARVESTED", "PUBLISHED")
    )
    if program is None or count < program["min_plot_replications"]:
        raise ApiError(ERR_INSUFFICIENT_PLOT_REPLICATIONS, 409, "insufficient harvested/published replications for the variety")
    trial["status"] = "PUBLISHED"
    db.touch(trial)
    return success_obj(db.public(trial), 200)


@bp.post("/plot-trials/<tid>/discard")
def discard_trial(tid):
    authenticate(["Agronomist"])
    trial = require_fk("plot_trials", tid, "plot trial")
    if trial["status"] not in ("PLANNED", "PLANTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409, "only a PLANNED or PLANTED trial can be discarded")
    trial["status"] = "DISCARDED"
    db.touch(trial)
    return success_obj(db.public(trial), 200)
