from flask import Blueprint, request

import db
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ACCOUNT_CLOSED, ERR_ACCOUNT_RESTRICTED,
                    ERR_STALE_DISCLOSURE, ERR_ELECTION_EXISTS, ERR_OWNERSHIP)
from helpers import (auth, require_role, require_body, ok, ok_list, v_str,
                     v_enum, ALL_ROLES, sort_created)
from serializers import election_to_dict
from services import get_election
from routes.account_routes import get_account_or_404

bp = Blueprint("elections", __name__)

CHANNELS = ["BRANCH", "ONLINE", "PHONE", "MAIL"]


def get_election_or_404(eid):
    e = db.store["elections"].get(eid)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Opt-in election %s not found" % eid)
    return e


@bp.post("/v1/accounts/<aid>/opt-in-election")
def create_election(aid):
    uid, role = auth()
    require_role(role, ["AccountHolder", "Teller"])
    body = require_body()
    channel = v_enum(body, "channel", CHANNELS)
    disclosure_version = v_str(body, "disclosure_version")
    acct = get_account_or_404(aid)
    if role == "AccountHolder" and uid != aid:
        raise ApiError(ERR_OWNERSHIP, 403, "AccountHolder may only act on their own account")
    if acct["status"] in ("CLOSED_VOLUNTARY", "CLOSED_CHARGEOFF"):
        raise ApiError(ERR_ACCOUNT_CLOSED, 409, "Account is closed")
    program = db.store["programs"][acct["program_id"]]
    if disclosure_version != program["current_disclosure_version"]:
        raise ApiError(ERR_STALE_DISCLOSURE, 409,
                       "disclosure_version does not match the program's current version")
    if get_election(aid) is not None:
        raise ApiError(ERR_ELECTION_EXISTS, 409,
                       "An opt-in election already exists for this account")
    e = db.new_entity({
        "account_id": aid,
        "status": "OPTED_IN",
        "channel": channel,
        "disclosure_version": disclosure_version,
        "elected_at": db.now_iso(),
        "last_changed_at": db.now_iso(),
    })
    db.store["elections"][e["id"]] = e
    return ok(election_to_dict(e), status=201)


@bp.get("/v1/opt-in-elections")
def list_elections():
    _, role = auth()
    require_role(role, ALL_ROLES)
    items = list(db.store["elections"].values())
    account_id = request.args.get("account_id")
    if account_id is not None:
        items = [e for e in items if e["account_id"] == account_id]
    return ok_list([election_to_dict(e) for e in sort_created(items)])


@bp.get("/v1/opt-in-elections/<eid>")
def get_one_election(eid):
    _, role = auth()
    require_role(role, ALL_ROLES)
    return ok(election_to_dict(get_election_or_404(eid)))


@bp.post("/v1/opt-in-elections/<eid>/revoke")
def revoke_election(eid):
    uid, role = auth()
    require_role(role, ["AccountHolder", "Teller"])
    e = get_election_or_404(eid)
    if role == "AccountHolder" and uid != e["account_id"]:
        raise ApiError(ERR_OWNERSHIP, 403, "AccountHolder may only act on their own account")
    acct = db.store["accounts"][e["account_id"]]
    if acct["status"] in ("CLOSED_VOLUNTARY", "CLOSED_CHARGEOFF"):
        raise ApiError(ERR_ACCOUNT_CLOSED, 409, "Account is closed")
    if e["status"] != "OPTED_IN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPTED_IN election can be revoked")
    e["status"] = "REVOKED"
    e["last_changed_at"] = db.now_iso()
    db.touch(e)
    return ok(election_to_dict(e))


@bp.post("/v1/opt-in-elections/<eid>/reinstate")
def reinstate_election(eid):
    uid, role = auth()
    require_role(role, ["AccountHolder", "Teller"])
    body = require_body()
    disclosure_version = v_str(body, "disclosure_version")
    e = get_election_or_404(eid)
    if role == "AccountHolder" and uid != e["account_id"]:
        raise ApiError(ERR_OWNERSHIP, 403, "AccountHolder may only act on their own account")
    acct = db.store["accounts"][e["account_id"]]
    if acct["status"] in ("CLOSED_VOLUNTARY", "CLOSED_CHARGEOFF"):
        raise ApiError(ERR_ACCOUNT_CLOSED, 409, "Account is closed")
    if acct["status"] == "RESTRICTED":
        raise ApiError(ERR_ACCOUNT_RESTRICTED, 409,
                       "RESTRICTED account blocks opt-in reinstatement")
    if e["status"] != "REVOKED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a REVOKED election can be reinstated")
    program = db.store["programs"][acct["program_id"]]
    if disclosure_version != program["current_disclosure_version"]:
        raise ApiError(ERR_STALE_DISCLOSURE, 409,
                       "disclosure_version does not match the program's current version")
    e["status"] = "OPTED_IN"
    e["disclosure_version"] = disclosure_version
    e["last_changed_at"] = db.now_iso()
    db.touch(e)
    return ok(election_to_dict(e))
