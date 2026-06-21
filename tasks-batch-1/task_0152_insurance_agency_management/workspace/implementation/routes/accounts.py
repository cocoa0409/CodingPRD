"""Account endpoints (PRD §3.3)."""
from flask import Blueprint, request

import serialize
from db import store, new_common
from middleware import auth, get_json_body, lookup, paginate
from response import object_response, array_response
from util import require_str, require_enum

bp = Blueprint("accounts", __name__)

ALL_ROLES = {"AgencyAdmin", "Producer", "AccountManager", "TrustAccountant"}
ACCOUNT_TYPE = {"PERSONAL", "COMMERCIAL"}


@bp.post("/accounts")
def create_account():
    auth({"AgencyAdmin", "AccountManager"})
    body = get_json_body()
    name = require_str(body, "name")
    servicing_producer_id = require_str(body, "servicing_producer_id")
    with store.lock:
        lookup(store.producers, servicing_producer_id)  # existence (404)
        account_type = require_enum(body, "account_type", ACCOUNT_TYPE)
        rec = new_common()
        rec.update(
            name=name,
            servicing_producer_id=servicing_producer_id,
            account_type=account_type,
        )
        store.accounts[rec["id"]] = rec
        return object_response(serialize.account(rec), 201)


@bp.get("/accounts/<aid>")
def get_account(aid):
    auth(ALL_ROLES)
    rec = lookup(store.accounts, aid)
    return object_response(serialize.account(rec))


@bp.get("/accounts")
def list_accounts():
    auth(ALL_ROLES)
    servicing_producer_id = request.args.get("servicing_producer_id")
    account_type = request.args.get("account_type")
    recs = [
        a
        for a in store.accounts.values()
        if (servicing_producer_id is None or a["servicing_producer_id"] == servicing_producer_id)
        and (account_type is None or a["account_type"] == account_type)
    ]
    page, limit, offset, total = paginate(recs)
    return array_response([serialize.account(a) for a in page], limit, offset, total)
