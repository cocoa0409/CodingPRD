from flask import Blueprint
import errors
from errors import err
from db import db, init_common
from middleware import get_auth, require_roles
from response import success
from util import get_body, require_str, require_int, require_bool
from serialize import public

bp = Blueprint("interop", __name__)


@bp.post("/etc/interop-agencies")
def create_interop_agency():
    _, role = get_auth()
    require_roles(role, {"SystemAdmin"})
    body = get_body()
    name = require_str(body, "name")
    state_code = require_str(body, "state_code")
    fee = require_int(body, "settlement_fee_bps", required=False, default=200, min_value=0)
    active = require_bool(body, "active", required=False, default=True)
    agency = {
        "name": name,
        "state_code": state_code,
        "settlement_fee_bps": fee,
        "active": active,
    }
    init_common(agency)
    db.interop_agencies[agency["id"]] = agency
    return success(public(agency), status=201)


@bp.get("/etc/interop-agencies/<aid>")
def get_interop_agency(aid):
    _, role = get_auth()
    require_roles(role, {"TollOperator", "InteropClerk", "SystemAdmin"})
    a = db.interop_agencies.get(aid)
    if a is None:
        raise err(errors.ERR_NOT_FOUND, "Interop agency not found")
    return success(public(a))
