"""Erection sequence endpoints."""

from flask import Blueprint

from envelope import ok_object
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_JOB_NOT_FABRICATING,
    ERR_NOT_FOUND,
    ERR_SEQUENCE_NUMBER_NOT_UNIQUE,
)
from store import new_record, store, touch, public
from validate import authenticate, get_body, req_int, req_str, require_role
from . import list_response

bp = Blueprint("sequences", __name__)

FOREMAN = {"FOREMAN"}
READERS = {"FABRICATOR_ADMIN", "DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"}


def view(s):
    return public(s)


def get_sequence_or_404(sid):
    s = store.sequences.get(sid)
    if s is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Erection sequence not found.")
    return s


@bp.post("/erection-sequences")
def create_sequence():
    uid, role = authenticate()
    require_role(role, FOREMAN)
    body = get_body()
    job_id = body.get("job_id")
    if job_id is not None and job_id not in store.jobs:
        raise ApiError(ERR_NOT_FOUND, 404, "Job not found.")
    job_id = req_str(body, "job_id")
    seq_number = req_int(body, "seq_number")
    if any(
        s
        for s in store.sequences.values()
        if s["job_id"] == job_id and s["seq_number"] == seq_number
    ):
        raise ApiError(
            ERR_SEQUENCE_NUMBER_NOT_UNIQUE, 409, "seq_number already exists within the job."
        )
    s = new_record()
    s.update({"job_id": job_id, "seq_number": seq_number, "status": "PLANNED"})
    store.sequences[s["id"]] = s
    return ok_object(view(s), 201)


@bp.get("/erection-sequences")
def list_sequences():
    uid, role = authenticate()
    require_role(role, READERS)
    return list_response(
        store.sequences.values(), view, [("job_id", "job_id"), ("status", "status")]
    )


@bp.get("/erection-sequences/<sid>")
def get_sequence(sid):
    uid, role = authenticate()
    require_role(role, READERS)
    return ok_object(view(get_sequence_or_404(sid)))


@bp.post("/erection-sequences/<sid>/release")
def release_sequence(sid):
    uid, role = authenticate()
    require_role(role, FOREMAN)
    s = get_sequence_or_404(sid)
    if s["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Sequence must be PLANNED to release.")
    # Rung 8: owning job must be FABRICATING or ERECTING
    job = store.jobs.get(s["job_id"])
    if job is None or job["status"] not in ("FABRICATING", "ERECTING"):
        raise ApiError(
            ERR_JOB_NOT_FABRICATING, 409, "Sequence release requires job FABRICATING or ERECTING."
        )
    s["status"] = "RELEASED"
    touch(s)
    return ok_object(view(s))
