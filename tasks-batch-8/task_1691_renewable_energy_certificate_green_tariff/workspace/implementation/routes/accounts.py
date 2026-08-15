"""Account endpoints and the account lifecycle."""

from flask import Blueprint, request

from errors import raise_err, ERR_VALIDATION, ERR_ACCOUNT_NOT_ACTIVE
from store import STORE, new_id, next_seq, now_ts
from util import auth, require_role, ok_object, body_json, req_str, opt_str, \
    req_enum, get_or_404
from services import account_holdings, suspend_account, touch
from routes.generators import list_with_serializer

bp = Blueprint("accounts", __name__)


def serialize_account(a):
    out = {k: v for k, v in a.items() if not k.startswith("_")}
    active, locked = account_holdings(a["id"])
    out["active_holdings_mwh"] = active
    out["locked_holdings_mwh"] = locked
    return out


@bp.post("/greenpower/accounts")
def create_account():
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    body = body_json()
    account_type = req_enum(body, "account_type", {"GENERATOR", "BROKER", "PROGRAM"})
    if account_type == "GENERATOR":
        raise_err(ERR_VALIDATION,
                  "GENERATOR accounts are auto-created at generator verify")
    owner_name = req_str(body, "owner_name")
    generator_id = opt_str(body, "generator_id")
    program_id = opt_str(body, "program_id")
    if account_type == "PROGRAM" and program_id is None:
        raise_err(ERR_VALIDATION, "program_id is required for PROGRAM accounts")
    if generator_id is not None:
        get_or_404(STORE["generators"], generator_id, "Generator")
    if program_id is not None:
        get_or_404(STORE["programs"], program_id, "Program")
    now = now_ts()
    acct = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "account_type": account_type,
        "owner_name": owner_name,
        "generator_id": generator_id,
        "program_id": program_id,
        "status": "ACTIVE",
        "failure_strikes": 0,
        "_seq": next_seq(),
    }
    STORE["accounts"][acct["id"]] = acct
    return ok_object(serialize_account(acct), 201)


@bp.get("/greenpower/accounts")
def list_accounts():
    auth()
    filters = {
        "account_type": request.args.get("account_type"),
        "generator_id": request.args.get("generator_id"),
        "program_id": request.args.get("program_id"),
        "status": request.args.get("status"),
    }
    return list_with_serializer(list(STORE["accounts"].values()), filters,
                                serialize_account)


@bp.get("/greenpower/accounts/<aid>")
def get_account(aid):
    auth()
    acct = get_or_404(STORE["accounts"], aid, "Account")
    return ok_object(serialize_account(acct))


@bp.post("/greenpower/accounts/<aid>/suspend")
def suspend(aid):
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    acct = get_or_404(STORE["accounts"], aid, "Account")
    if acct["status"] != "ACTIVE":
        raise_err(ERR_ACCOUNT_NOT_ACTIVE, "Suspension requires an ACTIVE account")
    suspend_account(acct)
    touch(acct)
    return ok_object(serialize_account(acct))


@bp.post("/greenpower/accounts/<aid>/reinstate")
def reinstate(aid):
    uid, role = auth()
    require_role(role, "RegistryAdmin")
    acct = get_or_404(STORE["accounts"], aid, "Account")
    if acct["status"] != "SUSPENDED":
        raise_err(ERR_ACCOUNT_NOT_ACTIVE, "Reinstatement requires a SUSPENDED account")
    acct["status"] = "ACTIVE"
    acct["failure_strikes"] = 0
    touch(acct)
    return ok_object(serialize_account(acct))
