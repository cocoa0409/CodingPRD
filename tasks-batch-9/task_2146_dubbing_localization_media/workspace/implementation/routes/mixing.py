"""Mix jobs: open, stem-check, mix, conform."""
from flask import Blueprint, request

import calc
from auth import ALL_ROLES, auth
from domain import (check_order_open, get_mix_job, get_order, live_assignments,
                    order_cut, order_spec, rows_where)
from errors import ApiError
from responses import created, ok, paged
from store import db, new_row, serialize, touch
from validate import body, v_bool, v_enum, v_number

bp = Blueprint("mixing", __name__)

STEM_LAYOUTS = ("STEREO_ME", "FIVE_ONE_ME")
MIX_LIVE_STATES = ("PROPOSED", "HOLD_REQUESTED", "HELD", "CONFIRMED", "RECORDED")


def _stamp_conformance(job, order):
    spec = order_spec(order)
    cut = order_cut(order)
    character_count = 0
    if cut is not None:
        character_count = len([c for c in db.characters.values()
                               if c["title_id"] == cut["title_id"]])
    recorded_count = len([a for a in live_assignments(order["id"])
                          if a["casting_status"] == "RECORDED"])
    job["conformance_index"] = calc.conformance_index(
        job["loudness_lufs"], spec["loudness_target_lufs"], job["me_stem_present"],
        job["stem_layout"], spec["stem_layout"], character_count, recorded_count)


@bp.post("/mix-jobs")
@auth("MixEngineer")
def create_mix_job():
    data = body()
    order = get_order(data.get("order_id"))                       # rung 7
    stem_layout = v_enum(data, "stem_layout", STEM_LAYOUTS)       # rung 8
    me_stem_present = v_bool(data, "me_stem_present", required=False, default=False)
    check_order_open(order)                                       # rung 10
    recorded = [a for a in live_assignments(order["id"]) if a["casting_status"] == "RECORDED"]
    if not recorded:                                              # rung 27
        raise ApiError("ERR_NO_RECORDED_CAST")

    row = new_row({
        "order_id": order["id"],
        "status": "QUEUED",
        "stem_layout": stem_layout,
        "me_stem_present": me_stem_present,
        "loudness_lufs": None,
        "mix_round": 1,
        "conformance_index": None,
    })
    db.mix_jobs[row["id"]] = row
    return created(serialize(row))


@bp.get("/mix-jobs/<mix_job_id>")
@auth(*ALL_ROLES)
def read_mix_job(mix_job_id):
    return ok(serialize(get_mix_job(mix_job_id)))


@bp.get("/mix-jobs")
@auth(*ALL_ROLES)
def list_mix_jobs():
    rows = list(db.mix_jobs.values())
    for key in ("order_id", "status"):
        value = request.args.get(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    return paged(rows, serialize)


@bp.post("/mix-jobs/<mix_job_id>/stem-check")
@auth("MixEngineer")
def stem_check(mix_job_id):
    job = get_mix_job(mix_job_id)
    order = db.orders[job["order_id"]]
    if job["status"] != "QUEUED":                                 # rung 11
        raise ApiError("ERR_INVALID_STATE")
    spec = order_spec(order)                                      # rung 21
    if not job["me_stem_present"] or job["stem_layout"] != spec["stem_layout"]:
        raise ApiError("ERR_STEM_LAYOUT_MISMATCH")
    job["status"] = "STEM_CHECKED"
    touch(job)
    return ok(serialize(job))


@bp.post("/mix-jobs/<mix_job_id>/mix")
@auth("MixEngineer")
def mix(mix_job_id):
    job = get_mix_job(mix_job_id)
    data = body()
    loudness = v_number(data, "loudness_lufs")                    # rung 8
    order = db.orders[job["order_id"]]
    if job["status"] != "STEM_CHECKED":                           # rung 11
        raise ApiError("ERR_INVALID_STATE")
    for assignment in live_assignments(order["id"]):              # rung 28
        if assignment["casting_status"] in MIX_LIVE_STATES and assignment["casting_status"] != "RECORDED":
            raise ApiError("ERR_CAST_NOT_FULLY_RECORDED")

    job["loudness_lufs"] = loudness
    _stamp_conformance(job, order)
    job["status"] = "MIXED"
    touch(job)
    if order["status"] in ("RECORDING", "RECALLED"):
        order["status"] = "MIXING"
        touch(order)
    return ok(serialize(job))


@bp.post("/mix-jobs/<mix_job_id>/conform")
@auth("MixEngineer")
def conform(mix_job_id):
    job = get_mix_job(mix_job_id)
    order = db.orders[job["order_id"]]
    if job["status"] != "MIXED":                                  # rung 11
        raise ApiError("ERR_INVALID_STATE")
    index = job["conformance_index"]                              # rung 30
    if index is None or calc.dec(index) < calc.MIN_CONFORMANCE_INDEX:
        raise ApiError("ERR_CONFORMANCE_BELOW_MIN")
    job["status"] = "CONFORMED"
    touch(job)
    if order["status"] == "MIXING":
        order["status"] = "QC"
        touch(order)
    return ok(serialize(job))
