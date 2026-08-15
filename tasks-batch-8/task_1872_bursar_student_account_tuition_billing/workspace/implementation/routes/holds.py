from flask import Blueprint, request

from db import store, base_fields, touch
from errors import (err, ERR_ACCOUNT_NOT_FOUND, ERR_RESOURCE_NOT_FOUND,
                    ERR_ACCOUNT_STATE_INVALID, ERR_HOLD_STATE_INVALID)
from middleware import auth_context, require_roles, forbid
from response import success, json_body, req_str, req_enum, list_response
from serialize import ser_hold

bp = Blueprint("holds", __name__)


@bp.post("/bursar/holds")
def create_hold():
    _, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    body = json_body()
    account_id = req_str(body, "account_id")
    hold_type = req_enum(body, "hold_type", ("REGISTRATION", "TRANSCRIPT"))
    reason = req_str(body, "reason")
    account = store.accounts.get(account_id)
    if account is None:
        raise err(ERR_ACCOUNT_NOT_FOUND, "Account not found")
    if account["status"] not in ("OPEN", "PAST_DUE"):
        raise err(ERR_ACCOUNT_STATE_INVALID,
                  "Manual hold placement requires the account to be OPEN or PAST_DUE")
    h = base_fields()
    h.update({
        "account_id": account["id"], "hold_type": hold_type, "origin": "MANUAL",
        "reason": reason, "status": "ACTIVE", "released_reason": None,
    })
    store.holds[h["id"]] = h
    return success(ser_hold(h), status=201)


@bp.post("/bursar/holds/<hid>/release")
def release_hold(hid):
    _, role = auth_context()
    require_roles(role, "BursarStaff", "BursarManager")
    h = store.holds.get(hid)
    if h is None:
        raise err(ERR_RESOURCE_NOT_FOUND, "Hold not found")
    if h["status"] != "ACTIVE":
        raise err(ERR_HOLD_STATE_INVALID, "Only an ACTIVE hold can be released")
    body = json_body()
    # Manual release is explicit and unconditional, regardless of balance.
    reason = body.get("released_reason", body.get("reason"))
    h["status"] = "RELEASED"
    h["released_reason"] = reason
    touch(h)
    return success(ser_hold(h))


@bp.get("/bursar/accounts/<aid>/holds")
def list_holds(aid):
    uid, role = auth_context()
    require_roles(role, "Student", "RegistrarStaff", "BursarStaff", "BursarManager")
    a = store.accounts.get(aid)
    if a is None:
        raise err(ERR_ACCOUNT_NOT_FOUND, "Account not found")
    if role == "Student" and a["student_id"] != uid:
        forbid()
    rows = [h for h in store.holds.values() if h["account_id"] == aid]
    status = request.args.get("status")
    if status is not None:
        rows = [h for h in rows if h["status"] == status]
    rows.sort(key=lambda h: h["_seq"])
    return list_response(rows, ser_hold)
