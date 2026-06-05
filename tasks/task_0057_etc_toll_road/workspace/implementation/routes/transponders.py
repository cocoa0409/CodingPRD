from flask import Blueprint, request
import errors
from errors import err
from db import db, init_common
from middleware import get_auth, require_roles
from response import success
from util import get_body, require_str, paginate, sorted_by_created
from serialize import public, public_list

bp = Blueprint("transponders", __name__)


@bp.post("/etc/transponders")
def create_transponder():
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator"})
    body = get_body()
    account_id = require_str(body, "account_id")
    acc = db.accounts.get(account_id)
    if acc is None:
        raise err(errors.ERR_NOT_FOUND, "Account not found")
    if role == "AccountHolder" and account_id != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning account")
    serial = require_str(body, "serial")
    for t in db.transponders.values():
        if t["serial"] == serial:
            raise err(errors.ERR_DUPLICATE_SERIAL, "Transponder serial already exists")
    tp = {
        "account_id": account_id,
        "serial": serial,
        "status": "UNBOUND",
    }
    init_common(tp)
    db.transponders[tp["id"]] = tp
    return success(public(tp), status=201)


@bp.get("/etc/transponders/<tid>")
def get_transponder(tid):
    user_id, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    t = db.transponders.get(tid)
    if t is None:
        raise err(errors.ERR_NOT_FOUND, "Transponder not found")
    if role == "AccountHolder" and t["account_id"] != user_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Not the owning account")
    return success(public(t))


@bp.get("/etc/transponders")
def list_transponders():
    _, role = get_auth()
    require_roles(role, {"AccountHolder", "TollOperator", "SystemAdmin"})
    items = list(db.transponders.values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        items = [t for t in items if t["account_id"] == account_id]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success(public_list(page), pagination=meta)
