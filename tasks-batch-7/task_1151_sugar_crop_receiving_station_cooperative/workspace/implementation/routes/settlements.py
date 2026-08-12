from decimal import Decimal

from flask import Blueprint, request as _req

import db
import response
import serializers
import services.cascade as cascade
from errors import raise_err
from middleware import check_member_ownership, require_roles
from routes._common import as_int, body, opt_field, pagination_args, req_field, sorted_page
from services.calc import (
    D,
    q0,
    ticket_sugar_lbs,
    transport_allowance_cents_for_ticket,
)

bp = Blueprint("settlements", __name__)


def _member_net_advance(member_id, pool_id):
    """Net ADVANCE_CREDIT for a member in a pool (ADVANCE_CREDIT + REVERSAL amounts)."""
    total = 0
    for e in db.ledger_entries.values():
        if e["member_id"] != member_id or e["pool_id"] != pool_id:
            continue
        if e["kind"] == "ADVANCE_CREDIT":
            total += int(e["amount_cents"])
        elif e["kind"] == "REVERSAL":
            # reversal references the reversed advance; its amount is already the negation
            orig = db.ledger_entries.get(e["reversal_of_id"])
            if orig and orig["kind"] == "ADVANCE_CREDIT":
                total += int(e["amount_cents"])
    return total


@bp.post("/api/settlements/generate")
def generate_settlements():
    require_roles(["POOL_ACCOUNTANT"])
    data = body()
    campaign_id = req_field(data, "campaign_id")
    campaign = db.campaigns.get(campaign_id)
    if not campaign:
        raise_err("ERR_NOT_FOUND", "Campaign not found")
    pool = cascade.get_campaign_pool(campaign_id)
    if not pool:
        raise_err("ERR_INVALID_STATE", "Campaign has no pool")
    if pool["status"] != "CLOSED":
        raise_err("ERR_INVALID_STATE", "Pool is not CLOSED")

    # members with >= 1 CREDITED ticket for this campaign
    member_tickets = {}
    for t in db.tickets.values():
        if t["status"] != "CREDITED":
            continue
        b = db.bookings.get(t["booking_id"])
        if not b or b["campaign_id"] != campaign_id:
            continue
        member_tickets.setdefault(t["member_id"], []).append(t)

    if not member_tickets:
        return response.success_list([], 0, 0, 0, 201)

    price = D(pool["final_price_cents_per_lb"])
    gross_pool = int(pool["gross_pool_value_cents"])

    raw_by_member = {}
    sugar_by_member = {}
    transport_by_member = {}
    for mid, tickets in member_tickets.items():
        sugar_total = Decimal("0")
        transport_total = 0
        member = db.members.get(mid)
        for t in tickets:
            sugar_total += ticket_sugar_lbs(t)
            transport_total += transport_allowance_cents_for_ticket(t["adjusted_net_tons_final"], member)
        sugar_by_member[mid] = sugar_total
        raw_by_member[mid] = int(q0(sugar_total * price))
        transport_by_member[mid] = int(transport_total)

    delta = gross_pool - sum(raw_by_member.values())
    # largest raw gross entitlement absorbs delta; tie-break member_code ASC
    ordered = sorted(
        raw_by_member.keys(),
        key=lambda mid: (-raw_by_member[mid], db.members[mid]["member_code"]),
    )
    gross_entitlement = dict(raw_by_member)
    if ordered:
        gross_entitlement[ordered[0]] = raw_by_member[ordered[0]] + delta

    created = []
    for mid in ordered:
        s = db.stamp_new({
            "member_id": mid,
            "campaign_id": campaign_id,
            "pool_id": pool["id"],
            "sugar_lbs": sugar_by_member[mid],
            "price_cents_per_lb": D(pool["final_price_cents_per_lb"]),
            "gross_entitlement_cents": int(gross_entitlement[mid]),
            "advances_posted_cents": 0,
            "transport_credit_cents": int(transport_by_member[mid]),
            "final_payment_cents": 0,
            "total_payment_cents": 0,
            "status": "DRAFT",
        })
        db.settlements[s["id"]] = s
        created.append(s)

    return response.success_list([serializers.settlement(s) for s in created], len(created), len(created), 0, 201)


@bp.get("/api/settlements/<settlement_id>")
def get_settlement(settlement_id):
    user_id, role = require_roles(["COOP_ADMIN", "POOL_ACCOUNTANT", "MEMBER"])
    s = db.settlements.get(settlement_id)
    if not s:
        raise_err("ERR_NOT_FOUND", "Settlement not found")
    check_member_ownership(user_id, role, s["member_id"])
    return response.success(serializers.settlement(s), 200)


