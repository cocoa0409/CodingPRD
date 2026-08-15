"""Routes: change orders (contract ledger, OCC, supersede-on-approve)."""

from flask import Blueprint, request

from calc import change_order_computed_delta
from core import (
    bump,
    envelope_object,
    err_credit_hold,
    err_invalid_request,
    err_invalid_state,
    err_not_owner,
    err_ref_not_found,
    err_stale,
    err_unauthorized,
    get_body,
    opt_num,
    paginate,
    req_num,
    req_str,
    require_roles,
    sorted_by_created,
    stamp_new,
)
from lookups import get_change_order, get_job
from serializers import ser_change_order
from store import db

bp = Blueprint("change_orders", __name__)


def _validate_discount(v):
    if not isinstance(v, (int, float)) or isinstance(v, bool) or v < 0 or v > 0.5:
        raise err_invalid_request("discount_pct must be within [0, 0.5].")
    return v


@bp.route("/panel-shop/jobs/<job_id>/change-orders", methods=["POST"])
def create_change_order(job_id):
    user_id, _ = require_roles("ProjectManager")
    j = get_job(job_id)
    body = get_body()
    description = req_str(body, "description")
    price_delta = body.get("price_delta_cents")
    discount = body.get("discount_pct", 0)
    # priority 18: fiscal validation
    if not isinstance(price_delta, int) or isinstance(price_delta, bool):
        raise err_invalid_request("price_delta_cents is required and must be an integer.")
    _validate_discount(discount)
    co_number = max(
        [o["co_number"] for o in db.change_orders.values() if o["job_id"] == job_id],
        default=0,
    ) + 1
    o = stamp_new(
        {
            "job_id": job_id,
            "co_number": co_number,
            "status": "PROPOSED",
            "description": description,
            "price_delta_cents": price_delta,
            "discount_pct": discount,
            "computed_delta_cents": change_order_computed_delta(price_delta, discount),
            "requested_by_id": user_id,
            "supersedes_co_id": None,
        }
    )
    db.change_orders[o["id"]] = o
    return envelope_object(ser_change_order(o), 201)


@bp.route("/panel-shop/change-orders/<co_id>", methods=["GET"])
def fetch_change_order(co_id):
    require_roles("ProjectManager", "QAManager", "Customer")
    return envelope_object(ser_change_order(get_change_order(co_id)))


@bp.route("/panel-shop/change-orders", methods=["GET"])
def list_change_orders():
    require_roles("ProjectManager", "QAManager", "Customer")
    orders = list(db.change_orders.values())
    args = request.args
    if "job_id" in args:
        orders = [o for o in orders if o["job_id"] == args.get("job_id")]
    if "supersedes_co_id" in args:
        orders = [o for o in orders if o.get("supersedes_co_id") == args.get("supersedes_co_id")]
    if "status" in args:
        orders = [o for o in orders if o["status"] == args.get("status")]
    return paginate(sorted_by_created(orders), ser_change_order)


@bp.route("/panel-shop/change-orders/<co_id>/revise", methods=["POST"])
def revise_change_order(co_id):
    user_id, _ = require_roles("Customer")
    o = get_change_order(co_id)
    j = db.jobs[o["job_id"]]
    # priority 3: Customer ownership
    if j["customer_id"] != user_id:
        raise err_not_owner("Customer does not own this change order.")
    if o["status"] != "PROPOSED":
        raise err_invalid_state("ChangeOrder is not PROPOSED.")
    body = get_body()
    price_delta = body.get("price_delta_cents")
    discount = body.get("discount_pct", o["discount_pct"])
    if not isinstance(price_delta, int) or isinstance(price_delta, bool):
        raise err_invalid_request("price_delta_cents is required and must be an integer.")
    _validate_discount(discount)
    o["price_delta_cents"] = price_delta
    o["discount_pct"] = discount
    o["computed_delta_cents"] = change_order_computed_delta(price_delta, discount)
    o["status"] = "REVISED"
    bump(o)
    return envelope_object(ser_change_order(o))


@bp.route("/panel-shop/change-orders/<co_id>/repropose", methods=["POST"])
def repropose_change_order(co_id):
    require_roles("ProjectManager")
    o = get_change_order(co_id)
    if o["status"] != "REVISED":
        raise err_invalid_state("ChangeOrder is not REVISED.")
    o["status"] = "PROPOSED"
    bump(o)
    return envelope_object(ser_change_order(o))


