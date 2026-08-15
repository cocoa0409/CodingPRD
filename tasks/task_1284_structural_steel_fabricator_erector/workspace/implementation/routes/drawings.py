"""Shop drawing endpoints: create/submit/decide/revise + supersede cascade."""

from flask import Blueprint

import domain
from envelope import ok_object
from errors import (
    ApiError,
    ERR_DRAWING_NOT_UNIQUE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SELF_APPROVAL_FORBIDDEN,
    ERR_STALE_VERSION,
)
from store import new_record, store, touch, public
from validate import authenticate, get_body, req_enum, req_int, req_str, require_role
from . import list_response

bp = Blueprint("drawings", __name__)

DETAILER = {"DETAILER"}
EOR = {"EOR"}
READERS = {"FABRICATOR_ADMIN", "DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"}


def view(d):
    return public(d)


def get_drawing_or_404(did):
    d = store.drawings.get(did)
    if d is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Shop drawing not found.")
    return d


@bp.post("/shop-drawings")
def create_drawing():
    uid, role = authenticate()
    require_role(role, DETAILER)
    body = get_body()
    # Rung 3: body FK existence (when supplied)
    job_id = body.get("job_id")
    if job_id is not None and job_id not in store.jobs:
        raise ApiError(ERR_NOT_FOUND, 404, "Job not found.")
    # Rung 4: shape
    job_id = req_str(body, "job_id")
    drawing_number = req_str(body, "drawing_number")
    # Rung 9: (job_id, drawing_number, revision) unique
    if any(
        d
        for d in store.drawings.values()
        if d["job_id"] == job_id and d["drawing_number"] == drawing_number and d["revision"] == 1
    ):
        raise ApiError(
            ERR_DRAWING_NOT_UNIQUE,
            409,
            "A drawing with this job_id, drawing_number and revision already exists.",
        )
    d = new_record()
    d.update(
        {
            "job_id": job_id,
            "drawing_number": drawing_number,
            "revision": 1,
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "decided_by_user_id": None,
            "supersedes_id": None,
        }
    )
    store.drawings[d["id"]] = d
    return ok_object(view(d), 201)


@bp.get("/shop-drawings")
def list_drawings():
    uid, role = authenticate()
    require_role(role, READERS)
    return list_response(
        store.drawings.values(),
        view,
        [("job_id", "job_id"), ("supersedes_id", "supersedes_id"), ("status", "status")],
    )


@bp.get("/shop-drawings/<did>")
def get_drawing(did):
    uid, role = authenticate()
    require_role(role, READERS)
    return ok_object(view(get_drawing_or_404(did)))


@bp.post("/shop-drawings/<did>/submit")
def submit_drawing(did):
    uid, role = authenticate()
    require_role(role, DETAILER)
    d = get_drawing_or_404(did)
    if d["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Drawing must be DRAFT to submit.")
    d["status"] = "SUBMITTED"
    d["submitted_by_user_id"] = uid
    touch(d)
    return ok_object(view(d))


@bp.post("/shop-drawings/<did>/decide")
def decide_drawing(did):
    uid, role = authenticate()
    require_role(role, EOR)
    d = get_drawing_or_404(did)
    body = get_body()
    decision = req_enum(body, "decision", ("APPROVE", "REJECT"))
    if d["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Drawing must be SUBMITTED to decide.")
    # Rung 7: segregation — the decider must not be the submitter
    if uid == d["submitted_by_user_id"]:
        raise ApiError(
            ERR_SELF_APPROVAL_FORBIDDEN, 409, "The EOR may not decide a drawing they submitted."
        )
    d["decided_by_user_id"] = uid
    if decision == "APPROVE":
        d["status"] = "APPROVED"
        touch(d)
        domain.supersede_cascade(d)
    else:
        d["status"] = "REJECTED"
        touch(d)
    return ok_object(view(d))


@bp.post("/shop-drawings/<did>/revise")
def revise_drawing(did):
    uid, role = authenticate()
    require_role(role, DETAILER)
    src = get_drawing_or_404(did)
    body = get_body()
    expected = req_int(body, "expected_drawing_version")
    # Rung 5: OCC on the source drawing version
    if expected != src["version"]:
        raise ApiError(
            ERR_STALE_VERSION, 412, "expected_drawing_version does not match current version."
        )
    # Rung 6: revise allowed only from APPROVED or REJECTED
    if src["status"] not in ("APPROVED", "REJECTED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Only an APPROVED or REJECTED drawing can be revised.")
    new_revision = src["revision"] + 1
    # Rung 9: (job_id, drawing_number, revision) unique
    if any(
        d
        for d in store.drawings.values()
        if d["job_id"] == src["job_id"]
        and d["drawing_number"] == src["drawing_number"]
        and d["revision"] == new_revision
    ):
        raise ApiError(
            ERR_DRAWING_NOT_UNIQUE,
            409,
            "A drawing with this job_id, drawing_number and revision already exists.",
        )
    d = new_record()
    d.update(
        {
            "job_id": src["job_id"],
            "drawing_number": src["drawing_number"],
            "revision": new_revision,
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "decided_by_user_id": None,
            "supersedes_id": src["id"],
        }
    )
    store.drawings[d["id"]] = d
    touch(src)  # revising increments the source drawing's version by 1
    return ok_object(view(d), 201)
