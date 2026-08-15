"""DesignChangeOrder endpoints: request, assess, approve, reject, apply,
withdraw — including the six-hop apply cascade."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_CHANGE_ORDER_INVALID_TRANSITION,
    ERR_DESIGN_NOT_CURRENT,
    ERR_REVISION_CHAIN_BROKEN,
    ERR_STALE_JOB_VERSION,
)
from middleware import authenticate, require_role, require_ownership, get_or_404, ALL_ROLES
from response import success, success_list
from services import cascade, serializers
from services.derive import design_is_current
from util import as_int, as_str, as_fk, body, paginate

bp = Blueprint("changeorders", __name__)


def _co_customer_id(co):
    return db.jobs[co["job_id"]]["customer_id"]


@bp.route("/plant/jobs/<job_id>/change-orders", methods=["POST"])
def create_change_order(job_id):
    uid, role = authenticate()
    require_role(role, ["CustomerContact", "ProductionPlanner"])
    job = get_or_404(db.jobs, job_id, "job")
    require_ownership(role, uid, job["customer_id"])
    data = body()
    supersedes = as_fk(data.get("supersedes_design_id"), "supersedes_design_id",
                       db.designs, "component design")
    new_design = as_fk(data.get("new_design_id"), "new_design_id", db.designs, "component design")
    if supersedes is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "missing required field: supersedes_design_id")
    reason = as_str(data.get("reason"), "reason", required=True)
    expected_job_version = as_int(data.get("expected_job_version"), "expected_job_version", required=True)
    # OCC (priority 6).
    if expected_job_version != job["version"]:
        raise ApiError(ERR_STALE_JOB_VERSION, 412, "job version has advanced since last read")
    rec = db.new_record({
        "job_id": job["id"],
        "supersedes_design_id": supersedes["id"],
        "new_design_id": new_design["id"] if new_design else None,
        "reason": reason,
        "requested_by": uid,
        "impact_lines_scrapped": None,
        "impact_open_reservations": None,
        "status": "REQUESTED",
    })
    db.design_change_orders[rec["id"]] = rec
    db.touch(job)  # each change-order create increments the job's version
    return success(serializers.design_change_order(rec), status=201)


@bp.route("/plant/change-orders/<cid>", methods=["GET"])
def get_change_order(cid):
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    rec = get_or_404(db.design_change_orders, cid, "design change order")
    require_ownership(role, uid, _co_customer_id(rec))
    return success(serializers.design_change_order(rec))


@bp.route("/plant/change-orders", methods=["GET"])
def list_change_orders():
    uid, role = authenticate()
    require_role(role, ALL_ROLES)
    records = list(db.design_change_orders.values())
    if role == "CustomerContact":
        records = [c for c in records if _co_customer_id(c) == uid]
    for field in ("job_id", "supersedes_design_id", "new_design_id", "status"):
        raw = request.args.get(field)
        if raw is not None:
            records = [c for c in records if c[field] == raw]
    page, meta = paginate(records)
    return success_list([serializers.design_change_order(c) for c in page], meta)


@bp.route("/plant/change-orders/<cid>/assess", methods=["POST"])
def assess_change_order(cid):
    _uid, role = authenticate()
    require_role(role, ["ProductionPlanner"])
    rec = get_or_404(db.design_change_orders, cid, "design change order")
    data = body()
    new_design = as_fk(data.get("new_design_id"), "new_design_id", db.designs, "component design")
    if rec["status"] != "REQUESTED":
        raise ApiError(ERR_CHANGE_ORDER_INVALID_TRANSITION, 409, "assess requires status REQUESTED")
    if new_design is not None:
        supersedes = db.designs[rec["supersedes_design_id"]]
        if (new_design["job_id"] != rec["job_id"]
                or new_design["component_ref"] != supersedes["component_ref"]
                or new_design["supersedes_design_id"] != rec["supersedes_design_id"]):
            raise ApiError(ERR_REVISION_CHAIN_BROKEN, 422,
                           "new design must be a revision of the same component_ref superseding the same design")
        rec["new_design_id"] = new_design["id"]
    # Quantify the blast radius at this moment.
    lists = [cl for cl in db.cut_lists.values() if cl["design_id"] == rec["supersedes_design_id"]]
    list_ids = {cl["id"] for cl in lists}
    line_ids = {ln["id"] for ln in db.cut_list_lines.values() if ln["cut_list_id"] in list_ids}
    rec["impact_lines_scrapped"] = sum(
        1 for ln in db.cut_list_lines.values()
        if ln["cut_list_id"] in list_ids and ln["status"] == "CUT"
    )
    rec["impact_open_reservations"] = sum(
        1 for r in db.material_reservations.values()
        if r["status"] == "RESERVED"
        and (r["cut_list_line_id"] in line_ids or r["cut_list_id"] in list_ids)
    )
    rec["status"] = "IMPACT_ASSESSED"
    db.touch(rec)
    return success(serializers.design_change_order(rec))


@bp.route("/plant/change-orders/<cid>/approve", methods=["POST"])
def approve_change_order(cid):
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    rec = get_or_404(db.design_change_orders, cid, "design change order")
    if rec["status"] != "IMPACT_ASSESSED":
        raise ApiError(ERR_CHANGE_ORDER_INVALID_TRANSITION, 409, "approve requires status IMPACT_ASSESSED")
    supersedes = db.designs[rec["supersedes_design_id"]]
    new_design = db.designs.get(rec["new_design_id"]) if rec["new_design_id"] else None
    if (
        new_design is None
        or new_design["status"] != "SEALED"
        or new_design["revision_no"] <= supersedes["revision_no"]
        or new_design["supersedes_design_id"] != rec["supersedes_design_id"]
        or new_design["job_id"] != rec["job_id"]
        or new_design["component_ref"] != supersedes["component_ref"]
    ):
        raise ApiError(ERR_REVISION_CHAIN_BROKEN, 422,
                       "approval requires a SEALED, chain-valid successor revision")
    rec["status"] = "APPROVED"
    db.touch(rec)
    # Job posture reads BLOCKED until applied (derived).
    return success(serializers.design_change_order(rec))


@bp.route("/plant/change-orders/<cid>/reject", methods=["POST"])
def reject_change_order(cid):
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    rec = get_or_404(db.design_change_orders, cid, "design change order")
    if rec["status"] not in ("REQUESTED", "IMPACT_ASSESSED"):
        raise ApiError(ERR_CHANGE_ORDER_INVALID_TRANSITION, 409,
                       "reject requires status REQUESTED or IMPACT_ASSESSED")
    rec["status"] = "REJECTED"
    db.touch(rec)
    return success(serializers.design_change_order(rec))


@bp.route("/plant/change-orders/<cid>/apply", methods=["POST"])
def apply_change_order(cid):
    _uid, role = authenticate()
    require_role(role, ["PlantManager"])
    rec = get_or_404(db.design_change_orders, cid, "design change order")
    if rec["status"] != "APPROVED":
        raise ApiError(ERR_CHANGE_ORDER_INVALID_TRANSITION, 409, "apply requires status APPROVED")
    new_design = db.designs[rec["new_design_id"]]
    if not design_is_current(new_design):
        raise ApiError(ERR_DESIGN_NOT_CURRENT, 409,
                       "new design is no longer the current SEALED revision")
    cascade.change_order_apply_cascade(rec)
    rec["status"] = "APPLIED"
    db.touch(rec)
    return success(serializers.design_change_order(rec))


@bp.route("/plant/change-orders/<cid>/withdraw", methods=["POST"])
def withdraw_change_order(cid):
    uid, role = authenticate()
    require_role(role, ["CustomerContact"])
    rec = get_or_404(db.design_change_orders, cid, "design change order")
    require_ownership(role, uid, _co_customer_id(rec))
    if rec["status"] != "REQUESTED":
        raise ApiError(ERR_CHANGE_ORDER_INVALID_TRANSITION, 409, "withdraw requires status REQUESTED")
    rec["status"] = "WITHDRAWN"
    db.touch(rec)
    return success(serializers.design_change_order(rec))
