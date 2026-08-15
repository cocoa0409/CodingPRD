"""Handler endpoints."""
from flask import Blueprint, request

from db import store
from errors import err, err_not_found, err_invalid_request
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services import cascades
from services.credits import tier_for
from services.records import new_record, touch, public
from validate import get_body, validate_body

bp = Blueprint("handlers", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_handler(handler_id):
    h = store.handlers.get(handler_id)
    if h is None:
        raise err_not_found("handler")
    return h


@bp.post("/v1/handlers")
def create_handler():
    auth = get_auth()
    require_roles(auth, ["Anonymous"])
    body = validate_body(get_body(), {
        "full_name": ("string", True, None),
        "email": ("string", True, None),
        "region_code": ("string", True, None),
        "volunteer_since": ("date", True, None),
        "phone": ("string", False, None),
    })
    for h in store.handlers.values():
        if h["email"] == body["email"]:
            raise err_invalid_request("email must be unique across handlers")
    rec = new_record(store.handlers, {
        "full_name": body["full_name"],
        "email": body["email"],
        "region_code": body["region_code"],
        "volunteer_since": body["volunteer_since"],
        "phone": body.get("phone"),
        "status": "APPLICANT",
        "suspension_reason": None,
        "lifetime_minutes": 0,
        "recognition_tier": "NONE",
    })
    return success_object(public(rec), 201)


@bp.get("/v1/handlers/<handler_id>")
def get_handler(handler_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_handler(handler_id)), 200)


@bp.get("/v1/handlers")
def list_handlers():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.handlers.values())
    status = request.args.get("status")
    tier = request.args.get("recognition_tier")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    if tier is not None:
        records = [r for r in records if r["recognition_tier"] == tier]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/handlers/<handler_id>/approve")
def approve_handler(handler_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    h = _get_handler(handler_id)
    if h["status"] != "APPLICANT":
        raise err("ERR_HANDLER_NOT_APPLICANT", 409, "Handler is not in APPLICANT")
    h["status"] = "ACTIVE"
    touch(h)
    return success_object(public(h), 200)


@bp.post("/v1/handlers/<handler_id>/reject")
def reject_handler(handler_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    h = _get_handler(handler_id)
    validate_body(get_body(), {"reason": ("string", True, None)})
    if h["status"] != "APPLICANT":
        raise err("ERR_HANDLER_NOT_APPLICANT", 409, "Handler is not in APPLICANT")
    h["status"] = "REJECTED"
    touch(h)
    return success_object(public(h), 200)


@bp.post("/v1/handlers/<handler_id>/suspend")
def suspend_handler(handler_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    h = _get_handler(handler_id)
    body = validate_body(get_body(), {"reason": ("string", True, None)})
    if h["status"] != "ACTIVE":
        raise err("ERR_HANDLER_NOT_ACTIVE", 409, "Handler is not ACTIVE")
    h["status"] = "SUSPENDED"
    h["suspension_reason"] = body["reason"]
    touch(h)
    return success_object(public(h), 200)


@bp.post("/v1/handlers/<handler_id>/reinstate")
def reinstate_handler(handler_id):
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    h = _get_handler(handler_id)
    if h["status"] != "SUSPENDED":
        raise err("ERR_HANDLER_NOT_SUSPENDED", 409, "Handler is not SUSPENDED")
    h["status"] = "ACTIVE"
    h["suspension_reason"] = None
    touch(h)
    return success_object(public(h), 200)


@bp.post("/v1/handlers/<handler_id>/retire")
def retire_handler(handler_id):
    auth = get_auth()
    require_roles(auth, ["Handler", "ProgramAdmin"])
    h = _get_handler(handler_id)
    # Ownership: a Handler actor may only retire themself.
    if auth.role == "Handler" and auth.user_id != h["id"]:
        raise err_ownership()
    if h["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_HANDLER_NOT_ACTIVE", 409, "Handler is not ACTIVE or SUSPENDED")
    h["status"] = "RETIRED"
    touch(h)
    cascades.retire_handler_cascade(h)
    return success_object(public(h), 200)


@bp.get("/v1/handlers/<handler_id>/recognition")
def handler_recognition(handler_id):
    from util import round_half_up
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    h = _get_handler(handler_id)
    lifetime = h.get("lifetime_minutes", 0)
    tier = h.get("recognition_tier", "NONE")
    order = ["NONE", "BRONZE", "SILVER", "GOLD", "PLATINUM"]
    thresholds = {"NONE": 0, "BRONZE": 1500, "SILVER": 6000, "GOLD": 15000, "PLATINUM": 30000}
    idx = order.index(tier)
    if idx < len(order) - 1:
        next_tier = order[idx + 1]
        minutes_to_next = thresholds[next_tier] - lifetime
    else:
        next_tier = None
        minutes_to_next = 0
    return success_object({
        "handler_id": h["id"],
        "lifetime_minutes": lifetime,
        "lifetime_hours": round_half_up(lifetime / 60.0, 2),
        "recognition_tier": tier,
        "next_tier": next_tier,
        "minutes_to_next_tier": minutes_to_next,
    }, 200)
