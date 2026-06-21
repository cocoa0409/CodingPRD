"""Client endpoints (PRD 3.1)."""
from flask import Blueprint

import db
from errors import err
from middleware import require_auth, require_role
from response import success
from services import common, derive

bp = Blueprint("clients", __name__)


@bp.post("/clients")
def create_client():
    _, role = require_auth()
    require_role(role, ["PlatformAdmin"])
    body = common.get_body()
    display_name = common.require_str(body, "display_name")
    email = common.require_str(body, "email")
    # email unique among clients (PRD 3.1)
    for c in db.clients.values():
        if c["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email already used by another client")
    rec = db.new_common()
    rec.update({
        "display_name": display_name,
        "email": email,
        "wallet_balance_cents": 0,
        "lifetime_funded_cents": 0,
        "status": "ACTIVE",
    })
    db.clients[rec["id"]] = rec
    return success(derive.client_view(rec), status=201)


@bp.get("/clients")
def list_clients():
    _, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client"])
    from flask import request
    email = request.args.get("email")
    items = list(db.clients.values())
    if email is not None:
        items = [c for c in items if c["email"] == email]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.client_view(c) for c in page], pagination=meta)


@bp.get("/clients/<cid>")
def get_client(cid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client"])
    c = common.get_client(cid)
    common.check_client_owns(role, user_id, c["id"])
    return success(derive.client_view(c))


@bp.post("/clients/<cid>/wallet/deposit")
def deposit(cid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client"])
    c = common.get_client(cid)
    common.check_client_owns(role, user_id, c["id"])
    body = common.get_body()
    amount = common.require_int(body, "amount_cents", minimum=1)
    c["wallet_balance_cents"] += amount
    db.touch(c)
    return success(derive.client_view(c))


@bp.get("/clients/<cid>/job-postings")
def client_job_postings(cid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client", "Freelancer"])
    common.get_client(cid)
    common.check_client_owns(role, user_id, cid)
    items = [j for j in db.job_postings.values() if j["client_id"] == cid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.job_posting_view(j) for j in page], pagination=meta)


@bp.get("/clients/<cid>/contracts")
def client_contracts(cid):
    user_id, role = require_auth()
    require_role(role, ["PlatformAdmin", "Client"])
    common.get_client(cid)
    common.check_client_owns(role, user_id, cid)
    items = [c for c in db.contracts.values() if c["client_id"] == cid]
    items = common.sort_by_created(items)
    page, meta = common.paginate(items)
    return success([derive.contract_view(c) for c in page], pagination=meta)
