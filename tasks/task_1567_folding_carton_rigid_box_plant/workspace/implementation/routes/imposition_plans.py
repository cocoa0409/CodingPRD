"""ImpositionPlan endpoints (PRD §3.3): nesting yield, OCC-guarded lock."""

from flask import Blueprint

import calc
import db
from errors import (
    ApiError,
    ERR_INVALID_STATE_TRANSITION,
    ERR_LAYOUT_IMPOSSIBLE,
    ERR_REVISION_JOB_MISMATCH,
    ERR_REVISION_SUPERSEDED,
    ERR_STALE_JOB_VERSION,
)
from middleware import ALL_ROLES, authenticate
from response import ok_object
from routes.common import (
    fk_exists,
    get_body,
    get_or_404,
    list_response,
    req_int,
    req_str,
    ser_plain,
)
from util import touch

bp = Blueprint("imposition_plans", __name__)

# Job states from which a LOCKED plan may no longer be manually superseded
PRODUCTION_OR_LATER = ("IN_PRODUCTION", "FINISHING", "FINISHED", "COMPLETE", "CANCELLED")


@bp.post("/plant/imposition-plans")
def create_imposition_plan():
    authenticate(("StructuralDesigner",))
    data = get_body()
    fk_exists(db.jobs, data, "job_id")
    fk_exists(db.design_revisions, data, "design_revision_id")

    job_id = req_str(data, "job_id")
    design_revision_id = req_str(data, "design_revision_id")
    sheet_w_cin = req_int(data, "sheet_w_cin", 1)
    sheet_h_cin = req_int(data, "sheet_h_cin", 1)
    gutter_cin = req_int(data, "gutter_cin", 0)
    edge_margin_cin = req_int(data, "edge_margin_cin", 0)
    gripper_cin = req_int(data, "gripper_cin", 0)

    job = db.jobs[job_id]
    revision = db.design_revisions[design_revision_id]

    if job["status"] != "ENGINEERING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Imposition plans can only be created while the job is ENGINEERING")
    if revision["status"] == "SUPERSEDED":
        raise ApiError(ERR_REVISION_SUPERSEDED, 409,
                       "Design revision %s is SUPERSEDED" % design_revision_id)
    if revision["job_id"] != job_id:
        raise ApiError(ERR_REVISION_JOB_MISMATCH, 409,
                       "Design revision belongs to a different job")

    ups, orientation = calc.nesting_yield(
        sheet_w_cin, sheet_h_cin, gutter_cin, edge_margin_cin, gripper_cin,
        revision["blank_w_cin"], revision["blank_h_cin"],
        revision["grain_rotation_allowed"],
    )
    if ups == 0:
        raise ApiError(ERR_LAYOUT_IMPOSSIBLE, 409,
                       "Blank does not fit the sheet in any permitted orientation")
    net_sheets, gross_sheets, layout_yield = calc.sheet_counts(
        ups, revision["blank_w_cin"], revision["blank_h_cin"],
        sheet_w_cin, sheet_h_cin, job["quantity_ordered"], job["route_type"],
    )

    rec = db.new_record()
    rec.update({
        "job_id": job_id,
        "design_revision_id": design_revision_id,
        "sheet_w_cin": sheet_w_cin,
        "sheet_h_cin": sheet_h_cin,
        "gutter_cin": gutter_cin,
        "edge_margin_cin": edge_margin_cin,
        "gripper_cin": gripper_cin,
        "ups": ups,
        "orientation": orientation,
        "net_sheets": net_sheets,
        "gross_sheets": gross_sheets,
        "layout_yield_milli_pct": layout_yield,
        "realized_sheets_printed": 0,
        "realized_good_sheets": 0,
        "realized_waste_milli_pct": None,
        "status": "DRAFT",
    })
    db.imposition_plans[rec["id"]] = rec
    return ok_object(ser_plain(rec), 201)


@bp.get("/plant/imposition-plans")
def list_imposition_plans():
    authenticate(ALL_ROLES)
    return list_response(
        db.imposition_plans.values(),
        ser_plain,
        [("job_id", "job_id", "str"),
         ("design_revision_id", "design_revision_id", "str"),
         ("status", "status", "str")],
    )


@bp.get("/plant/imposition-plans/<planId>")
def get_imposition_plan(planId):
    authenticate(ALL_ROLES)
    return ok_object(ser_plain(get_or_404(db.imposition_plans, planId)))


@bp.post("/plant/imposition-plans/<planId>/lock")
def lock_imposition_plan(planId):
    authenticate(("StructuralDesigner",))
    rec = get_or_404(db.imposition_plans, planId)
    data = get_body()
    expected_job_version = req_int(data, "expected_job_version")

    job = db.jobs[rec["job_id"]]
    if rec["status"] != "DRAFT" or job["status"] != "ENGINEERING":
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Locking requires a DRAFT plan of an ENGINEERING job")
    if expected_job_version != job["version"]:
        raise ApiError(ERR_STALE_JOB_VERSION, 412,
                       "expected_job_version %s does not match current job version %s"
                       % (expected_job_version, job["version"]))

    # Supersede any other LOCKED plan of the same job
    for other in db.imposition_plans.values():
        if other["job_id"] == job["id"] and other["id"] != rec["id"] \
                and other["status"] == "LOCKED":
            other["status"] = "SUPERSEDED"
            touch(other)

    rec["status"] = "LOCKED"
    touch(rec)
    touch(job)  # lock is a create-with-supersede write: Job.version += 1
    return ok_object(ser_plain(rec))


@bp.post("/plant/imposition-plans/<planId>/supersede")
def supersede_imposition_plan(planId):
    authenticate(("StructuralDesigner",))
    rec = get_or_404(db.imposition_plans, planId)
    job = db.jobs[rec["job_id"]]
    if rec["status"] != "LOCKED" or job["status"] in PRODUCTION_OR_LATER:
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a LOCKED plan may be superseded, and only before production")
    rec["status"] = "SUPERSEDED"
    touch(rec)
    return ok_object(ser_plain(rec))
