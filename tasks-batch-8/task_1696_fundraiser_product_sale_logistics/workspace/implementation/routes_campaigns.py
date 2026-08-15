"""Campaign endpoints: CRUD + lifecycle transitions + scoped list sub-resources."""

from flask import Blueprint, request

import db
import errors
import helpers
import middleware
import services
from db import clock, _parse_iso
from helpers import (
    get_campaign, new_id, now_iso, paginate, sort_created, ledger_sort,
    req_string, req_int, req_datetime, opt_int,
    serialize_campaign, serialize_group, serialize_product, serialize_prize,
    serialize_seller, serialize_supplier_order, serialize_event,
    serialize_ledger_entry,
)
from middleware import get_body, parse_pagination
from response import success_object, success_list

bp = Blueprint("campaigns", __name__)

CAMPAIGN_STATUSES = (
    "DRAFT", "OPEN", "ORDERING_CLOSED", "SUPPLIER_ORDERED", "DELIVERED",
    "SORTED", "DISTRIBUTION_COMPLETE", "RECONCILED", "CLOSED", "CANCELLED",
)


@bp.post("/fundraiser/campaigns")
def create_campaign():
    middleware.require_role("FundraiserAdmin")
    body = get_body(required=True)
    name = req_string(body, "name")
    school_name = req_string(body, "school_name")
    ows = req_datetime(body, "order_window_start")
    owe = req_datetime(body, "order_window_end")
    edd = req_datetime(body, "expected_delivery_date")
    bps = req_int(body, "default_profit_share_bps", minimum=0, maximum=10000)
    if not (owe > ows):
        raise errors.err_validation("order_window_end must be strictly later than order_window_start")
    if not (edd > owe):
        raise errors.err_validation("expected_delivery_date must be strictly later than order_window_end")
    cid = new_id()
    campaign = {
        "id": cid,
        "name": name,
        "school_name": school_name,
        "order_window_start": body["order_window_start"],
        "order_window_end": body["order_window_end"],
        "expected_delivery_date": body["expected_delivery_date"],
        "default_profit_share_bps": bps,
        "status": "DRAFT",
        "distribution_completed_at": None,
        "gross_sales_cents": 0,
        "family_credits_cents": 0,
        "estimated_supplier_cost_cents": 0,
        "actual_supplier_cost_cents": 0,
        "general_fund_cents": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.campaigns[cid] = campaign
    return success_object(serialize_campaign(campaign), status=201)


@bp.get("/fundraiser/campaigns/<cid>")
def read_campaign(cid):
    middleware.any_role()
    campaign = get_campaign(cid)
    return success_object(serialize_campaign(campaign))


@bp.patch("/fundraiser/campaigns/<cid>")
def patch_campaign(cid):
    middleware.require_role("FundraiserAdmin")
    campaign = get_campaign(cid)
    body = get_body(required=True)
    # Body schema: expected_campaign_version required
    if "expected_campaign_version" not in body or not isinstance(body.get("expected_campaign_version"), int) or isinstance(body.get("expected_campaign_version"), bool):
        raise errors.err_validation("expected_campaign_version is required and must be an integer")
    expected = body["expected_campaign_version"]
    # Validate optional fields' types before any mutation
    new_values = {}
    if "name" in body:
        new_values["name"] = req_string(body, "name")
    if "school_name" in body:
        new_values["school_name"] = req_string(body, "school_name")
    if "order_window_start" in body:
        new_values["order_window_start"] = req_datetime(body, "order_window_start")
    if "order_window_end" in body:
        new_values["order_window_end"] = req_datetime(body, "order_window_end")
    if "expected_delivery_date" in body:
        new_values["expected_delivery_date"] = req_datetime(body, "expected_delivery_date")
    if "default_profit_share_bps" in body:
        new_values["default_profit_share_bps"] = req_int(body, "default_profit_share_bps", minimum=0, maximum=10000)
    # OCC check (priority 7)
    if expected != campaign["version"]:
        raise errors.err_stale_version()
    # State gate (priority 8): DRAFT only
    if campaign["status"] != "DRAFT":
        raise errors.err_invalid_state("Campaign settings may only be edited while DRAFT")
    # Cross-field temporal constraints on the merged result
    ows = _parse_iso(new_values.get("order_window_start", campaign["order_window_start"]))
    owe = _parse_iso(new_values.get("order_window_end", campaign["order_window_end"]))
    edd = _parse_iso(new_values.get("expected_delivery_date", campaign["expected_delivery_date"]))
    if not (owe > ows):
        raise errors.err_validation("order_window_end must be strictly later than order_window_start")
    if not (edd > owe):
        raise errors.err_validation("expected_delivery_date must be strictly later than order_window_end")
    for k, v in new_values.items():
        if k in ("order_window_start", "order_window_end", "expected_delivery_date"):
            campaign[k] = body[k]  # keep original string form
        else:
            campaign[k] = v
    helpers.touch(campaign)
    return success_object(serialize_campaign(campaign))


@bp.post("/fundraiser/campaigns/<cid>/open")
def open_campaign(cid):
    middleware.require_role("FundraiserAdmin")
    campaign = get_campaign(cid)
    get_body()
    if campaign["status"] != "DRAFT":
        raise errors.err_invalid_state("Campaign is not DRAFT")
    has_active_product = any(
        p["campaign_id"] == cid and p["status"] == "ACTIVE" for p in db.products.values()
    )
    has_group = any(g["campaign_id"] == cid for g in db.groups.values())
    if not (has_active_product and has_group):
        raise errors.err_campaign_not_ready()
    if not (clock.now() < _parse_iso(campaign["order_window_end"])):
        raise errors.err_invalid_state("Order window has already ended")
    campaign["status"] = "OPEN"
    helpers.touch(campaign)
    return success_object(serialize_campaign(campaign))


@bp.post("/fundraiser/campaigns/<cid>/close-ordering")
def close_ordering(cid):
    middleware.require_role("FundraiserAdmin")
    campaign = get_campaign(cid)
    get_body()
    if campaign["status"] != "OPEN":
        raise errors.err_invalid_state("Campaign is not OPEN")
    if not (clock.now() >= _parse_iso(campaign["order_window_end"])):
        raise errors.err_order_window_not_yet_closed()
    # Cascade: DRAFT orders -> CANCELLED (no ledger impact); SUBMITTED -> LOCKED
    affected_sellers = set()
    for o in list(db.orders.values()):
        if o["campaign_id"] != cid:
            continue
        if o["status"] == "DRAFT":
            o["status"] = "CANCELLED"
            helpers.touch(o)
            affected_sellers.add(o["seller_id"])
        elif o["status"] == "SUBMITTED":
            o["status"] = "LOCKED"
            helpers.touch(o)
            affected_sellers.add(o["seller_id"])
    for sid in affected_sellers:
        services.recompute_seller_metrics(db.sellers[sid])
    campaign["status"] = "ORDERING_CLOSED"
    helpers.touch(campaign)
    services.recompute_campaign_totals(campaign)
    return success_object(serialize_campaign(campaign))


@bp.post("/fundraiser/campaigns/<cid>/mark-sorted")
def mark_sorted(cid):
    middleware.require_role("GroupCoordinator")
    campaign = get_campaign(cid)
    get_body()
    if campaign["status"] != "DELIVERED":
        raise errors.err_invalid_state("Campaign is not DELIVERED")
    pending = [t for t in db.sort_tickets.values()
               if t["campaign_id"] == cid and t["status"] == "PENDING"]
    if pending:
        raise errors.err_unverified_sort_tickets()
    for o in db.orders.values():
        if o["campaign_id"] == cid and o["status"] != "CANCELLED" and o["fulfillment_status"] == "PENDING":
            o["fulfillment_status"] = "SORTED"
            helpers.touch(o)
    campaign["status"] = "SORTED"
    helpers.touch(campaign)
    return success_object(serialize_campaign(campaign))


@bp.post("/fundraiser/campaigns/<cid>/complete-distribution")
def complete_distribution(cid):
    middleware.require_role("GroupCoordinator")
    campaign = get_campaign(cid)
    get_body()
    if campaign["status"] != "SORTED":
        raise errors.err_invalid_state("Campaign is not SORTED")
    has_completed_event = any(
        e["campaign_id"] == cid and e["status"] == "COMPLETED"
        for e in db.distribution_events.values()
    )
    if not has_completed_event:
        raise errors.err_invalid_state("No COMPLETED distribution event exists")
    campaign_event_ids = {e["id"] for e in db.distribution_events.values() if e["campaign_id"] == cid}
    open_appts = [
        a for a in db.pickup_appointments.values()
        if a["distribution_event_id"] in campaign_event_ids and a["status"] == "BOOKED"
    ]
    if open_appts:
        raise errors.err_open_claims_or_returns("Pickup appointments remain BOOKED")
    # Distribute PAID orders
    for o in db.orders.values():
        if o["campaign_id"] != cid or o["status"] == "CANCELLED":
            continue
        if o["payment_status"] == "PAID" and o["fulfillment_status"] == "SORTED":
            o["fulfillment_status"] = "DISTRIBUTED"
            helpers.touch(o)
            for ln in db.order_lines.values():
                if ln["order_id"] != o["id"]:
                    continue
                eff_qty = ln["quantity"] - ln["sort_shortage_qty"] - ln["claim_resolved_refund_qty"]
                if eff_qty:
                    product = db.products[ln["product_id"]]
                    product["distributed_units"] += eff_qty
                    product["surplus_units"] -= eff_qty
                    helpers.touch(product)
    campaign["distribution_completed_at"] = now_iso()
    campaign["status"] = "DISTRIBUTION_COMPLETE"
    helpers.touch(campaign)
    services.full_prize_sweep(cid)
    return success_object(serialize_campaign(campaign))


@bp.post("/fundraiser/campaigns/<cid>/reconcile")
def reconcile_campaign(cid):
    middleware.require_role("FundraiserAdmin")
    campaign = get_campaign(cid)
    get_body()
    if campaign["status"] != "DISTRIBUTION_COMPLETE":
        raise errors.err_invalid_state("Campaign is not DISTRIBUTION_COMPLETE")
    from datetime import timedelta
    window_end = _parse_iso(campaign["distribution_completed_at"]) + timedelta(days=services.RETURN_WINDOW_DAYS)
    if not (clock.now() > window_end):
        raise errors.err_return_window_not_elapsed()
    open_claims = [c for c in db.claims.values()
                   if c["campaign_id"] == cid and c["status"] in ("SUBMITTED", "APPROVED")]
    open_returns = [r for r in db.return_requests.values()
                    if r["campaign_id"] == cid and r["status"] in ("REQUESTED", "APPROVED", "REJECTED")]
    if open_claims or open_returns:
        raise errors.err_open_claims_or_returns()
    campaign["status"] = "RECONCILED"
    helpers.touch(campaign)
    return success_object(serialize_campaign(campaign))


@bp.post("/fundraiser/campaigns/<cid>/close")
def close_campaign(cid):
    middleware.require_role("Treasurer")
    campaign = get_campaign(cid)
    get_body()
    if campaign["status"] != "RECONCILED":
        raise errors.err_invalid_state("Campaign is not RECONCILED")
    services.recompute_campaign_totals(campaign)
    services.run_final_settlement(campaign)
    # Sweep: QUEUED awards -> EXPIRED
    for a in db.prize_awards.values():
        if a["campaign_id"] == cid and a["status"] == "QUEUED":
            a["status"] = "EXPIRED"
            helpers.touch(a)
    # Sweep: PAID + distributed orders -> COMPLETED; unpaid SUBMITTED/LOCKED -> CANCELLED with reversal
    for o in list(db.orders.values()):
        if o["campaign_id"] != cid:
            continue
        if o["payment_status"] == "PAID" and o["fulfillment_status"] in ("DISTRIBUTED", "PARTIALLY_RETURNED", "RETURNED") and o["status"] in ("SUBMITTED", "LOCKED"):
            o["status"] = "COMPLETED"
            helpers.touch(o)
        elif o["status"] in ("SUBMITTED", "LOCKED") and o["cleared_cents"] == 0:
            services.cancel_order(o, post_reversal=True)
    campaign["status"] = "CLOSED"
    helpers.touch(campaign)
    services.recompute_campaign_totals(campaign)
    return success_object(serialize_campaign(campaign))


@bp.post("/fundraiser/campaigns/<cid>/cancel")
def cancel_campaign(cid):
    middleware.require_role("FundraiserAdmin")
    campaign = get_campaign(cid)
    get_body()
    if campaign["status"] not in ("DRAFT", "OPEN"):
        raise errors.err_invalid_state("Campaign may only be cancelled from DRAFT or OPEN")
    for o in db.orders.values():
        if o["campaign_id"] == cid and o["cleared_cents"] > 0:
            raise errors.err_campaign_cancel_blocked()
    # Cascade: DRAFT/SUBMITTED orders -> CANCELLED (SUBMITTED post reversal)
    for o in list(db.orders.values()):
        if o["campaign_id"] != cid:
            continue
        if o["status"] == "DRAFT":
            o["status"] = "CANCELLED"
            helpers.touch(o)
        elif o["status"] == "SUBMITTED":
            services.cancel_order(o, post_reversal=True)
    # RECORDED payments -> VOIDED
    for p in db.payments.values():
        po = db.orders.get(p["order_id"])
        if po and po["campaign_id"] == cid and p["status"] == "RECORDED":
            p["status"] = "VOIDED"
            helpers.touch(p)
    campaign["status"] = "CANCELLED"
    helpers.touch(campaign)
    services.recompute_campaign_totals(campaign)
    return success_object(serialize_campaign(campaign))


# ---------------------------------------------------------------------------
# Campaign-scoped list sub-resources
# ---------------------------------------------------------------------------

@bp.get("/fundraiser/campaigns/<cid>/groups")
def list_campaign_groups(cid):
    middleware.any_role()
    get_campaign(cid)
    limit, offset = parse_pagination()
    items = sort_created([g for g in db.groups.values() if g["campaign_id"] == cid])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_group(g) for g in page], limit, offset, total)


