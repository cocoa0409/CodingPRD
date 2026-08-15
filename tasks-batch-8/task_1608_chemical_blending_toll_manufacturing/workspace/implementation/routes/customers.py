"""Customer endpoints."""
from flask import Blueprint, request

import db
import errors
from middleware import require_role
from response import success_object, success_list
from services.common import (
    new_id,
    now_iso,
    pagination_params,
    paginate,
    sort_by_created_at,
    serialize_customer,
)

bp = Blueprint("customers", __name__)


@bp.route("/toll-operations/customers", methods=["POST"])
def create_customer():
    require_role({"QualityManager"})
    body = request.get_json(silent=True) or {}
    legal_name = body.get("legal_name")
    if not legal_name or not isinstance(legal_name, str):
        raise errors.invalid_request("legal_name is required")
    credit_hold = body.get("credit_hold", False)
    if not isinstance(credit_hold, bool):
        raise errors.invalid_request("credit_hold must be boolean")
    now = now_iso()
    cid = new_id()
    customer = {
        "id": cid,
        "legal_name": legal_name,
        "credit_hold": credit_hold,
        "status": "ACTIVE",
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.customers[cid] = customer
    return success_object(serialize_customer(customer), status=201)


@bp.route("/toll-operations/customers", methods=["GET"])
def list_customers():
    require_role({"Any"})
    limit, offset = pagination_params()
    rows = sort_by_created_at(list(db.customers.values()))
    slice_, total = paginate(rows, limit, offset)
    return success_list([serialize_customer(c) for c in slice_], limit, offset, total)


@bp.route("/toll-operations/customers/<id>", methods=["GET"])
def get_customer(id):
    require_role({"Any"})
    c = db.customers.get(id)
    if c is None:
        raise errors.not_found("customer not found")
    return success_object(serialize_customer(c))


def _customer_or_404(cid):
    c = db.customers.get(cid)
    if c is None:
        raise errors.not_found("customer not found")
    return c


@bp.route("/toll-operations/customers/<id>/suspend", methods=["POST"])
def suspend_customer(id):
    require_role({"QualityManager"})
    c = _customer_or_404(id)
    if c["status"] != "ACTIVE":
        raise errors.invalid_state("customer not ACTIVE")
    c["status"] = "SUSPENDED"
    c["version"] += 1
    c["updated_at"] = now_iso()
    return success_object(serialize_customer(c))


@bp.route("/toll-operations/customers/<id>/reinstate", methods=["POST"])
def reinstate_customer(id):
    require_role({"QualityManager"})
    c = _customer_or_404(id)
    if c["status"] != "SUSPENDED":
        raise errors.invalid_state("customer not SUSPENDED")
    c["status"] = "ACTIVE"
    c["version"] += 1
    c["updated_at"] = now_iso()
    return success_object(serialize_customer(c))


@bp.route("/toll-operations/customers/<id>/terminate", methods=["POST"])
def terminate_customer(id):
    require_role({"QualityManager"})
    c = _customer_or_404(id)
    if c["status"] != "SUSPENDED":
        raise errors.invalid_state("customer not SUSPENDED")
    open_statuses = {"INTAKE", "RELEASED", "CHARGING", "MIXING", "HOLD_QA"}
    for b in db.batch_jobs.values():
        if b["customer_id"] == id and b["status"] in open_statuses:
            raise errors.ApiError(errors.ERR_OPEN_BATCH_JOBS, 409, "customer has open batch jobs")
    c["status"] = "TERMINATED"
    c["version"] += 1
    c["updated_at"] = now_iso()
    return success_object(serialize_customer(c))
