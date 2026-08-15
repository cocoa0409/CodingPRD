from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ACCOUNT_CLOSED, ERR_OWNERSHIP, ERR_OFFER_EXPIRED,
                    ERR_STALE_ACCOUNT)
from helpers import (auth, require_role, require_body, ok, ok_list, v_str,
                     v_int, v_enum, ALL_ROLES, sort_created)
from serializers import offer_to_dict, offer_effective_status

bp = Blueprint("offers", __name__)

OFFER_TYPES = ["LINKED_SAVINGS", "OVERDRAFT_LINE_OF_CREDIT", "COUNSELING"]


def get_offer_or_404(oid):
    o = db.store["offers"].get(oid)
    if o is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Education offer %s not found" % oid)
    return o


@bp.post("/v1/education-offers")
def create_offer():
    _, role = auth()
    require_role(role, ["Teller"])
    body = require_body()
    account_id = v_str(body, "account_id")
    offer_type = v_enum(body, "offer_type", OFFER_TYPES)
    expected_account_version = v_int(body, "expected_account_version")
    acct = db.store["accounts"].get(account_id)
    if acct is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Account %s not found" % account_id)
    if acct["status"] in ("CLOSED_VOLUNTARY", "CLOSED_CHARGEOFF"):
        raise ApiError(ERR_ACCOUNT_CLOSED, 409, "Account is closed")
    # Tier 13 (last): OCC against the account's version.
    if expected_account_version != acct["version"]:
        raise ApiError(ERR_STALE_ACCOUNT, 412,
                       "expected_account_version does not match the account's version")
    # Supersede any currently OFFERED offer (manual-creation effect).
    for o in db.store["offers"].values():
        if o["account_id"] == account_id and offer_effective_status(o) == "OFFERED":
            o["status"] = "SUPERSEDED"
            db.touch(o)
    program = db.store["programs"][acct["program_id"]]
    expires = db.clock_dt() + timedelta(days=program["offer_expiry_days"])
    o = db.new_entity({
        "account_id": account_id,
        "offer_type": offer_type,
        "trigger_reason": "MANUAL",
        "status": "OFFERED",
        "expires_at": db.fmt_ts(expires),
    })
    db.store["offers"][o["id"]] = o
    db.touch(acct)
    return ok(offer_to_dict(o), status=201)


@bp.get("/v1/education-offers")
def list_offers():
    _, role = auth()
    require_role(role, ALL_ROLES)
    items = list(db.store["offers"].values())
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    if account_id is not None:
        items = [o for o in items if o["account_id"] == account_id]
    if status is not None:
        items = [o for o in items if offer_effective_status(o) == status]
    return ok_list([offer_to_dict(o) for o in sort_created(items)])


@bp.get("/v1/education-offers/<oid>")
def get_offer(oid):
    _, role = auth()
    require_role(role, ALL_ROLES)
    return ok(offer_to_dict(get_offer_or_404(oid)))


def _answer_offer(oid, target):
    uid, role = auth()
    require_role(role, ["AccountHolder"])
    o = get_offer_or_404(oid)
    if uid != o["account_id"]:
        raise ApiError(ERR_OWNERSHIP, 403, "Only the owning account holder may answer an offer")
    acct = db.store["accounts"][o["account_id"]]
    if acct["status"] not in ("ACTIVE", "RESTRICTED"):
        raise ApiError(ERR_ACCOUNT_CLOSED, 409, "Account is closed")
    eff = offer_effective_status(o)
    if eff != "OFFERED":
        if o["status"] == "OFFERED":
            # Lazily expired (stored OFFERED but clock passed expires_at).
            raise ApiError(ERR_OFFER_EXPIRED, 409, "The offer has expired")
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Only an OFFERED offer can be answered")
    o["status"] = target
    db.touch(o)
    return ok(offer_to_dict(o))


@bp.post("/v1/education-offers/<oid>/accept")
def accept_offer(oid):
    return _answer_offer(oid, "ACCEPTED")


@bp.post("/v1/education-offers/<oid>/decline")
def decline_offer(oid):
    return _answer_offer(oid, "DECLINED")
