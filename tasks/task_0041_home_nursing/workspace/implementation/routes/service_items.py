"""Routes for /service-items."""
from flask import Blueprint, request

import db
from db import public
from middleware import require_auth, get_pagination, get_json_body
from response import success, success_list
from services import service_item as svc


bp = Blueprint("service_items", __name__)


@bp.route("/service-items", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def create_si():
    body = get_json_body()
    item = svc.create_service_item(body)
    return success(public(item), status=201)


@bp.route("/service-items", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceOfficer", "Patient"})
def list_si():
    limit, offset = get_pagination()
    raw_active = request.args.get("active")
    active = None
    if raw_active is not None:
        if raw_active.lower() == "true":
            active = True
        elif raw_active.lower() == "false":
            active = False
    rows, total = svc.list_service_items(limit, offset, active)
    return success_list([public(r) for r in rows], limit, offset, total)


@bp.route("/service-items/<code>", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceOfficer", "Patient"})
def get_si(code):
    item = svc.get_service_item(code)
    return success(public(item))
