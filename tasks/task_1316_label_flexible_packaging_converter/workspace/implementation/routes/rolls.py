"""RewindRoll endpoints: recording and judgment (PRD 3.7)."""
from flask import Blueprint

from db import DB, new_id, now_iso
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    get_job,
    get_roll,
    maybe_advance_to_rewound,
    sorted_created,
    touch,
)
from util import as_int, body, pagination_args, reject_unknown, required

bp = Blueprint("rolls", __name__)

_ROLL_FIELDS = {"roll_seq", "label_count", "splice_count"}


@bp.post("/label-jobs/jobs/<job_id>/rewind-rolls")
def record_roll(job_id):
    auth(["PressOperator"])
    job = get_job(job_id)
    data = body()
    reject_unknown(data, _ROLL_FIELDS)
    roll_seq = as_int(required(data, "roll_seq"), "roll_seq")
    label_count = as_int(required(data, "label_count"), "label_count")
    splice_count = as_int(required(data, "splice_count"), "splice_count")
    if job["status"] != "PRINTED":
        raise ApiError(
            "ERR_JOB_NOT_PRINTED", 409, "recording a roll requires job in PRINTED"
        )
    existing = [r for r in DB["rolls"].values() if r["job_id"] == job_id]
    if len(existing) >= job["rewind_max_rolls"]:
        raise ApiError(
            "ERR_ROLL_LIMIT_EXCEEDED",
            422,
            "recording another roll would exceed rewind_max_rolls",
        )
    ts = now_iso()
    roll = {
        "id": new_id(),
        "job_id": job_id,
        "roll_seq": roll_seq,
        "label_count": label_count,
        "splice_count": splice_count,
        "status": "WOUND",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    DB["rolls"][roll["id"]] = roll
    return ok(roll, 201)


@bp.get("/label-jobs/jobs/<job_id>/rewind-rolls")
def list_rolls(job_id):
    auth(ALL_ROLES)
    get_job(job_id)
    limit, offset = pagination_args()
    items = sorted_created(r for r in DB["rolls"].values() if r["job_id"] == job_id)
    return ok_list(items[offset : offset + limit], len(items), limit, offset)


@bp.post("/label-jobs/jobs/<job_id>/rewind-rolls/<roll_id>/accept")
def accept_roll(job_id, roll_id):
    auth(["QualityManager"])
    job = get_job(job_id)
    roll = get_roll(job_id, roll_id)
    data = body()
    reject_unknown(data, set())
    if roll["status"] != "WOUND":
        raise ApiError(
            "ERR_ROLL_ALREADY_JUDGED", 409, "accept requires roll status WOUND"
        )
    if job["status"] != "PRINTED":
        raise ApiError(
            "ERR_JOB_NOT_PRINTED", 409, "accepting a roll requires job in PRINTED"
        )
    if roll["splice_count"] > job["max_splices_per_roll"]:
        raise ApiError(
            "ERR_SPLICE_LIMIT_EXCEEDED",
            422,
            "roll splice_count exceeds the job's max_splices_per_roll",
        )
    roll["status"] = "ACCEPTED"
    touch(roll)
    maybe_advance_to_rewound(job)
    return ok(roll)


@bp.post("/label-jobs/jobs/<job_id>/rewind-rolls/<roll_id>/reject")
def reject_roll(job_id, roll_id):
    auth(["QualityManager"])
    job = get_job(job_id)
    roll = get_roll(job_id, roll_id)
    data = body()
    reject_unknown(data, set())
    if roll["status"] != "WOUND":
        raise ApiError(
            "ERR_ROLL_ALREADY_JUDGED", 409, "reject requires roll status WOUND"
        )
    if job["status"] != "PRINTED":
        raise ApiError(
            "ERR_JOB_NOT_PRINTED", 409, "rejecting a roll requires job in PRINTED"
        )
    roll["status"] = "REJECTED"
    touch(roll)
    maybe_advance_to_rewound(job)
    return ok(roll)
