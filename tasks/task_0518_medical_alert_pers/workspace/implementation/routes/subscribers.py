"""Subscriber endpoints (PRD 3.1)."""
from flask import Blueprint

from db import store
from errors import err
from middleware import get_auth, require_role
from models import new_record, serialize_subscriber
from response import object_response
from services.lookup import get_subscriber
from util import get_json_body, require_fields, require_str

bp = Blueprint("subscribers", __name__)


@bp.route("/pers/subscribers", methods=["POST"])
def create_subscriber():
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    require_fields(body, ["full_name", "email", "residence_address", "phone"])
    require_str(body["full_name"], "full_name")
    require_str(body["email"], "email")
    require_str(body["residence_address"], "residence_address")
    require_str(body["phone"], "phone")

    # email unique across subscribers (priority 16)
    for s in store.subscribers.values():
        if s["email"] == body["email"]:
            raise err("ERR_DUPLICATE", "Email already exists")

    r = new_record()
    r.update({
        "full_name": body["full_name"],
        "email": body["email"],
        "residence_address": body["residence_address"],
        "phone": body["phone"],
        "status": "ACTIVE",
    })
    store.subscribers[r["id"]] = r
    return object_response(serialize_subscriber(r), 201)


@bp.route("/pers/subscribers/<sid>", methods=["GET"])
def get_subscriber_route(sid):
    _uid, role = get_auth()
    require_role(role, {"PlatformAdmin", "Subscriber"})
    r = get_subscriber(sid)
    return object_response(serialize_subscriber(r), 200)
