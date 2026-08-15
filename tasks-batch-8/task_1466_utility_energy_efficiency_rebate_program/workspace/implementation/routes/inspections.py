"""Inspection endpoints: listing, retrieval, completion with cascades."""
from flask import Blueprint, request

from auth import ALL_ROLES, require_roles
from db import store, today
from errors import ApiError
from lookups import (
    ensure_program_open,
    get_inspection,
    program_year_of_application,
)
from respond import respond_list, success
from serialize import inspection_out
from services import recompute_ally, touch
from validate import get_body, req_enum

bp = Blueprint("inspections", __name__)


@bp.get("/inspections")
@require_roles(*ALL_ROLES)
def list_inspections():
    application_id = request.args.get("application_id")
    inspection_kind = request.args.get("inspection_kind")
    outcome = request.args.get("outcome")
    rows = list(store.inspections.values())
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    if inspection_kind is not None:
        rows = [r for r in rows if r["inspection_kind"] == inspection_kind]
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    return respond_list(rows, inspection_out)


@bp.get("/inspections/<rid>")
@require_roles(*ALL_ROLES)
def get_inspection_route(rid):
    return success(inspection_out(get_inspection(rid)), "object", 200)


@bp.post("/inspections/<rid>/complete")
@require_roles("VerificationInspector")
def complete_inspection(rid):
    insp = get_inspection(rid)
    body = get_body()
    outcome = req_enum(body, "outcome", ("PASSED", "FAILED"))
    app = store.applications[insp["application_id"]]
    py = program_year_of_application(app)
    # Fixed completion check order (PRD section 3.5): gate, parent state,
    # fail-reason requirement, then the double-completion guard.
    ensure_program_open(py)
    required_status = (
        "PRE_INSPECTION" if insp["inspection_kind"] == "PRE" else "POST_INSPECTION"
    )
    if app["status"] != required_status:
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "RebateApplication.status is %s; completing a %s inspection "
            "requires %s" % (app["status"], insp["inspection_kind"], required_status),
        )
    fail_reason = body.get("fail_reason")
    if outcome == "FAILED":
        if not isinstance(fail_reason, str) or len(fail_reason) == 0:
            raise ApiError(
                "ERR_FAIL_REASON_REQUIRED",
                422,
                "A FAILED inspection requires a non-empty fail_reason",
            )
    if insp["outcome"] != "PENDING":
        raise ApiError(
            "ERR_INSPECTION_ALREADY_COMPLETED",
            409,
            "Inspection %s is already %s" % (insp["id"], insp["outcome"]),
        )
    # --- commit ---
    insp["outcome"] = outcome
    insp["completed_on"] = today().isoformat()
    insp["fail_reason"] = fail_reason if outcome == "FAILED" else None
    touch(insp)
    if outcome == "PASSED":
        if insp["inspection_kind"] == "PRE":
            app["status"] = "POST_INSPECTION"
            touch(app)
        # A passed POST inspection leaves the application in POST_INSPECTION.
    else:
        # A failed inspection of either kind rejects the application and
        # releases its committed incentive.
        app["status"] = "REJECTED"
        touch(app)
        py["committed_cents"] -= app["incentive_total_cents"]
        touch(py)
    # The installing ally's standing is recomputed on every completion.
    recompute_ally(app["trade_ally_id"])
    return success(inspection_out(insp), "object", 200)
