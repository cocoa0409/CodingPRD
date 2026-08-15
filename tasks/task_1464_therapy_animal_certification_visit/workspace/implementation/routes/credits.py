"""Hour-credit ledger endpoints."""
from flask import Blueprint, request

from db import store
from errors import err_not_found
from middleware import get_auth, require_roles
from response import success_object, success_list, paginate
from services import credits as credit_service
from services.records import public
from validate import get_body, validate_body

bp = Blueprint("credits", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


@bp.get("/v1/hour-credits/<credit_id>")
def get_credit(credit_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    row = store.hour_credits.get(credit_id)
    if row is None:
        raise err_not_found("hour_credit")
    return success_object(public(row), 200)


@bp.get("/v1/hour-credits")
def list_credits():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.hour_credits.values())
    handler_id = request.args.get("handler_id")
    visit_id = request.args.get("visit_id")
    kind = request.args.get("kind")
    if handler_id is not None:
        records = [r for r in records if r["handler_id"] == handler_id]
    if visit_id is not None:
        records = [r for r in records if r.get("visit_id") == visit_id]
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/hour-credits/adjustments")
def create_adjustment():
    auth = get_auth()
    require_roles(auth, ["ComplianceOfficer"])
    body = validate_body(get_body(), {
        "handler_id": ("string", True, None),
        "minutes": ("integer", True, None),
        "reason": ("string", True, None),
    })
    handler = store.handlers.get(body["handler_id"])
    if handler is None:
        raise err_not_found("handler")
    row = credit_service.post_adjustment(handler, body["minutes"], body["reason"])
    return success_object(public(row), 201)
