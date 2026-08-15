"""Spill response plans: shipper lifecycle plus safety-office adjudication
(PRD 3.7)."""
from flask import Blueprint, request

from authz import (
    ALL_ROLES, CUSTOMER_REP, FLEET_ADMIN, SAFETY_OFFICER,
    require_customer_identity, require_roles,
)
from cascades import refresh_plan_lazy
from db import store
from errors import err
from respond import success
from serialize import ser_spill_plan
from store_ops import (
    get_or_404, json_body, new_common_fields, new_id, paginate,
    reject_unknown, req_field, req_str_list, sorted_by_creation, touch,
)
from timeutil import add_days
from calc import SPILL_PLAN_VALIDITY_DAYS

bp = Blueprint("spill_plans", __name__)


def _plan_invalid(msg):
    return err("ERR_SPILL_PLAN_INVALID_STATE", msg)


@bp.route("/spill-response-plans", methods=["POST"])
def create_plan():
    uid, role = require_roles([CUSTOMER_REP, FLEET_ADMIN])
    data = json_body()
    # Priority 2 identity: a CustomerRep may only plan for its own customer.
    if role == CUSTOMER_REP and data.get("customer_id") is not None:
        require_customer_identity(uid, data["customer_id"])
    # Priority 3: body-reference existence, left-to-right.
    customer = product = None
    if data.get("customer_id") is not None:
        customer = get_or_404(store.customers, "customers", data["customer_id"])
    if data.get("product_id") is not None:
        product = get_or_404(store.products, "products", data["product_id"])
    reject_unknown(data, {"customer_id", "product_id", "equipment_checklist"})
    req_field(data, "customer_id")
    req_field(data, "product_id")
    checklist = req_str_list(data, "equipment_checklist")
    p = {
        "id": new_id(),
        "_seq": next(store.seq),
        "customer_id": customer["id"],
        "product_id": product["id"],
        "equipment_checklist": checklist,
        "approved_at": None,
        "expires_at": None,
        "status": "DRAFT",
    }
    p.update(new_common_fields())
    store.spill_plans[p["id"]] = p
    return success(ser_spill_plan(p), status=201)


@bp.route("/spill-response-plans", methods=["GET"])
def list_plans():
    require_roles(ALL_ROLES)
    customer_id = request.args.get("customer_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    items = []
    for p in store.spill_plans.values():
        refresh_plan_lazy(p)  # lazy EXPIRED surfaces on reads (PRD 2.5)
        if customer_id is not None and p["customer_id"] != customer_id:
            continue
        if product_id is not None and p["product_id"] != product_id:
            continue
        if status is not None and p["status"] != status:
            continue
        items.append(p)
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_spill_plan(p) for p in page],
                   response_type="array", pagination=pagination)


@bp.route("/spill-response-plans/<pid>", methods=["GET"])
def get_plan(pid):
    require_roles(ALL_ROLES)
    p = get_or_404(store.spill_plans, "spill_plans", pid)
    refresh_plan_lazy(p)
    return success(ser_spill_plan(p))


@bp.route("/spill-response-plans/<pid>/submit", methods=["POST"])
def submit_plan(pid):
    uid, _role = require_roles([CUSTOMER_REP])
    p = get_or_404(store.spill_plans, "spill_plans", pid)
    # Priority 2 identity: only the owning CustomerRep submits.
    require_customer_identity(uid, p["customer_id"])
    reject_unknown(json_body(), set())
    if p["status"] != "DRAFT":
        raise _plan_invalid("Submit requires the plan to be DRAFT")
    p["status"] = "SUBMITTED"
    touch(p)
    return success(ser_spill_plan(p))


@bp.route("/spill-response-plans/<pid>/approve", methods=["POST"])
def approve_plan(pid):
    require_roles([SAFETY_OFFICER])
    p = get_or_404(store.spill_plans, "spill_plans", pid)
    reject_unknown(json_body(), set())
    if p["status"] != "SUBMITTED":
        raise _plan_invalid("Approve requires the plan to be SUBMITTED")
    p["approved_at"] = store.clock
    p["expires_at"] = add_days(store.clock, SPILL_PLAN_VALIDITY_DAYS)
    p["status"] = "APPROVED"
    touch(p)
    return success(ser_spill_plan(p))


@bp.route("/spill-response-plans/<pid>/reject", methods=["POST"])
def reject_plan(pid):
    require_roles([SAFETY_OFFICER])
    p = get_or_404(store.spill_plans, "spill_plans", pid)
    data = json_body()
    reject_unknown(data, {"reason"})  # optional reason is accepted, not stored
    if p["status"] != "SUBMITTED":
        raise _plan_invalid("Reject requires the plan to be SUBMITTED")
    p["status"] = "REJECTED"
    touch(p)
    return success(ser_spill_plan(p))


@bp.route("/spill-response-plans/<pid>/suspend", methods=["POST"])
def suspend_plan(pid):
    require_roles([SAFETY_OFFICER])
    p = get_or_404(store.spill_plans, "spill_plans", pid)
    reject_unknown(json_body(), set())
    if p["status"] != "APPROVED":
        raise _plan_invalid("Suspend requires the plan to be APPROVED")
    p["status"] = "SUSPENDED"
    touch(p)
    return success(ser_spill_plan(p))


@bp.route("/spill-response-plans/<pid>/reinstate", methods=["POST"])
def reinstate_plan(pid):
    require_roles([SAFETY_OFFICER])
    p = get_or_404(store.spill_plans, "spill_plans", pid)
    reject_unknown(json_body(), set())
    if p["status"] != "SUSPENDED":
        raise _plan_invalid("Reinstate requires the plan to be SUSPENDED")
    # expires_at is unchanged from the original approval — suspension never
    # extends a plan's life (PRD 3.7).
    p["status"] = "APPROVED"
    touch(p)
    return success(ser_spill_plan(p))
