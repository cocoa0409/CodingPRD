"""Client routes (PRD §3.1, §3.12)."""
from flask import Blueprint

from db import db, common_fields, touch
from errors import err
from middleware import get_user_context, require_role
from response import success_object
from serializers import client_out
from services.helpers import get_json_body, require_fields
from services.lookups import get_client

bp = Blueprint("clients", __name__)


@bp.route("/clients", methods=["POST"])
def create_client():
    _uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable"})
    body = get_json_body()
    require_fields(body, ["name", "billing_email"])
    if not isinstance(body["name"], str) or not isinstance(body["billing_email"], str):
        raise err("ERR_INVALID_REQUEST", "name and billing_email must be strings")
    c = common_fields()
    c.update({
        "name": body["name"],
        "billing_email": body["billing_email"],
        "ar_balance_cents": 0,
        "status": "ACTIVE",
    })
    db.clients[c["id"]] = c
    return success_object(client_out(c), 201)


@bp.route("/clients/<cid>", methods=["GET"])
def get_client_route(cid):
    uid, role = get_user_context()
    require_role(role, {"ProjectManager", "AccountsReceivable", "Client"})
    c = get_client(cid)
    if role == "Client" and uid != c["id"]:
        raise err("ERR_FORBIDDEN_FOR_ROLE", "Client may only read its own record")
    return success_object(client_out(c), 200)


@bp.route("/clients/<cid>/suspend", methods=["POST"])
def suspend_client(cid):
    _uid, role = get_user_context()
    require_role(role, {"AccountsReceivable"})
    c = get_client(cid)
    c["status"] = "SUSPENDED"
    touch(c)
    return success_object(client_out(c), 200)
