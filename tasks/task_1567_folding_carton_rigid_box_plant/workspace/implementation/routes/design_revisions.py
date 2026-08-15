"""DesignRevision endpoints (PRD §3.3): OCC-guarded create-with-supersede."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_CUSTOMER_OWNERSHIP_MISMATCH,
    ERR_INVALID_STATE_TRANSITION,
    ERR_STALE_JOB_VERSION,
)
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    fk_exists,
    get_body,
    get_or_404,
    list_response,
    release_job_reservation,
    req_bool,
    req_int,
    req_str,
    ser_plain,
)
from util import touch

bp = Blueprint("design_revisions", __name__)


@bp.post("/plant/design-revisions")
def create_design_revision():
    authenticate(("StructuralDesigner",))
    data = get_body()
    fk_exists(db.jobs, data, "job_id")

    job_id = req_str(data, "job_id")
    expected_job_version = req_int(data, "expected_job_version")
    cad_ref = req_str(data, "cad_ref")
    blank_w_cin = req_int(data, "blank_w_cin", 1)
    blank_h_cin = req_int(data, "blank_h_cin", 1)
    grain_rotation_allowed = req_bool(data, "grain_rotation_allowed")

    job = db.jobs[job_id]
    if job["status"] != "ENGINEERING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Design revisions can only be created while the job is ENGINEERING")
    if expected_job_version != job["version"]:
        raise ApiError(ERR_STALE_JOB_VERSION, 412,
                       "expected_job_version %s does not match current job version %s"
                       % (expected_job_version, job["version"]))

    # CASCADE L1: prior non-SUPERSEDED revision of the job -> SUPERSEDED
    for prior in db.design_revisions.values():
        if prior["job_id"] == job_id and prior["status"] != "SUPERSEDED":
            was_brand_approved = prior["status"] == "BRAND_APPROVED"
            prior["status"] = "SUPERSEDED"
            touch(prior)
            # CASCADE L2/L3: unreachable in practice (creation requires ENGINEERING)
            # but implemented per the state machine table.
            if was_brand_approved and job["status"] == "PRESS_READY":
                job["status"] = "ENGINEERING"
                release_job_reservation(job, clear_stock_ref=True)

    existing = [r["revision_number"] for r in db.design_revisions.values()
                if r["job_id"] == job_id]
    revision_number = (max(existing) + 1) if existing else 1

    rec = db.new_record()
    rec.update({
        "job_id": job_id,
        "cad_ref": cad_ref,
        "blank_w_cin": blank_w_cin,
        "blank_h_cin": blank_h_cin,
        "grain_rotation_allowed": grain_rotation_allowed,
        "revision_number": revision_number,
        "status": "DRAFT",
    })
    db.design_revisions[rec["id"]] = rec

    touch(job)  # create-with-supersede increments Job.version by 1
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/design-revisions")
def list_design_revisions():
    authenticate(ALL_ROLES)
    return list_response(
        db.design_revisions.values(),
        ser_plain,
        [("job_id", "job_id", "str"), ("status", "status", "str")],
    )


@bp.get("/plant/design-revisions/<revisionId>")
def get_design_revision(revisionId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.design_revisions, revisionId)))


@bp.post("/plant/design-revisions/<revisionId>/make-sample")
def make_sample(revisionId):
    authenticate(("StructuralDesigner",))
    rec = get_or_404(db.design_revisions, revisionId)
    job = db.jobs[rec["job_id"]]
    if rec["status"] != "DRAFT" or job["status"] != "ENGINEERING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "make-sample requires a DRAFT revision of an ENGINEERING job")
    rec["status"] = "SAMPLE_MADE"
    touch(rec)
    return ok_object(ser_plain(rec))


def _brand_adjudicate(revisionId, to_status):
    user_id, _role = authenticate(("BrandQuality",))
    rec = get_or_404(db.design_revisions, revisionId)
    job = db.jobs[rec["job_id"]]
    if user_id != job["customer_id"]:
        raise ApiError(ERR_CUSTOMER_OWNERSHIP_MISMATCH, 403,
                       "X-User-ID must equal the job's customer_id")
    if rec["status"] != "SAMPLE_MADE":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a SAMPLE_MADE revision can be adjudicated")
    rec["status"] = to_status
    touch(rec)
    return ok_object(ser_plain(rec))


@bp.post("/plant/design-revisions/<revisionId>/brand-accept")
def brand_accept(revisionId):
    return _brand_adjudicate(revisionId, "BRAND_APPROVED")


@bp.post("/plant/design-revisions/<revisionId>/brand-reject")
def brand_reject(revisionId):
    return _brand_adjudicate(revisionId, "DRAFT")
