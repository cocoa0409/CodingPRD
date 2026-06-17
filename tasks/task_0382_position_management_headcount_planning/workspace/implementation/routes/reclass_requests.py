"""ReclassRequest endpoints: submit (nested), review, return, approve, reject,
get, list (PRD §3.7)."""
from flask import Blueprint, request

from db import db
from errors import err
from middleware import require_auth
from response import success, list_success
from services import serialize, calc
from services.common import (
    get_body, require_string, fetch, paginate, base_common_fields, bump,
)

bp = Blueprint("reclass_requests", __name__)

ALL_ROLES = ["HRBP", "HRDirector", "FinanceController", "CompensationAnalyst"]


@bp.post("/positions/<position_id>/reclass-requests")
def submit_reclass(position_id):
    require_auth(["CompensationAnalyst"])
    pos = fetch(db.positions, position_id)
    body = get_body()
    target_grade_id = require_string(body, "target_grade_id")
    justification = require_string(body, "justification")

    # Existence (priority 3): body FK target grade.
    target_grade = fetch(db.grades, target_grade_id)
    current_grade = db.grades.get(pos["grade_id"])

    from_rank = current_grade["rank"] if current_grade else 0
    target_rank = target_grade["rank"]
    direction = calc.reclass_direction(from_rank, target_rank)

    rec = base_common_fields()
    rec.update({
        "position_id": position_id,
        "target_grade_id": target_grade_id,
        "from_grade_rank": from_rank,
        "target_grade_rank": target_rank,
        "direction": direction,
        "status": "SUBMITTED",
    })
    db.reclass_requests[rec["id"]] = rec
    return success(serialize.reclass_request_out(rec), status=201)


@bp.get("/positions/<position_id>/reclass-requests")
def list_position_reclass(position_id):
    require_auth(ALL_ROLES)
    fetch(db.positions, position_id)
    records = [r for r in db.reclass_requests.values() if r["position_id"] == position_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.reclass_request_out(r) for r in page], limit, offset, total)


@bp.get("/reclass-requests/<reclass_id>")
def get_reclass(reclass_id):
    require_auth(ALL_ROLES)
    rec = fetch(db.reclass_requests, reclass_id)
    return success(serialize.reclass_request_out(rec))


@bp.get("/reclass-requests")
def list_reclass():
    require_auth(ALL_ROLES)
    records = list(db.reclass_requests.values())
    for field in ("target_grade_id", "position_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r[field] == val]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.reclass_request_out(r) for r in page], limit, offset, total)


@bp.post("/reclass-requests/<reclass_id>/review")
def review_reclass(reclass_id):
    require_auth(["CompensationAnalyst"])
    rec = fetch(db.reclass_requests, reclass_id)
    if rec["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "reclass must be SUBMITTED to move under review")
    rec["status"] = "UNDER_REVIEW"
    bump(rec)
    return success(serialize.reclass_request_out(rec))


@bp.post("/reclass-requests/<reclass_id>/return")
def return_reclass(reclass_id):
    require_auth(["CompensationAnalyst"])
    rec = fetch(db.reclass_requests, reclass_id)
    if rec["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "reclass must be UNDER_REVIEW to return")
    rec["status"] = "SUBMITTED"
    bump(rec)
    return success(serialize.reclass_request_out(rec))


@bp.post("/reclass-requests/<reclass_id>/approve")
def approve_reclass(reclass_id):
    require_auth(["HRDirector"])
    rec = fetch(db.reclass_requests, reclass_id)
    body = get_body()
    pos = db.positions.get(rec["position_id"])

    # State (priority 6): request must be UNDER_REVIEW.
    if rec["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "reclass must be UNDER_REVIEW to approve")

    # Owning position lifecycle must be REQUISITIONED or FUNDED (ERR_INVALID_STATE).
    if pos is None or pos["lifecycle_status"] not in ("REQUISITIONED", "FUNDED"):
        raise err("ERR_INVALID_STATE", "owning position must be REQUISITIONED or FUNDED")

    cc = db.cost_centers.get(pos["cost_center_id"])
    # Frozen gate (priority 7).
    if cc is not None and calc.cost_center_posture(cc["id"]) == "FROZEN":
        raise err("ERR_COST_CENTER_FROZEN", "owning cost center is frozen")

    override = body.get("override") is True

    # Budget check only when FUNDED and direction == UPGRADE (PRD §3.7).
    if pos["lifecycle_status"] == "FUNDED" and rec["direction"] == "UPGRADE":
        old_planned = calc.planned_cost_cents(pos)
        target_grade = db.grades.get(rec["target_grade_id"])
        from decimal import Decimal, ROUND_HALF_UP
        new_planned = int(
            (Decimal(target_grade["band_mid_cents"]) * Decimal(str(pos["fte"])))
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )
        # committed - old + new <= annual_budget_cents (admit equality).
        prospective = calc.committed_cost_cents(cc["id"]) - old_planned + new_planned
        if prospective > cc["annual_budget_cents"] and not override:
            raise err("ERR_BUDGET_EXCEEDED", "reclass approval would exceed budget")

    # Apply: grade change, recompute planned cost (derived at read time).
    rec["status"] = "APPROVED"
    bump(rec)
    pos["grade_id"] = rec["target_grade_id"]
    bump(pos)
    return success(serialize.reclass_request_out(rec))


@bp.post("/reclass-requests/<reclass_id>/reject")
def reject_reclass(reclass_id):
    require_auth(["HRDirector"])
    rec = fetch(db.reclass_requests, reclass_id)
    if rec["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "reclass must be UNDER_REVIEW to reject")
    rec["status"] = "REJECTED"
    bump(rec)
    return success(serialize.reclass_request_out(rec))
