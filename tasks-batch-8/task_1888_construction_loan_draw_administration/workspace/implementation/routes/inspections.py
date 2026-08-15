from flask import Blueprint, g, request

import db
from auth import ALL_ROLES, require_role
from db import pub, touch
from errors import ApiError
from respond import success, success_list
from services import get_or_404, recompute_inspection_progress
from util import (
    get_body,
    opt_int,
    opt_str,
    paginate,
    req_date,
    req_enum,
    req_num,
    req_str,
    sort_created,
    to_date,
)

bp = Blueprint("inspections", __name__)


@bp.post("/inspections")
def create_inspection():
    require_role(g.role, {"DrawProcessor"})
    body = get_body()
    # Existence (4).
    loan_id = body.get("loan_id")
    if loan_id is not None and loan_id not in db.loans:
        raise ApiError("ERR_NOT_FOUND", "Loan not found")
    loan = db.loans.get(loan_id) if isinstance(loan_id, str) else None
    draw_id = body.get("draw_id")
    if draw_id is not None and draw_id not in db.draws:
        raise ApiError("ERR_NOT_FOUND", "DrawRequest not found")
    draw = db.draws.get(draw_id) if isinstance(draw_id, str) else None
    # Loan-open gating (6).
    if loan is not None and loan["status"] != "OPEN":
        raise ApiError(
            "ERR_LOAN_NOT_OPEN", "Inspections can only be ordered on an OPEN loan"
        )
    # Temporal rule (8): minimum 3-day gap vs existing ORDERED inspections
    # on the same loan (a difference of <= 2 days in either direction conflicts).
    sched_raw = body.get("scheduled_date")
    if isinstance(sched_raw, str) and loan is not None:
        try:
            new_date = to_date(sched_raw)
            for other in db.inspections.values():
                if other["loan_id"] == loan["id"] and other["status"] == "ORDERED":
                    if abs((new_date - to_date(other["scheduled_date"])).days) <= 2:
                        raise ApiError(
                            "ERR_INSPECTION_SCHEDULE_CONFLICT",
                            "New ORDERED inspection within +/- 2 days of an existing ORDERED inspection on the same loan",
                        )
        except ValueError:
            pass  # malformed date handled by structural validation below
    # Structural field validation (9).
    scheduled_date = req_date(body, "scheduled_date")
    loan_id = req_str(body, "loan_id")
    # Cross-entity linkage (10): the draw must belong to the named loan.
    if draw is not None and draw["loan_id"] != loan_id:
        raise ApiError(
            "ERR_DRAW_LOAN_MISMATCH",
            "Inspection's draw_id belongs to a different loan than loan_id",
        )
    rec = db.base_record()
    rec.update(
        {
            "loan_id": loan_id,
            "draw_id": draw_id if draw is not None else None,
            "scheduled_date": scheduled_date,
            "status": "ORDERED",
            "percent_complete_reported": None,
            "completed_date": None,
            "stored_materials_observed_cents": None,
            "notes": None,
            "rejection_reason": None,
        }
    )
    db.inspections[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/inspections/<rid>")
def get_inspection(rid):
    require_role(g.role, ALL_ROLES)
    return success(pub(get_or_404(db.inspections, rid, "Inspection")))


@bp.get("/inspections")
def list_inspections():
    require_role(g.role, ALL_ROLES)
    items = list(db.inspections.values())
    f_loan = request.args.get("loan_id")
    f_draw = request.args.get("draw_id")
    f_status = request.args.get("status")
    if f_loan is not None:
        items = [i for i in items if i["loan_id"] == f_loan]
    if f_draw is not None:
        items = [i for i in items if i["draw_id"] == f_draw]
    if f_status is not None:
        items = [i for i in items if i["status"] == f_status]
    page, total, limit, offset = paginate(sort_created(items))
    return success_list([pub(r) for r in page], total, limit, offset)


@bp.post("/inspections/<rid>/complete")
def complete_inspection(rid):
    require_role(g.role, {"Inspector"})
    insp = get_or_404(db.inspections, rid, "Inspection")
    if insp["status"] != "ORDERED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an ORDERED inspection can be completed"
        )
    body = get_body()
    pct = req_num(body, "percent_complete_reported")
    if pct < 0.0 or pct > 100.0:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "percent_complete_reported must be within 0.00-100.00",
        )
    insp["percent_complete_reported"] = pct
    insp["completed_date"] = req_date(body, "completed_date")
    insp["stored_materials_observed_cents"] = opt_int(
        body, "stored_materials_observed_cents", None, min_value=0
    )
    insp["notes"] = opt_str(body, "notes")
    insp["status"] = "COMPLETED"
    touch(insp)
    return success(pub(insp))


@bp.post("/inspections/<rid>/review")
def review_inspection(rid):
    require_role(g.role, {"DrawProcessor"})
    insp = get_or_404(db.inspections, rid, "Inspection")
    if insp["status"] != "COMPLETED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only a COMPLETED inspection can be reviewed"
        )
    body = get_body()
    decision = req_enum(body, "decision", ["ACCEPTED", "REJECTED"])
    if decision == "REJECTED":
        insp["rejection_reason"] = req_str(body, "reason")
        insp["status"] = "REJECTED"
        touch(insp)
        return success(pub(insp))
    insp["status"] = "ACCEPTED"
    touch(insp)
    loan = db.loans[insp["loan_id"]]
    recompute_inspection_progress(loan)
    touch(loan)
    return success(pub(insp))


@bp.post("/inspections/<rid>/cancel")
def cancel_inspection(rid):
    require_role(g.role, {"DrawProcessor"})
    insp = get_or_404(db.inspections, rid, "Inspection")
    if insp["status"] != "ORDERED":
        raise ApiError(
            "ERR_INVALID_STATE", "Only an ORDERED inspection can be cancelled"
        )
    insp["status"] = "CANCELLED"
    touch(insp)
    return success(pub(insp))
