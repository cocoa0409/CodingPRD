"""Pass / permit endpoints."""
from flask import Blueprint, request

import store
from errors import err
import core as c

bp = Blueprint("passes", __name__)


@bp.post("/coop/passes")
def create_pass():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff"})
    body = c.get_body()
    member_id = c.require_str(body, "member_id")
    pass_type = c.require_enum(body, "pass_type", {"DAY", "SEASON", "ANNUAL"})
    valid_from = c.require_str(body, "valid_from")
    valid_to = c.require_str(body, "valid_to")
    price_cents = c.require_int(body, "price_cents")
    c.require_owner_member(ctx, member_id)
    c.lookup("members", member_id)
    vf = store._parse_instant(valid_from)
    vt = store._parse_instant(valid_to)
    if not (vt > vf):
        raise err("ERR_INVALID_INTERVAL", "valid_to must be after valid_from")
    p = {
        "member_id": member_id,
        "pass_type": pass_type,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "price_cents": price_cents,
        "voided": False,
    }
    store.stamp_new(p)
    store.passes[p["id"]] = p
    return c.ok(c.ser_pass(p), 201)


@bp.get("/coop/passes")
def list_passes():
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    items = list(store.passes.values())
    if ctx.role == "Member":
        items = [p for p in items if p["member_id"] == ctx.user_id]
    member_id = request.args.get("member_id")
    if member_id is not None:
        items = [p for p in items if p["member_id"] == member_id]
    return c.paginate_and_serialize(items, c.ser_pass)


@bp.get("/coop/passes/<pid>")
def get_pass(pid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    p = c.lookup("passes", pid)
    c.require_owner_member(ctx, p["member_id"])
    return c.ok(c.ser_pass(p))


@bp.post("/coop/passes/<pid>/void")
def void_pass(pid):
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff", "CoopAdmin"})
    p = c.lookup("passes", pid)
    p["voided"] = True
    store.touch(p)
    return c.ok(c.ser_pass(p))
