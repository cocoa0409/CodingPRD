"""Member endpoints + logical clock."""
from flask import Blueprint

import store
from errors import err
import core as c

bp = Blueprint("members", __name__)


def _get_member(mid):
    return c.lookup("members", mid)


@bp.post("/coop/members")
def register():
    # Public: no auth required.
    body = c.get_body()
    email = c.require_str(body, "email")
    full_name = c.require_str(body, "full_name")
    tier = c.opt_enum(body, "membership_tier", {"BASIC", "PREMIER"}, "BASIC")
    for m in store.members.values():
        if m["email"] == email:
            raise err("ERR_VALIDATION", "email already registered")
    member = {
        "email": email,
        "full_name": full_name,
        "membership_tier": tier,
        "membership_status": "PENDING",
        "join_fee_cents": c.JOIN_FEE[tier],
        "wallet_credit_cents": 0,
    }
    store.stamp_new(member)
    store.members[member["id"]] = member
    return c.ok(c.ser_member(member), 201)


@bp.get("/coop/members")
def list_members():
    ctx = c.authenticate()
    c.authorize(ctx, {"StoreStaff", "CoopAdmin"})
    from flask import request
    status = request.args.get("status")
    items = [m for m in store.members.values() if status is None or m["membership_status"] == status]
    return c.paginate_and_serialize(items, c.ser_member)


@bp.get("/coop/members/<mid>")
def get_member(mid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    c.require_owner_member(ctx, mid)
    m = _get_member(mid)
    return c.ok(c.ser_member(m))


@bp.get("/coop/members/<mid>/summary")
def member_summary(mid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    c.require_owner_member(ctx, mid)
    m = _get_member(mid)
    elig = c.eligible_spend(mid)
    summary = {
        "member_id": mid,
        "eligible_spend_cents": elig,
        "provisional_dividend_cents": c.floor_mul(elig, c.PROVISIONAL_RATE),
        "loyalty_points_balance": c.loyalty_balance(mid),
        "wallet_credit_cents": m["wallet_credit_cents"],
    }
    return c.ok(summary)


@bp.get("/coop/members/<mid>/loyalty-ledger")
def member_ledger(mid):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    c.require_owner_member(ctx, mid)
    _get_member(mid)
    items = [e for e in store.loyalty_ledger.values() if e["member_id"] == mid]
    return c.paginate_and_serialize(items, c.ser_ledger)


def _transition(mid, allowed_roles, from_states, to_state):
    ctx = c.authenticate()
    c.authorize(ctx, allowed_roles)
    m = _get_member(mid)
    if m["membership_status"] not in from_states:
        raise err("ERR_INVALID_STATE", "member not in a state permitting this action")
    m["membership_status"] = to_state
    store.touch(m)
    return c.ok(c.ser_member(m))


@bp.post("/coop/members/<mid>/activate")
def activate(mid):
    return _transition(mid, {"StoreStaff", "CoopAdmin"}, {"PENDING"}, "ACTIVE")


@bp.post("/coop/members/<mid>/lapse")
def lapse(mid):
    return _transition(mid, {"CoopAdmin"}, {"ACTIVE"}, "LAPSED")


@bp.post("/coop/members/<mid>/reactivate")
def reactivate(mid):
    return _transition(mid, {"StoreStaff", "CoopAdmin"}, {"LAPSED"}, "ACTIVE")


@bp.post("/coop/members/<mid>/close")
def close(mid):
    return _transition(mid, {"CoopAdmin"}, {"ACTIVE", "LAPSED"}, "CLOSED")


@bp.post("/coop/members/<mid>/wallet/adjustments")
def wallet_adjust(mid):
    ctx = c.authenticate()
    c.authorize(ctx, {"CoopAdmin"})
    body = c.get_body()
    delta = c.require_int(body, "delta_cents")
    c.require_str(body, "reason")
    m = _get_member(mid)
    m["wallet_credit_cents"] += delta
    store.touch(m)
    return c.ok(c.ser_member(m))
