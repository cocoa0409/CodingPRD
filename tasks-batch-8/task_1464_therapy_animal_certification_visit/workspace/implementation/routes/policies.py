"""Insurance policy endpoints."""
from flask import Blueprint, request

from db import store
from errors import err, err_not_found, err_invalid_request
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services import cascades
from services.records import new_record, touch, public
from util import today, parse_date
from validate import get_body, validate_body

bp = Blueprint("policies", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_policy(policy_id):
    p = store.policies.get(policy_id)
    if p is None:
        raise err_not_found("policy")
    return p


@bp.post("/v1/insurance-policies")
def create_policy():
    auth = get_auth()
    require_roles(auth, ["Handler"])
    body = validate_body(get_body(), {
        "insurer_name": ("string", True, None),
        "policy_number": ("string", True, None),
        "coverage_cents": ("integer", True, None),
        "effective_from": ("date", True, None),
        "effective_until": ("date", True, None),
    })
    if parse_date(body["effective_until"]) < parse_date(body["effective_from"]):
        raise err_invalid_request("effective_until may not precede effective_from")
    rec = new_record(store.policies, {
        "handler_id": auth.user_id,
        "insurer_name": body["insurer_name"],
        "policy_number": body["policy_number"],
        "coverage_cents": body["coverage_cents"],
        "effective_from": body["effective_from"],
        "effective_until": body["effective_until"],
        "status": "PENDING",
    })
    return success_object(public(rec), 201)


@bp.get("/v1/insurance-policies/<policy_id>")
def get_policy(policy_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_policy(policy_id)), 200)


@bp.get("/v1/insurance-policies")
def list_policies():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.policies.values())
    handler_id = request.args.get("handler_id")
    status = request.args.get("status")
    if handler_id is not None:
        records = [r for r in records if r["handler_id"] == handler_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/insurance-policies/<policy_id>/verify")
def verify_policy(policy_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    p = _get_policy(policy_id)
    if p["status"] != "PENDING":
        raise err("ERR_POLICY_NOT_PENDING", 409, "Policy is not PENDING")
    today_d = today()
    if not (parse_date(p["effective_from"]) <= today_d <= parse_date(p["effective_until"])):
        raise err("ERR_POLICY_WINDOW_INVALID", 409,
                  "Today is outside the policy's effective window")
    for other in store.policies.values():
        if other["id"] != p["id"] and other["handler_id"] == p["handler_id"] and other["status"] == "ACTIVE":
            raise err("ERR_ACTIVE_POLICY_EXISTS", 422,
                      "Handler already has an ACTIVE policy")
    p["status"] = "ACTIVE"
    touch(p)
    return success_object(public(p), 200)


@bp.post("/v1/insurance-policies/<policy_id>/cancel")
def cancel_policy(policy_id):
    auth = get_auth()
    require_roles(auth, ["Handler", "ProgramAdmin"])
    p = _get_policy(policy_id)
    if auth.role == "Handler" and p["handler_id"] != auth.user_id:
        raise err_ownership()
    if p["status"] not in ("PENDING", "ACTIVE"):
        raise err("ERR_POLICY_NOT_CANCELLABLE", 409, "Policy is not PENDING or ACTIVE")
    was_active = p["status"] == "ACTIVE"
    p["status"] = "CANCELLED"
    touch(p)
    if was_active:
        handler = store.handlers.get(p["handler_id"])
        if handler is not None:
            cascades.policy_cancellation_cascade(handler)
    return success_object(public(p), 200)
