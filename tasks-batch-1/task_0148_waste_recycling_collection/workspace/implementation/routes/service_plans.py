"""ServicePlan endpoints (PRD §3.1)."""
from flask import request, Blueprint

from db import db, base_record, touch
from errors import err
from middleware import authenticate, require_roles
from response import success
from services import serializers as ser
from services.common import check_enum, get_json_body, paginate, parse_pagination, require_fields

bp = Blueprint("service_plans", __name__)

STREAMS = {"TRASH", "RECYCLE", "ORGANICS"}
FREQUENCIES = {"WEEKLY", "BIWEEKLY", "MONTHLY"}


@bp.route("/service-plans", methods=["POST"])
def create_plan():
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    body = get_json_body()
    # Body-reference existence (priority 5) precedes request-shape (priority 6).
    require_fields(body, ["account_id"])
    if body["account_id"] not in db.accounts:
        raise err("ERR_REFERENCE_NOT_FOUND", "Referenced account does not exist.")
    require_fields(body, ["stream", "frequency", "base_monthly_fee_cents"])
    check_enum(body["stream"], STREAMS, "stream")
    check_enum(body["frequency"], FREQUENCIES, "frequency")
    fee = body["base_monthly_fee_cents"]
    if not isinstance(fee, int) or isinstance(fee, bool) or fee < 0:
        raise err("ERR_INVALID_REQUEST", "base_monthly_fee_cents must be an integer >= 0.")

    rec = base_record()
    rec.update(
        {
            "account_id": body["account_id"],
            "stream": body["stream"],
            "frequency": body["frequency"],
            "base_monthly_fee_cents": fee,
            "status": "DRAFT",
        }
    )
    db.service_plans[rec["id"]] = rec
    return success(ser.service_plan(rec), status=201)


@bp.route("/service-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Billing"})
    rec = db.service_plans.get(plan_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Service plan not found.")
    return success(ser.service_plan(rec), status=200)


@bp.route("/service-plans", methods=["GET"])
def list_plans():
    _, role = authenticate()
    require_roles(role, {"Dispatcher", "Billing"})
    parse_pagination()
    items = list(db.service_plans.values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [p for p in items if p["account_id"] == account_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, pagination = paginate(items)
    return success([ser.service_plan(p) for p in page], status=200, pagination=pagination)


@bp.route("/service-plans/<plan_id>/activate", methods=["POST"])
def activate_plan(plan_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.service_plans.get(plan_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Service plan not found.")
    if rec["status"] not in ("DRAFT", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Plan cannot be activated from its current state.")
    # ERR_NO_MATCHING_CART: account must own a same-stream cart in {ASSIGNED, ACTIVE}.
    has_match = any(
        c["account_id"] == rec["account_id"]
        and c["stream"] == rec["stream"]
        and c["status"] in ("ASSIGNED", "ACTIVE")
        for c in db.carts.values()
    )
    if not has_match:
        raise err("ERR_NO_MATCHING_CART", "No matching-stream cart available for activation.")
    rec["status"] = "ACTIVE"
    touch(rec)
    return success(ser.service_plan(rec), status=200)


@bp.route("/service-plans/<plan_id>/pause", methods=["POST"])
def pause_plan(plan_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.service_plans.get(plan_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Service plan not found.")
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE plan can be paused.")
    rec["status"] = "PAUSED"
    touch(rec)
    return success(ser.service_plan(rec), status=200)


@bp.route("/service-plans/<plan_id>/terminate", methods=["POST"])
def terminate_plan(plan_id):
    _, role = authenticate()
    require_roles(role, {"Dispatcher"})
    rec = db.service_plans.get(plan_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Service plan not found.")
    if rec["status"] not in ("DRAFT", "ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "Plan cannot be terminated from its current state.")
    rec["status"] = "TERMINATED"
    touch(rec)
    return success(ser.service_plan(rec), status=200)
