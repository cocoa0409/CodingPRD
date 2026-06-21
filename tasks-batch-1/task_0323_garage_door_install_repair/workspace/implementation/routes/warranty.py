"""WarrantyPlan routes (PRD §3.11)."""
from flask import Blueprint, request

import db
import errors
import lookup
import serialize
import services.calc as calc
import util
from middleware import authenticate, require_role
from response import success

bp = Blueprint("warranty", __name__)


@bp.route("/warranty-plans", methods=["POST"])
def create_plan():
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["job_id", "customer_id"])
    job_id = body.get("job_id")
    customer_id = body.get("customer_id")
    if not isinstance(job_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "job_id must be a string")
    if not isinstance(customer_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "customer_id must be a string")
    tune_ups_included = util.optional_int(body, "tune_ups_included", 2)
    lookup.job(job_id)
    lookup.customer(customer_id)
    w = {
        "job_id": job_id, "customer_id": customer_id,
        "tune_ups_included": tune_ups_included, "tune_ups_used": 0,
        "status": "PENDING",
    }
    db.stamp_create(w, common_fields=True, versioned=True)
    db.warranty_plans[w["id"]] = w
    return success(serialize.warranty_plan(w), status=201)


@bp.route("/warranty-plans/<id>", methods=["GET"])
def get_plan(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer"])
    w = lookup.warranty_plan(id)
    return success(serialize.warranty_plan(w))


@bp.route("/warranty-plans", methods=["GET"])
def list_plans():
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer"])
    limit, offset = util.parse_pagination()
    job_id = request.args.get("job_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    rows = []
    for w in db.warranty_plans.values():
        if job_id is not None and w["job_id"] != job_id:
            continue
        if customer_id is not None and w["customer_id"] != customer_id:
            continue
        if status is not None and w["status"] != status:
            continue
        rows.append(w)
    page, pagination = util.paginate(rows, limit, offset)
    return success([serialize.warranty_plan(w) for w in page], pagination=pagination)


@bp.route("/warranty-plans/<id>/tune-up", methods=["POST"])
def tune_up(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Customer"])
    w = lookup.warranty_plan(id)
    if w["tune_ups_used"] >= w["tune_ups_included"]:
        raise errors.err(errors.ERR_TUNEUPS_EXHAUSTED, "Tune-ups exhausted")
    w["tune_ups_used"] += 1
    db.touch(w)
    return success(serialize.warranty_plan(w))


@bp.route("/warranty-plans/<id>/cancel", methods=["POST"])
def cancel_plan(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    w = lookup.warranty_plan(id)
    if w["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Plan must be ACTIVE to cancel")
    w["status"] = "CANCELLED"
    db.touch(w)
    cust = db.customers.get(w["customer_id"])
    if cust is not None:
        db.touch(cust)  # active_warranty_count derives live
    return success(serialize.warranty_plan(w))


@bp.route("/warranty-plans/<id>/expire", methods=["POST"])
def expire_plan(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager"])
    w = lookup.warranty_plan(id)
    if w["status"] != "ACTIVE":
        raise errors.err(errors.ERR_INVALID_STATE, "Plan must be ACTIVE to expire")
    if not (w["tune_ups_used"] >= w["tune_ups_included"]):
        raise errors.err(errors.ERR_INVALID_STATE, "Plan not exhausted")
    w["status"] = "EXPIRED"
    db.touch(w)
    cust = db.customers.get(w["customer_id"])
    if cust is not None:
        db.touch(cust)
    return success(serialize.warranty_plan(w))
