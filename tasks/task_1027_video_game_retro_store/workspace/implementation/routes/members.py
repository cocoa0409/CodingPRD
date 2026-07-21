from flask import Blueprint

import store
import ledger
from common import (
    authorize, get_json, need, as_str, as_int, as_enum,
    require_found, parse_pagination, paginate,
)
from envelope import object_response, array_response

bp = Blueprint("members", __name__)

TIERS = ("STANDARD", "SILVER", "GOLD")


def _serialize(m):
    return store.serialize(m)


@bp.post("/members")
def create_member():
    authorize(["Clerk", "Manager"])
    body = get_json()
    full_name = as_str(need(body, "full_name"), "full_name")
    email = as_str(need(body, "email"), "email")
    tier = "STANDARD"
    if body.get("tier") is not None:
        tier = as_enum(body["tier"], "tier", TIERS)
    m = store.make_record({
        "full_name": full_name,
        "email": email,
        "tier": tier,
        "store_credit_balance_cents": 0,
        "loyalty_points": 0,
    })
    store.members[m["id"]] = m
    return object_response(_serialize(m), 201)


@bp.get("/members/<mid>")
def get_member(mid):
    authorize(["Member", "Clerk", "Manager"])
    m = require_found(store.members, mid)
    return object_response(_serialize(m), 200)


@bp.get("/members/<mid>/store-credit-entries")
def list_store_credit_entries(mid):
    authorize(["Member", "Clerk", "Manager"])
    require_found(store.members, mid)
    limit, offset = parse_pagination()
    matching = [e for e in store.store_credit_entries.values() if e["member_id"] == mid]
    window, total = paginate(matching, limit, offset)
    return array_response([store.serialize(e) for e in window], limit, offset, total)


@bp.get("/members/<mid>/sales")
def list_member_sales(mid):
    authorize(["Member", "Clerk", "Manager"])
    require_found(store.members, mid)
    limit, offset = parse_pagination()
    matching = [s for s in store.sales.values() if s["member_id"] == mid]
    window, total = paginate(matching, limit, offset)
    return array_response([store.serialize(s) for s in window], limit, offset, total)


@bp.post("/members/<mid>/store-credit/adjustments")
def adjust_store_credit(mid):
    authorize(["Manager"])
    m = require_found(store.members, mid)
    body = get_json()
    amount = as_int(need(body, "amount_cents"), "amount_cents")
    entry = ledger.add_entry(mid, amount, "MANUAL_ADJUSTMENT", None)
    ledger.recompute_balance(m)
    # Endpoint output is the created StoreCreditEntry.
    return object_response(store.serialize(entry), 201)