@bp.get("/fundraiser/campaigns/<cid>/products")
def list_campaign_products(cid):
    middleware.any_role()
    get_campaign(cid)
    limit, offset = parse_pagination()
    items = [p for p in db.products.values() if p["campaign_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_product(p) for p in page], limit, offset, total)


@bp.get("/fundraiser/campaigns/<cid>/prizes")
def list_campaign_prizes(cid):
    middleware.any_role()
    get_campaign(cid)
    limit, offset = parse_pagination()
    items = sort_created([p for p in db.prizes.values() if p["campaign_id"] == cid])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_prize(p) for p in page], limit, offset, total)


@bp.get("/fundraiser/campaigns/<cid>/sellers")
def list_campaign_sellers(cid):
    middleware.any_role()
    get_campaign(cid)
    limit, offset = parse_pagination()
    items = [s for s in db.sellers.values() if s["campaign_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_seller(s) for s in page], limit, offset, total)


@bp.get("/fundraiser/campaigns/<cid>/supplier-orders")
def list_campaign_supplier_orders(cid):
    middleware.any_role()
    get_campaign(cid)
    limit, offset = parse_pagination()
    items = sort_created([s for s in db.supplier_orders.values() if s["campaign_id"] == cid])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_supplier_order(s) for s in page], limit, offset, total)


@bp.get("/fundraiser/campaigns/<cid>/distribution-events")
def list_campaign_events(cid):
    middleware.any_role()
    get_campaign(cid)
    limit, offset = parse_pagination()
    items = [e for e in db.distribution_events.values() if e["campaign_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items = sort_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_event(e) for e in page], limit, offset, total)


@bp.get("/fundraiser/campaigns/<cid>/ledger")
def list_campaign_ledger(cid):
    middleware.require_role("FundraiserAdmin", "Treasurer")
    get_campaign(cid)
    limit, offset = parse_pagination()
    items = ledger_sort([e for e in db.ledger_entries.values() if e["campaign_id"] == cid])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_ledger_entry(e) for e in page], limit, offset, total)
