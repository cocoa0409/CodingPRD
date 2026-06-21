"""Interview endpoints (PRD §3.3)."""

from flask import Blueprint, request

import errors
from db import store, iso
from errors import err
from middleware import authenticate, require_roles, get_json, parse_pagination, paginate
from response import ok
from services import validate as v
from services.common import base_record, touch
from services.lookup import (get_family, get_caregiver, get_job_posting,
                             get_interview, sorted_by_created)
from services.serialize import interview_out

bp = Blueprint("interviews", __name__)

KINDS = {"PHONE", "VIDEO", "TRIAL"}
OUTCOMES = {"PASSED", "FAILED", "TRIAL_BOOKED"}


@bp.route("/marketplace/interviews", methods=["POST"])
def create_interview():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    body = get_json()
    job_posting_id = v.req_str(body, "job_posting_id")
    family_id = v.req_str(body, "family_id")
    caregiver_id = v.req_str(body, "caregiver_id")
    scheduled_start = v.req_datetime(body, "scheduled_start")
    scheduled_end = v.req_datetime(body, "scheduled_end")
    kind = v.req_enum(body, "kind", KINDS)

    if auth.is_family and auth.user_id != family_id:
        raise err(errors.ERR_FORBIDDEN, "Family may only schedule its own interviews")

    # Existence: path-then-body FK order. Body FKs left to right.
    get_job_posting(job_posting_id)
    get_family(family_id)
    get_caregiver(caregiver_id)

    # Interval ordering (priority 13).
    if not (scheduled_end > scheduled_start):
        raise err(errors.ERR_INVALID_INTERVAL, "scheduled_end must be after scheduled_start")

    rec = base_record()
    rec.update({
        "job_posting_id": job_posting_id,
        "family_id": family_id,
        "caregiver_id": caregiver_id,
        "scheduled_start_iso": iso(scheduled_start),
        "scheduled_end_iso": iso(scheduled_end),
        "kind": kind,
        "status": "SCHEDULED",
        "outcome_note": None,
    })
    store.interviews[rec["id"]] = rec
    return ok(interview_out(rec), status=201)


@bp.route("/marketplace/interviews/<iid>", methods=["GET"])
def get_one_interview(iid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    i = get_interview(iid)
    if auth.is_family and auth.user_id != i["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only read its own interviews")
    if auth.is_caregiver and auth.user_id != i["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only read its own interviews")
    return ok(interview_out(i), status=200)


@bp.route("/marketplace/interviews", methods=["GET"])
def list_interviews():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    limit, offset = parse_pagination()
    family_id = request.args.get("family_id")
    caregiver_id = request.args.get("caregiver_id")
    job_posting_id = request.args.get("job_posting_id")
    status = request.args.get("status")

    items = list(store.interviews.values())
    if auth.is_family:
        items = [i for i in items if i["family_id"] == auth.user_id]
    if auth.is_caregiver:
        items = [i for i in items if i["caregiver_id"] == auth.user_id]
    if family_id is not None:
        items = [i for i in items if i["family_id"] == family_id]
    if caregiver_id is not None:
        items = [i for i in items if i["caregiver_id"] == caregiver_id]
    if job_posting_id is not None:
        items = [i for i in items if i["job_posting_id"] == job_posting_id]
    if status is not None:
        items = [i for i in items if i["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([interview_out(i) for i in page], status=200, pagination=meta)


@bp.route("/marketplace/interviews/<iid>/decide", methods=["POST"])
def decide_interview(iid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    i = get_interview(iid)
    if auth.is_family and auth.user_id != i["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only decide its own interviews")
    body = get_json()
    outcome = v.req_enum(body, "outcome", OUTCOMES)
    note = v.opt_str(body, "outcome_note", default=None)

    status = i["status"]
    if outcome == "TRIAL_BOOKED":
        if status != "SCHEDULED":
            raise err(errors.ERR_INVALID_STATE, "TRIAL_BOOKED only from SCHEDULED")
        if i["kind"] != "TRIAL":
            raise err(errors.ERR_INVALID_STATE, "TRIAL_BOOKED requires kind==TRIAL")
        i["status"] = "TRIAL_BOOKED"
    elif outcome in {"PASSED", "FAILED"}:
        if status not in {"SCHEDULED", "TRIAL_BOOKED"}:
            raise err(errors.ERR_INVALID_STATE, "Decision not permitted from this state")
        i["status"] = outcome
    i["outcome_note"] = note
    touch(i)
    return ok(interview_out(i), status=200)


@bp.route("/marketplace/interviews/<iid>/cancel", methods=["POST"])
def cancel_interview(iid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    i = get_interview(iid)
    if auth.is_family and auth.user_id != i["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only cancel its own interviews")
    if i["status"] not in {"SCHEDULED", "TRIAL_BOOKED"}:
        raise err(errors.ERR_INVALID_STATE, "Interview not cancellable from this state")
    i["status"] = "CANCELLED"
    touch(i)
    return ok(interview_out(i), status=200)
