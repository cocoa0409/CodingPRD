"""Creditor endpoints."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_DUPLICATE
from middleware import auth_context, require_roles, json_body, ALL_ROLES
from response import ok_object, paginate
from services_common import new_entity, get_or_404, ser_creditor, ser_action, sorted_rows
from util import require_str, optional_bool

bp = Blueprint("creditors", __name__)


@bp.route("/trustee/creditors", methods=["POST"])
def create_creditor():
    _, role = auth_context()
    require_roles(role, ("Clerk",))
    body = json_body()

    raw_ref = body.get("creditor_ref")
    if isinstance(raw_ref, str):
        for existing in db.creditors.values():
            if existing["creditor_ref"] == raw_ref:
                raise ApiError(ERR_DUPLICATE, 409, "creditor_ref already exists.")

    legal_name = require_str(body, "legal_name")
    creditor_ref = require_str(body, "creditor_ref")
    insider = optional_bool(body, "insider")
    contact_email = require_str(body, "contact_email")

    creditor = new_entity({
        "legal_name": legal_name,
        "creditor_ref": creditor_ref,
        "insider": insider if insider is not None else False,
        "contact_email": contact_email,
    })
    db.creditors[creditor["id"]] = creditor
    return ok_object(ser_creditor(creditor), status=201)


@bp.route("/trustee/creditors/<id>", methods=["GET"])
def get_creditor(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    return ok_object(ser_creditor(get_or_404(db.creditors, id, "creditor")))


@bp.route("/trustee/creditors/<id>/avoidance_actions", methods=["GET"])
def creditor_avoidance_actions(id):
    auth_context()
    require_roles(request.headers.get("X-User-Role"), ALL_ROLES)
    get_or_404(db.creditors, id, "creditor")
    rows = [a for a in db.actions.values() if a["transferee_creditor_id"] == id]
    return paginate([ser_action(a) for a in sorted_rows(rows)])
