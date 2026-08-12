from flask import Blueprint, request as _req

import db
import response
import serializers
import services.cascade as cascade
from errors import raise_err
from middleware import check_member_ownership, require_roles
from routes._common import pagination_args, sorted_page

bp = Blueprint("ledger", __name__)


@bp.get("/api/ledger-entries/<entry_id>")
def get_entry(entry_id):
    user_id, role = require_roles(["COOP_ADMIN", "POOL_ACCOUNTANT", "MEMBER"])
    e = db.ledger_entries.get(entry_id)
    if not e:
        raise_err("ERR_NOT_FOUND", "Ledger entry not found")
    check_member_ownership(user_id, role, e["member_id"])
    return response.success(serializers.ledger_entry(e), 200)


@bp.get("/api/ledger-entries")
def list_entries():
    user_id, role = require_roles(["COOP_ADMIN", "POOL_ACCOUNTANT", "MEMBER"])
    member_id = _req.args.get("member_id")
    pool_id = _req.args.get("pool_id")
    installment_id = _req.args.get("installment_id")
    settlement_id = _req.args.get("settlement_id")
    kind = _req.args.get("kind")
    reversal_of_id = _req.args.get("reversal_of_id")
    limit, offset = pagination_args()
    if role == "MEMBER":
        member_id = user_id
    items = list(db.ledger_entries.values())
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    if pool_id is not None:
        items = [e for e in items if e["pool_id"] == pool_id]
    if installment_id is not None:
        items = [e for e in items if e["installment_id"] == installment_id]
    if settlement_id is not None:
        items = [e for e in items if e["settlement_id"] == settlement_id]
    if kind is not None:
        items = [e for e in items if e["kind"] == kind]
    if reversal_of_id is not None:
        items = [e for e in items if e["reversal_of_id"] == reversal_of_id]
    page, total = sorted_page(items, limit, offset)
    return response.success_list([serializers.ledger_entry(e) for e in page], total, limit, offset, 200)


@bp.post("/api/ledger-entries/<entry_id>/reverse")
def reverse_entry(entry_id):
    require_roles(["POOL_ACCOUNTANT"])
    e = db.ledger_entries.get(entry_id)
    if not e:
        raise_err("ERR_NOT_FOUND", "Ledger entry not found")
    if e["kind"] != "ADVANCE_CREDIT":
        raise_err("ERR_REVERSAL_NOT_ALLOWED", "Only ADVANCE_CREDIT entries may be reversed")
    # already reversed?
    for x in db.ledger_entries.values():
        if x["kind"] == "REVERSAL" and x["reversal_of_id"] == e["id"]:
            raise_err("ERR_REVERSAL_NOT_ALLOWED", "Entry has already been reversed")
    pool = db.pools.get(e["pool_id"])
    if not pool or pool["status"] != "ACCRUING":
        raise_err("ERR_REVERSAL_NOT_ALLOWED", "Pool is not ACCRUING")
    rev = db.stamp_ledger({
        "member_id": e["member_id"],
        "pool_id": e["pool_id"],
        "installment_id": None,
        "settlement_id": None,
        "kind": "REVERSAL",
        "amount_cents": -int(e["amount_cents"]),
        "reversal_of_id": e["id"],
    })
    db.ledger_entries[rev["id"]] = rev
    cascade.recompute_member_ledger(e["member_id"])
    return response.success(serializers.ledger_entry(rev), 201)
