"""Distributions, DRIP, and allocations (PRD §3.6)."""
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import err
from middleware import require_role
from response import success, list_success
from services import calc, domain, serialize
from services.paginate import get_pagination, order_and_page
from services import validate as V

bp = Blueprint("distributions", __name__)

READ_ROLES = {"FundManager", "ComplianceOfficer", "Operator", "Investor"}


@bp.post("/funds/<fund_id>/distributions")
def declare_distribution(fund_id):
    require_role({"FundManager"})
    domain.get_fund(fund_id)
    body = V.get_body()
    period_label = V.req_str(body, "period_label")
    dps = V.req_number(body, "dividend_per_share_cents")
    if dps <= 0:
        raise err("ERR_INVALID_REQUEST", "dividend_per_share_cents must be > 0")

    for d in db.distributions.values():
        if d["fund_id"] == fund_id and d["period_label"] == period_label:
            raise err("ERR_DUPLICATE", "Distribution period_label already exists for fund")

    e = db.base_fields()
    e.update({
        "fund_id": fund_id,
        "period_label": period_label,
        "dividend_per_share_cents": dps,
        "status": "DECLARED",
        "total_paid_cents": 0,
        "drip_shares_minted": calc.round_shares(0),
    })
    db.distributions[e["id"]] = e
    return success(serialize.distribution(e), status=201)


@bp.get("/funds/<fund_id>/distributions")
def list_fund_distributions(fund_id):
    require_role(READ_ROLES)
    domain.get_fund(fund_id)
    limit, offset = get_pagination()
    items = [d for d in db.distributions.values() if d["fund_id"] == fund_id]
    page, total = order_and_page(items, limit, offset)
    return list_success([serialize.distribution(d) for d in page], limit, offset, total)


@bp.get("/distributions/<did>")
def get_distribution(did):
    require_role(READ_ROLES)
    e = domain.get_distribution(did)
    return success(serialize.distribution(e))


@bp.post("/distributions/<did>/pay")
def pay_distribution(did):
    require_role({"Operator"})
    dist = domain.get_distribution(did)
    if dist["status"] != "DECLARED":
        raise err("ERR_INVALID_STATE", "Distribution not DECLARED")
    fund = domain.get_fund(dist["fund_id"])
    if fund["current_valuation_seq"] < 1:
        raise err("ERR_NO_VALUATION", "No valuation posted; cannot price DRIP")

    dps = dist["dividend_per_share_cents"]
    sc_ids = domain.share_class_ids_of_fund(fund["id"])
    sc_by_id = {sc_id: db.share_classes[sc_id] for sc_id in sc_ids}

    # Eligible holdings: shares_owned > 0, processed in created_at ASC
    eligible = [h for h in db.holdings.values()
                if h["share_class_id"] in sc_ids and h["shares_owned"] > 0]
    eligible.sort(key=lambda h: h["_seq"])

    total_paid = 0
    drip_minted = Decimal("0")
    affected_holdings = []

    for h in eligible:
        gross = calc.gross_dividend(h["shares_owned"], dps)
        sc = sc_by_id[h["share_class_id"]]
        is_drip = (h["drip_elected"] and sc["drip_eligible"] and fund["status"] == "OPEN")
        mode = "DRIP" if is_drip else "CASH"
        ds = calc.round_shares(0)
        if mode == "DRIP":
            ds = calc.drip_shares(gross, fund["nav_per_share_cents"])
            h["shares_owned"] = calc.round_shares(h["shares_owned"] + ds)
            h["cost_basis_cents"] += gross
            drip_minted += ds
            affected_holdings.append(h)

        alloc = db.base_fields(full=False)
        alloc.update({
            "distribution_id": dist["id"],
            "holding_id": h["id"],
            "gross_dividend_cents": gross,
            "mode": mode,
            "drip_shares": ds,
        })
        db.allocations[alloc["id"]] = alloc
        total_paid += gross

    dist["status"] = "PAID"
    dist["total_paid_cents"] = total_paid
    dist["drip_shares_minted"] = calc.round_shares(drip_minted)

    # Recompute fund derived fields after DRIP minting
    domain.recompute_fund_derived(fund)

    for h in affected_holdings:
        db.touch(h)
    db.touch(dist)
    db.touch(fund)
    return success(serialize.distribution(dist))


@bp.post("/distributions/<did>/cancel")
def cancel_distribution(did):
    require_role({"FundManager"})
    dist = domain.get_distribution(did)
    if dist["status"] != "DECLARED":
        raise err("ERR_INVALID_STATE", "Distribution not DECLARED")
    dist["status"] = "CANCELLED"
    db.touch(dist)
    return success(serialize.distribution(dist))


@bp.get("/distributions/<did>/allocations")
def list_distribution_allocations(did):
    require_role(READ_ROLES)
    domain.get_distribution(did)
    limit, offset = get_pagination()
    items = [a for a in db.allocations.values() if a["distribution_id"] == did]
    hid = request.args.get("holding_id")
    if hid is not None:
        items = [a for a in items if a["holding_id"] == hid]
    page, total = order_and_page(items, limit, offset)
    return list_success([serialize.allocation(a) for a in page], limit, offset, total)
