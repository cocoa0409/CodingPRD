from flask import Blueprint, g

from db import store, stamp_new
from errors import fail, ERR_NOT_PROGRAM_OWNER, ERR_INVALID_REQUEST
from middleware import require_roles
from response import success
from routes.helpers import get_body, require_fields, require_string, lookup
from services.serialize import client_out
from services import core

bp = Blueprint("clients", __name__)


@bp.post("/clients")
@require_roles("ProgramAdmin")
def create_client():
    body = get_body()
    require_fields(body, ["full_name", "email", "state_code"])
    full_name = require_string(body["full_name"], "full_name")
    email = require_string(body["email"], "email")
    state_code = require_string(body["state_code"], "state_code")
    if len(state_code) != 2:
        fail(ERR_INVALID_REQUEST, "state_code must be a two-letter code")
    c = stamp_new({
        "full_name": full_name,
        "email": email,
        "state_code": state_code,
        "refunded_to_client_cents": 0,
    })
    store.clients[c["id"]] = c
    return success(client_out(c), status=201)


@bp.get("/clients/<cid>")
@require_roles("ProgramAdmin", "Client")
def get_client(cid):
    c = lookup(store.clients, cid)
    # Client read scoping: a Client may only read their own client record.
    if g.role == "Client" and g.user_id != cid:
        fail(ERR_NOT_PROGRAM_OWNER, "Client may only read their own record")
    return success(client_out(c))
