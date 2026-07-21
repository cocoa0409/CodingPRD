"""Dividend declaration endpoints."""
from flask import Blueprint

import store
from errors import err
import core as c

bp = Blueprint("dividends", __name__)


@bp.post("/coop/dividend-declarations")
def create_declaration():
    ctx = c.authenticate()
    c.authorize(ctx, {"CoopAdmin"})
    body = c.get_body()
    year = c.require_int(body, "year")
    declared_rate = c.require_number(body, "declared_rate")
    for d in store.declarations.values():
        if d["year"] == year:
            raise err("ERR_VALIDATION", "a declaration for this year already exists")
    decl = {
        "year": year,
        "declared_rate": declared_rate,
        "status": "DRAFT",
        "total_payout_cents": None,
        "payouts": None,
    }
    store.stamp_new(decl)
    store.declarations[decl["id"]] = decl
    return c.ok(c.ser_declaration(decl), 201)


@bp.get("/coop/dividend-declarations/<did>")
def get_declaration(did):
    ctx = c.authenticate()
    c.authorize(ctx, {"Member", "StoreStaff", "CoopAdmin"})
    d = c.lookup("declarations", did)
    return c.ok(c.ser_declaration(d))


@bp.post("/coop/dividend-declarations/<did>/finalize")
def finalize(did):
    ctx = c.authenticate()
    c.authorize(ctx, {"CoopAdmin"})
    d = c.lookup("declarations", did)
    if d["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "declaration is not DRAFT")
    rate = d["declared_rate"]
    payouts = []
    total = 0
    members_sorted = sorted(store.members.values(), key=lambda m: m["_seq"])
    for m in members_sorted:
        elig = c.eligible_spend(m["id"])
        if elig >= c.MIN_ELIGIBLE_SPEND_CENTS:
            final = c.floor_mul(elig, rate)
            m["wallet_credit_cents"] += final
            store.touch(m)
            payouts.append({
                "member_id": m["id"],
                "eligible_spend_cents": elig,
                "final_dividend_cents": final,
            })
            total += final
    d["payouts"] = payouts
    d["total_payout_cents"] = total
    d["status"] = "FINALIZED"
    store.touch(d)
    return c.ok(c.ser_declaration(d))