@bp.get("/api/settlements")
def list_settlements():
    user_id, role = require_roles(["COOP_ADMIN", "POOL_ACCOUNTANT", "MEMBER"])
    member_id = _req.args.get("member_id")
    campaign_id = _req.args.get("campaign_id")
    pool_id = _req.args.get("pool_id")
    status = _req.args.get("status")
    limit, offset = pagination_args()
    if role == "MEMBER":
        member_id = user_id
    items = list(db.settlements.values())
    if member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    if campaign_id is not None:
        items = [s for s in items if s["campaign_id"] == campaign_id]
    if pool_id is not None:
        items = [s for s in items if s["pool_id"] == pool_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = sorted_page(items, limit, offset)
    return response.success_list([serializers.settlement(s) for s in page], total, limit, offset, 200)


@bp.post("/api/settlements/<settlement_id>/issue")
def issue_settlement(settlement_id):
    require_roles(["POOL_ACCOUNTANT"])
    s = db.settlements.get(settlement_id)
    if not s:
        raise_err("ERR_NOT_FOUND", "Settlement not found")
    if s["status"] != "DRAFT":
        raise_err("ERR_INVALID_STATE", "Settlement is not DRAFT")
    pool = db.pools.get(s["pool_id"])
    if pool["status"] != "CLOSED":
        raise_err("ERR_INVALID_STATE", "Pool is not CLOSED")
    advances = _member_net_advance(s["member_id"], s["pool_id"])
    s["advances_posted_cents"] = advances
    s["final_payment_cents"] = int(s["gross_entitlement_cents"]) - advances
    s["total_payment_cents"] = int(s["final_payment_cents"]) + int(s["transport_credit_cents"])
    s["status"] = "ISSUED"
    db.touch(s)
    return response.success(serializers.settlement(s), 200)


@bp.post("/api/settlements/<settlement_id>/dispute")
def dispute_settlement(settlement_id):
    user_id, role = require_roles(["MEMBER"])
    s = db.settlements.get(settlement_id)
    if not s:
        raise_err("ERR_NOT_FOUND", "Settlement not found")
    check_member_ownership(user_id, role, s["member_id"])
    if s["status"] != "ISSUED":
        raise_err("ERR_INVALID_STATE", "Settlement is not ISSUED")
    s["status"] = "DISPUTED"
    db.touch(s)
    return response.success(serializers.settlement(s), 200)


@bp.post("/api/settlements/<settlement_id>/revise")
def revise_settlement(settlement_id):
    require_roles(["POOL_ACCOUNTANT"])
    data = body()
    expected = as_int(req_field(data, "expected_settlement_version"), "expected_settlement_version")
    opt_field(data, "note", None)
    s = db.settlements.get(settlement_id)
    if not s:
        raise_err("ERR_NOT_FOUND", "Settlement not found")
    if s["status"] != "DISPUTED":
        raise_err("ERR_INVALID_STATE", "Settlement is not DISPUTED")
    if expected != s["version"]:
        raise_err("ERR_STALE_VERSION", "expected_settlement_version does not match current settlement version")
    s["status"] = "DRAFT"
    db.touch(s)
    return response.success(serializers.settlement(s), 200)


@bp.post("/api/settlements/<settlement_id>/acknowledge")
def acknowledge_settlement(settlement_id):
    user_id, role = require_roles(["MEMBER"])
    s = db.settlements.get(settlement_id)
    if not s:
        raise_err("ERR_NOT_FOUND", "Settlement not found")
    check_member_ownership(user_id, role, s["member_id"])
    if s["status"] != "ISSUED":
        raise_err("ERR_INVALID_STATE", "Settlement is not ISSUED")
    s["status"] = "ACKNOWLEDGED"
    db.touch(s)
    return response.success(serializers.settlement(s), 200)


@bp.post("/api/settlements/<settlement_id>/mark-paid")
def mark_paid_settlement(settlement_id):
    require_roles(["POOL_ACCOUNTANT"])
    s = db.settlements.get(settlement_id)
    if not s:
        raise_err("ERR_NOT_FOUND", "Settlement not found")
    if s["status"] != "ACKNOWLEDGED":
        raise_err("ERR_INVALID_STATE", "Settlement is not ACKNOWLEDGED")
    pool = db.pools.get(s["pool_id"])
    campaign = db.campaigns.get(s["campaign_id"])

    # FINAL_SETTLEMENT ledger entry
    entry = db.stamp_ledger({
        "member_id": s["member_id"],
        "pool_id": s["pool_id"],
        "installment_id": None,
        "settlement_id": s["id"],
        "kind": "FINAL_SETTLEMENT",
        "amount_cents": int(s["final_payment_cents"]),
        "reversal_of_id": None,
    })
    db.ledger_entries[entry["id"]] = entry

    if int(s["transport_credit_cents"]) > 0:
        te = db.stamp_ledger({
            "member_id": s["member_id"],
            "pool_id": s["pool_id"],
            "installment_id": None,
            "settlement_id": s["id"],
            "kind": "TRANSPORT_CREDIT",
            "amount_cents": int(s["transport_credit_cents"]),
            "reversal_of_id": None,
        })
        db.ledger_entries[te["id"]] = te

    cascade.recompute_member_ledger(s["member_id"])

    s["status"] = "PAID"
    db.touch(s)

    # compound transition: if all settlements of the pool are PAID
    pool_settlements = [x for x in db.settlements.values() if x["pool_id"] == pool["id"]]
    if pool_settlements and all(x["status"] == "PAID" for x in pool_settlements):
        if pool["status"] == "CLOSED":
            pool["status"] = "SETTLED"
            db.touch(pool)
        if campaign["status"] == "SETTLING":
            campaign["status"] = "SETTLED"
            db.touch(campaign)

    return response.success(serializers.settlement(s), 200)
