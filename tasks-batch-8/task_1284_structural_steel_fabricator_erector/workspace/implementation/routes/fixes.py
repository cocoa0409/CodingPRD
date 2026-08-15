"""Field fix endpoints: report / approve (prices the fix, creates the
PENDING backcharge) / resolve."""

from flask import Blueprint

import domain
from envelope import ok_object
from errors import (
    ApiError,
    ERR_BACKCHARGE_OPEN,
    ERR_CROSS_JOB_REFERENCE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from store import new_record, store, touch, public
from validate import authenticate, get_body, req_str, require_role
from . import list_response

bp = Blueprint("fixes", __name__)

FOREMAN = {"FOREMAN"}
GC_PM = {"GC_PM"}
READERS = {"FABRICATOR_ADMIN", "DETAILER", "EOR", "FOREMAN", "WELDER", "QC_INSPECTOR", "GC_PM"}


def view(f):
    return public(f)


def get_fix_or_404(fid):
    f = store.fixes.get(fid)
    if f is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Field fix not found.")
    return f


def _validate_repair_lines(body):
    lines = body.get("repair_lines")
    if lines is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: repair_lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "repair_lines must be a non-empty array.")
    for line in lines:
        if not isinstance(line, dict):
            raise ApiError(ERR_INVALID_REQUEST, 400, "Each repair line must be an object.")
        hours = line.get("labor_hours")
        if hours is None or isinstance(hours, bool) or not isinstance(hours, (int, float)):
            raise ApiError(ERR_INVALID_REQUEST, 400, "labor_hours must be a number.")
        for field in ("labor_rate_cents", "material_cents"):
            v = line.get(field)
            if v is None or isinstance(v, bool) or not isinstance(v, int):
                raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an integer." % field)
    return lines


@bp.post("/field-fixes")
def create_fix():
    uid, role = authenticate()
    require_role(role, FOREMAN)
    body = get_body()
    # Rung 3: body FK existence
    job_id = body.get("job_id")
    if job_id is not None and job_id not in store.jobs:
        raise ApiError(ERR_NOT_FOUND, 404, "Job not found.")
    piece_id = body.get("piece_id")
    if piece_id is not None and piece_id not in store.pieces:
        raise ApiError(ERR_NOT_FOUND, 404, "Piece not found.")
    # Rung 4: shape
    job_id = req_str(body, "job_id")
    piece_id = req_str(body, "piece_id")
    description = req_str(body, "description")
    repair_lines = _validate_repair_lines(body)
    piece = store.pieces[piece_id]
    # Rung 6: a fix is discovered after the steel has left the shop
    if piece["status"] not in ("SHIPPED", "ERECTED"):
        raise ApiError(
            ERR_INVALID_STATE, 409, "Field fixes require a SHIPPED or ERECTED piece."
        )
    # Rung 8: same-job consistency
    if piece["job_id"] != job_id:
        raise ApiError(ERR_CROSS_JOB_REFERENCE, 409, "piece_id belongs to a different job.")
    f = new_record()
    f.update(
        {
            "job_id": job_id,
            "piece_id": piece_id,
            "description": description,
            "repair_lines": repair_lines,
            "amount_cents": None,  # priced at approve time
            "status": "PRICED",
        }
    )
    store.fixes[f["id"]] = f
    return ok_object(view(f), 201)


@bp.get("/field-fixes")
def list_fixes():
    uid, role = authenticate()
    require_role(role, READERS)
    return list_response(
        store.fixes.values(),
        view,
        [("job_id", "job_id"), ("piece_id", "piece_id"), ("status", "status")],
    )


@bp.get("/field-fixes/<fid>")
def get_fix(fid):
    uid, role = authenticate()
    require_role(role, READERS)
    return ok_object(view(get_fix_or_404(fid)))


@bp.post("/field-fixes/<fid>/approve")
def approve_fix(fid):
    uid, role = authenticate()
    require_role(role, GC_PM)
    f = get_fix_or_404(fid)
    if f["status"] != "PRICED":
        raise ApiError(ERR_INVALID_STATE, 409, "Field fix must be PRICED to approve.")
    # Approving prices the fix (pinned rounding order) and creates the claim
    f["amount_cents"] = domain.backcharge_amount(f["repair_lines"])
    f["status"] = "APPROVED"
    touch(f)
    bc = new_record()
    bc.update(
        {
            "job_id": f["job_id"],
            "field_fix_id": f["id"],
            "amount_cents": f["amount_cents"],
            "settled_amount_cents": None,
            "status": "PENDING",
        }
    )
    store.backcharges[bc["id"]] = bc
    touch(store.jobs[f["job_id"]])  # pending_backcharge_cents recomputed
    return ok_object(view(f))


@bp.post("/field-fixes/<fid>/resolve")
def resolve_fix(fid):
    uid, role = authenticate()
    require_role(role, FOREMAN)
    f = get_fix_or_404(fid)
    if f["status"] != "APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409, "Field fix must be APPROVED to resolve.")
    # Rung 9: the linked backcharge must stand SETTLED
    bc = next((b for b in store.backcharges.values() if b["field_fix_id"] == f["id"]), None)
    if bc is None or bc["status"] != "SETTLED":
        raise ApiError(ERR_BACKCHARGE_OPEN, 409, "The linked backcharge is not SETTLED.")
    f["status"] = "RESOLVED"
    touch(f)
    return ok_object(view(f))
