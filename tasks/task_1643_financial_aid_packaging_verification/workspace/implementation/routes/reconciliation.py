"""ReconciliationRun and ReconciliationAdjustment endpoints (PRD 3.9)."""
from flask import Blueprint

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_VARIANCE_NOT_ZEROED,
)
from middleware import authorized
from response import success_object
from routes.helpers import list_response
from services.core import new_record, public, touch
from validate import (
    get_body, req_int, req_enum, req_str, require_path_resource,
    deferred_body_ref,
)

bp = Blueprint("reconciliation", __name__)

DIRECTOR = ["AidDirector"]
REASON_CODES = ("FEDERAL_UNDERREPORT", "FEDERAL_OVERREPORT", "TIMING_DIFFERENCE",
                "DATA_ENTRY_ERROR")


@bp.get("/reconciliation-runs/<rid>")
def get_run(rid):
    authorized(DIRECTOR)
    rec = require_path_resource("reconciliation_runs", rid)
    return success_object(public(rec))


@bp.post("/reconciliation-runs/<rid>/import-federal")
def import_federal(rid):
    authorized(DIRECTOR)
    run = require_path_resource("reconciliation_runs", rid)
    if run["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE,
                    f"run is {run['status']}, expected DRAFT")
    body = get_body()
    federal = req_int(body, "federal_reported_cents")
    if federal < 0:
        raise_error(ERR_INVALID_REQUEST,
                    "federal_reported_cents must be non-negative")
    run["federal_reported_cents"] = federal
    run["status"] = "IMPORTED"
    touch(run)
    return success_object(public(run))


@bp.post("/reconciliation-runs/<rid>/compare")
def compare(rid):
    authorized(DIRECTOR)
    run = require_path_resource("reconciliation_runs", rid)
    if run["status"] != "IMPORTED":
        raise_error(ERR_INVALID_STATE,
                    f"run is {run['status']}, expected IMPORTED")
    # Snapshot internal_posted_cents at compare time: the sum of disbursed_cents
    # over every POSTED disbursement whose line's package belongs to this year.
    internal = 0
    for disb in db.disbursements.values():
        if disb["status"] != "POSTED":
            continue
        line = db.award_lines.get(disb["award_line_id"])
        if line is None:
            continue
        pkg = db.award_packages.get(line["package_id"])
        if pkg is not None and pkg["aid_year_id"] == run["aid_year_id"]:
            internal += disb["disbursed_cents"]
    run["internal_posted_cents"] = internal
    run["variance_cents"] = run["federal_reported_cents"] - internal
    # Automatic fork at compare time.
    run["status"] = "BALANCED" if run["variance_cents"] == 0 else "VARIANCE_FOUND"
    touch(run)
    return success_object(public(run))


@bp.post("/reconciliation-runs/<rid>/adjustments")
def create_adjustment(rid):
    authorized(DIRECTOR)
    run = require_path_resource("reconciliation_runs", rid)
    if run["status"] != "VARIANCE_FOUND":
        raise_error(ERR_INVALID_STATE,
                    f"run is {run['status']}, expected VARIANCE_FOUND")
    body = get_body()
    # Rung 4: body foreign key (absent key defers to the rung-9 shape check).
    line = deferred_body_ref("award_lines", body, "award_line_id")
    # Rung 9: shape.
    req_str(body, "award_line_id")
    adjust = req_int(body, "adjust_cents")
    if adjust == 0:
        raise_error(ERR_INVALID_REQUEST, "adjust_cents must be non-zero")
    reason_code = req_enum(body, "reason_code", REASON_CODES)
    # Rung 18: the run's arithmetic must net out after this adjustment.
    existing_sum = sum(a["adjust_cents"] for a in db.reconciliation_adjustments.values()
                       if a["reconciliation_run_id"] == run["id"])
    if existing_sum + adjust + run["internal_posted_cents"] != run["federal_reported_cents"]:
        raise_error(ERR_VARIANCE_NOT_ZEROED,
                    "the run's adjustments plus internal_posted_cents must equal "
                    "federal_reported_cents")
    rec = new_record("reconciliation_adjustments", {
        "reconciliation_run_id": run["id"],
        "award_line_id": line["id"],
        "adjust_cents": adjust,
        "reason_code": reason_code,
    })
    run["status"] = "ADJUSTED"
    touch(run)
    return success_object(public(rec), status=201)


@bp.post("/reconciliation-runs/<rid>/finalize")
def finalize(rid):
    authorized(DIRECTOR)
    run = require_path_resource("reconciliation_runs", rid)
    if run["status"] != "ADJUSTED":
        raise_error(ERR_INVALID_STATE,
                    f"run is {run['status']}, expected ADJUSTED")
    # Applying the adjustments recomputes the variance to zero: the adjusted
    # internal books match the federal report exactly.
    run["variance_cents"] = 0
    run["status"] = "BALANCED"
    touch(run)
    return success_object(public(run))


@bp.get("/reconciliation-runs/<rid>/adjustments")
def list_run_adjustments(rid):
    authorized(DIRECTOR)
    require_path_resource("reconciliation_runs", rid)
    return list_response("reconciliation_adjustments", {"reconciliation_run_id": rid})


@bp.get("/award-lines/<rid>/reconciliation-adjustments")
def list_line_adjustments(rid):
    authorized(DIRECTOR)
    require_path_resource("award_lines", rid)
    return list_response("reconciliation_adjustments", {"award_line_id": rid})
