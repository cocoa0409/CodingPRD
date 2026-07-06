from flask import Blueprint

import store
import response
import serialize
from errors import ApiError
from helpers import endpoint, get_body, field, lookup, stamp_new, paginate

bp = Blueprint("members", __name__)


@bp.post("/v1/members")
@endpoint(["StoreClerk"])
def create_member():
    body = get_body()
    email = field(body, "email", required=True, kind="str")
    full_name = field(body, "full_name", required=True, kind="str")
    tier = field(body, "membership_tier", kind="str", enum={"BASIC", "PLUS"}, default="BASIC")
    # Uniqueness (priority 8 constraint) -> ERR_DUPLICATE_EMAIL
    for m in store.DB["members"].values():
        if m["email"] == email:
            raise ApiError("ERR_DUPLICATE_EMAIL", "email already registered")
    rec = {"email": email, "full_name": full_name, "membership_tier": tier}
    stamp_new(rec)
    store.DB["members"][rec["id"]] = rec
    return response.created(serialize.member_out(rec))


@bp.get("/v1/members/<member_id>")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def get_member(member_id):
    m = lookup("members", member_id)
    return response.ok(serialize.member_out(m))


@bp.get("/v1/members/<member_id>/wallet-ledger")
@endpoint(["Member", "StoreClerk", "InventoryManager"])
def wallet_ledger(member_id):
    lookup("members", member_id)  # path id resolved before sub-resource
    entries = [e for e in store.DB["wallet_ledger"].values() if e["member_id"] == member_id]
    page, limit, offset, total = paginate(entries)
    return response.listing([serialize.ledger_out(e) for e in page], limit, offset, total)
