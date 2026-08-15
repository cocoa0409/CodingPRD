"""ClientAccount registry and retainer top-ups (PRD §3.1)."""
import re

import clock
import db
from auth import require_roles, ALL_ROLES
from errors import (
    raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_EMAIL_NOT_UNIQUE,
)
from flask import Blueprint, request
from response import respond, respond_list
from services import ser_client, TIERS
from util import (
    body, opt_enum, paginate, req_num, req_str, sort_created, touch,
)

bp = Blueprint("clients", __name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def get_client(client_id):
    c = db.store["clients"].get(client_id)
    if c is None:
        raise_err(ERR_NOT_FOUND, f"ClientAccount {client_id} not found")
    return c


@bp.route("/clients", methods=["POST"])
@require_roles("LabDirector")
def create_client():
    b = body()
    name = req_str(b, "name")
    contact_email = req_str(b, "contact_email")
    if not _EMAIL_RE.match(contact_email):
        raise_err(ERR_INVALID_REQUEST, "contact_email is malformed")
    tier = opt_enum(b, "tier", TIERS, default="STANDARD")
    for c in db.store["clients"].values():
        if c["contact_email"] == contact_email:
            raise_err(ERR_EMAIL_NOT_UNIQUE,
                      f"contact_email {contact_email} is already registered")
    now = clock.now()
    client = {
        "id": db.new_id(),
        "_seq": db.next_seq(),
        "name": name,
        "contact_email": contact_email,
        "tier": tier,
        "retainer_hours_balance": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.store["clients"][client["id"]] = client
    return respond(ser_client(client), 201)


@bp.route("/clients", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_clients():
    items = sort_created(db.store["clients"].values())
    tier = request.args.get("tier")
    if tier is not None:
        items = [c for c in items if c["tier"] == tier]
    page, pagination = paginate(items)
    return respond_list([ser_client(c) for c in page], pagination)


@bp.route("/clients/<client_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_one_client(client_id):
    return respond(ser_client(get_client(client_id)), 200)


@bp.route("/clients/<client_id>/retainer-topups", methods=["POST"])
@require_roles("LabDirector")
def topup_client(client_id):
    client = get_client(client_id)
    b = body()
    hours = req_num(b, "hours")
    if hours <= 0:
        raise_err(ERR_INVALID_REQUEST, "hours must be greater than zero")
    client["retainer_hours_balance"] = client["retainer_hours_balance"] + hours
    touch(client)
    return respond(ser_client(client), 201)
