"""Campaigns: the brief, the launch, the hold, and the performance report (PRD 3.3, 3.9)."""
from flask import Blueprint, request

import calc
import db
import response
import services
import validate
from auth import ALL_ROLES, endpoint
from errors import ApiError

bp = Blueprint("campaigns", __name__)

REPORT_ROLES = ["AgencyAdmin", "AccountManager", "MediaBuyer", "ClientReviewer"]


@bp.post("/campaigns")
@endpoint(["AccountManager"])
def create_campaign():
    b = validate.body()
    client_id = validate.req_str(b, "client_id")
    sow_id = validate.req_str(b, "sow_id")
    name = validate.req_str(b, "name")
    brief_summary = validate.req_str(b, "brief_summary", max_len=2000)
    objective = validate.req_enum(b, "objective", validate.OBJECTIVES)

    services.must("client", client_id)
    sow = services.must("sow", sow_id)

    # Referential eligibility (priority 14): the SOW must belong to the same advertiser.
    if sow["client_id"] != client_id:
        validate.bad("The referenced SOW belongs to a different advertiser.")

    obj = db.base_entity()
    obj.update(
        {
            "client_id": client_id,
            "sow_id": sow_id,
            "name": name,
            "brief_summary": brief_summary,
            "objective": objective,
            "status": "DRAFT",
        }
    )
    db.CAMPAIGNS[obj["id"]] = obj
    return response.created(db.public(obj))


@bp.get("/campaigns/<cid>")
@endpoint(ALL_ROLES)
def get_campaign(cid):
    return response.ok(db.public(services.must("campaign", cid)))


@bp.get("/campaigns")
@endpoint(ALL_ROLES)
def list_campaigns():
    limit, offset = validate.pagination()
    client_id = request.args.get("client_id")
    sow_id = request.args.get("sow_id")
    status = request.args.get("status")
    rows = db.ordered(db.CAMPAIGNS)
    if client_id:
        rows = [c for c in rows if c["client_id"] == client_id]
    if sow_id:
        rows = [c for c in rows if c["sow_id"] == sow_id]
    if status:
        rows = [c for c in rows if c["status"] == status]
    return response.listing(rows, limit, offset)


@bp.post("/campaigns/<cid>/launch")
@endpoint(["AccountManager"])
def launch_campaign(cid):
    campaign = services.must("campaign", cid)

    # Priority 10: the campaign itself must be DRAFT.
    if campaign["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    if not campaign["brief_summary"] or not campaign["brief_summary"].strip():
        validate.bad("brief_summary must be non-empty before launch.")

    # Priority 11: the owning advertiser must not be on credit hold.
    client = db.CLIENTS.get(campaign["client_id"])
    if client is not None and client["status"] == "CREDIT_HOLD":
        raise ApiError("ERR_CAMPAIGN_ON_HOLD")

    # Priority 12: the governing SOW must be COUNTERSIGNED.
    sow = db.SOWS.get(campaign["sow_id"])
    if sow is None:
        raise ApiError("ERR_SOW_NOT_FOUND")
    services.sow_gate(sow)

    campaign["status"] = "IN_FLIGHT"
    services.touch(campaign)
    return response.ok(db.public(campaign))


@bp.get("/campaigns/<cid>/deliverables")
@endpoint(ALL_ROLES)
def campaign_deliverables(cid):
    services.must("campaign", cid)
    limit, offset = validate.pagination()
    status = request.args.get("status")
    rows = services.deliverables_of_campaign(cid)
    if status:
        rows = [d for d in rows if d["status"] == status]
    return response.listing(rows, limit, offset)


@bp.get("/campaigns/<cid>/vendor-costs")
@endpoint(REPORT_ROLES)
def campaign_vendor_costs(cid):
    services.must("campaign", cid)
    limit, offset = validate.pagination()
    status = request.args.get("status")
    rows = services.vendor_costs_of_campaign(cid)
    if status:
        rows = [v for v in rows if v["status"] == status]
    return response.listing(rows, limit, offset)


@bp.get("/campaigns/<cid>/performance-report")
@endpoint(REPORT_ROLES)
def campaign_performance_report(cid):
    campaign = services.must("campaign", cid)

    delivered = [
        o for o in services.orders_of_campaign(cid) if o["status"] == "DELIVERED"
    ]
    impressions = sum(o["delivered_impressions"] for o in delivered)
    spend = sum(o["delivered_spend_cents"] for o in delivered)
    cpm = (
        calc.rhu(calc.dec(spend) * 1000 / calc.dec(impressions)) if impressions > 0 else 0
    )

    billed_revenue = sum(
        i["total_cents"]
        for i in db.INVOICES.values()
        if i["campaign_id"] == cid and i["approval_status"] == "ISSUED"
    )
    direct_cost = sum(
        t["internal_cost_cents"]
        for t in db.TIME_ENTRIES.values()
        if t["campaign_id"] == cid and t["status"] in ("APPROVED", "BILLED")
    ) + sum(
        (v["actual_amount_cents"] or 0)
        for v in db.VENDOR_COSTS.values()
        if v["campaign_id"] == cid and v["status"] in ("APPROVED", "BILLED")
    )
    profit = billed_revenue - direct_cost
    margin = (
        calc.pct1(calc.dec(profit) / calc.dec(billed_revenue) * 100)
        if billed_revenue > 0
        else 0.0
    )

    return response.ok(
        {
            "campaign_id": campaign["id"],
            "delivered_impressions": impressions,
            "delivered_spend_cents": spend,
            "effective_cpm_cents": cpm,
            "billed_revenue_cents": billed_revenue,
            "direct_cost_cents": direct_cost,
            "agency_gross_profit_cents": profit,
            "gross_margin_pct": margin,
        }
    )
