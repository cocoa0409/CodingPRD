"""EscrowAccount routes."""

from flask import Blueprint, request

import errors
import middleware
from db import db
from response import success
from services.core import touch
from services.serialize import serialize_escrow
from util import parse_pagination, paginate

bp = Blueprint("escrow", __name__)


@bp.get("/escrow-accounts")
def list_escrow_accounts():
    middleware.require_roles(middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.escrow_accounts.values())
    lease_filter = request.args.get("lease_id")
    if lease_filter is not None:
        items = [e for e in items if e["lease_id"] == lease_filter]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, pg = paginate(items, limit, offset)
    return success([serialize_escrow(e) for e in page], "array", 200, pagination=pg)


@bp.get("/escrow-accounts/<eid>")
def get_escrow_account(eid):
    middleware.require_roles(middleware.ALL_ROLES)
    e = db.escrow_accounts.get(eid)
    if e is None:
        raise errors.err(errors.ERR_ESCROW_NOT_FOUND, "EscrowAccount not found", 404)
    return success(serialize_escrow(e), "object", 200)


@bp.post("/escrow-accounts/<eid>/disburse")
def disburse_escrow(eid):
    middleware.require_roles({"SettlementClerk"})
    e = db.escrow_accounts.get(eid)
    if e is None:
        raise errors.err(errors.ERR_ESCROW_NOT_FOUND, "EscrowAccount not found", 404)
    if e["status"] != "REFUND_PENDING":
        raise errors.err(errors.ERR_ESCROW_NOT_REFUNDABLE, "Escrow is not REFUND_PENDING", 409)
    e["total_refunded_cents"] += e["balance_cents"]
    e["balance_cents"] = 0
    e["status"] = "REFUNDED"
    touch(e)
    return success(serialize_escrow(e), "object", 200)