@bp.route("/panel-shop/change-orders/<co_id>/approve", methods=["POST"])
def approve_change_order(co_id):
    user_id, _ = require_roles("Customer")
    o = get_change_order(co_id)
    j = db.jobs[o["job_id"]]
    # priority 3: Customer ownership
    if j["customer_id"] != user_id:
        raise err_not_owner("Customer does not own this change order.")
    body = get_body()
    supersedes_co_id = body.get("supersedes_co_id")
    supersedes = None
    if supersedes_co_id is not None:
        if not isinstance(supersedes_co_id, str) or not supersedes_co_id:
            raise err_invalid_request("supersedes_co_id must be a string id.")
        supersedes = db.change_orders.get(supersedes_co_id)
        if supersedes is None or supersedes["job_id"] != j["id"]:
            raise err_ref_not_found("supersedes_co_id does not reference a ChangeOrder of this job.")
        if supersedes["status"] not in ("PROPOSED", "REVISED"):
            raise err_invalid_state("supersedes_co_id target is not PROPOSED or REVISED.")
    # priority 6: state preconditions
    if o["status"] not in ("PROPOSED", "REVISED"):
        raise err_invalid_state("ChangeOrder is not in PROPOSED or REVISED.")
    if j["status"] == "CLOSED":
        raise err_invalid_state("Job is CLOSED.")
    # priority 7: OCC on Job.version
    expected = body.get("expected_job_version")
    if expected is None:
        raise err_invalid_request("Missing required field: expected_job_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_job_version must be an integer.")
    if expected != j["version"]:
        raise err_stale("expected_job_version does not match the job's current version.")
    # priority 17: credit hold
    customer = db.customers[j["customer_id"]]
    if customer["credit_hold"]:
        raise err_credit_hold("Customer is on credit hold.")
    # ledger posting
    j["approved_co_delta_cents"] += o["computed_delta_cents"]
    j["contract_price_cents"] = j["quoted_price_cents"] + j["approved_co_delta_cents"]
    bump(j)
    if supersedes is not None:
        o["supersedes_co_id"] = supersedes["id"]
        supersedes["status"] = "SUPERSEDED"
        bump(supersedes)
    o["status"] = "APPROVED"
    bump(o)
    return envelope_object(ser_change_order(o))


@bp.route("/panel-shop/change-orders/<co_id>/reject", methods=["POST"])
def reject_change_order(co_id):
    user_id, _ = require_roles("Customer")
    o = get_change_order(co_id)
    j = db.jobs[o["job_id"]]
    if j["customer_id"] != user_id:
        raise err_not_owner("Customer does not own this change order.")
    if o["status"] not in ("PROPOSED", "REVISED"):
        raise err_invalid_state("ChangeOrder is not in PROPOSED or REVISED.")
    o["status"] = "REJECTED"
    bump(o)
    return envelope_object(ser_change_order(o))


@bp.route("/panel-shop/change-orders/<co_id>/withdraw", methods=["POST"])
def withdraw_change_order(co_id):
    user_id, _ = require_roles("ProjectManager")
    o = get_change_order(co_id)
    if o["status"] != "PROPOSED":
        raise err_invalid_state("ChangeOrder is not PROPOSED.")
    # only the drafting PM may withdraw
    if user_id != o["requested_by_id"]:
        raise err_unauthorized("Only the drafting ProjectManager may withdraw this order.")
    o["status"] = "WITHDRAWN"
    bump(o)
    return envelope_object(ser_change_order(o))


@bp.route("/panel-shop/change-orders/<co_id>/rescind", methods=["POST"])
def rescind_change_order(co_id):
    require_roles("ProjectManager")
    o = get_change_order(co_id)
    j = db.jobs[o["job_id"]]
    if o["status"] != "APPROVED":
        raise err_invalid_state("ChangeOrder is not APPROVED.")
    if j["status"] == "CLOSED":
        raise err_invalid_state("Job is CLOSED.")
    body = get_body()
    expected = body.get("expected_job_version")
    if expected is None:
        raise err_invalid_request("Missing required field: expected_job_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise err_invalid_request("expected_job_version must be an integer.")
    if expected != j["version"]:
        raise err_stale("expected_job_version does not match the job's current version.")
    # compensating entry
    j["approved_co_delta_cents"] -= o["computed_delta_cents"]
    j["contract_price_cents"] = j["quoted_price_cents"] + j["approved_co_delta_cents"]
    bump(j)
    o["status"] = "SUPERSEDED"
    bump(o)
    return envelope_object(ser_change_order(o))
