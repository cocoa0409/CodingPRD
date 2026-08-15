"""Orders: confirmation (the pivot), cancellation, invoicing, closing, and
order lines (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_ORDER_NOT_FOUND,
    ERR_ORDER_LINE_NOT_FOUND,
    ERR_ORDER_NOT_QUOTED,
    ERR_ORDER_NOT_CONFIRMED,
    ERR_ORDER_NOT_CANCELLABLE,
    ERR_ORDER_NOT_FULLY_DELIVERED,
    ERR_ORDER_UNPAID,
    ERR_OPEN_CLAIMS_EXIST,
    ERR_OPEN_RETURNS_EXIST,
    ERR_ACTIVE_DELIVERY_EXISTS,
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_LIEN_BLOCKS_ORDER,
    ERR_LOT_UNAVAILABLE,
    ERR_SURGE_ALLOCATION_EXCEEDED,
    ERR_STALE_VERSION,
)
from middleware import authorized, check_contractor_owns
from response import success_object
from routes.helpers import body, render_list, render_one
from services.core import get_or_404, mutate, available_bundles, credit_available
from services.calculations import (
    compute_order_pricing, active_surge_event_for_branch, order_lines_of,
    unconsumed_allocation_for,
)
from services.order_ops import recompute_fulfillment  # noqa: F401  (re-exported for deliveries)
from services.sweep import recompute_allocation_status

bp = Blueprint("orders", __name__)

ORDER_READ_ROLES = ["PlatformAdmin", "BranchManager", "SalesRep", "CreditAnalyst", "Dispatcher"]
ORDER_READ_ROLES_WITH_CONTRACTOR = ORDER_READ_ROLES + ["Contractor"]
LINE_READ_ROLES = ["PlatformAdmin", "BranchManager", "SalesRep", "CreditAnalyst",
                   "Dispatcher", "WarehouseClerk"]

OPEN_CLAIM_STATES = ("FILED", "UNDER_REVIEW", "DISPUTED", "APPROVED")
OPEN_RETURN_STATES = ("REQUESTED", "APPROVED")


def _order_context(order):
    job = db["job_accounts"][order["job_account_id"]]
    account = db["contractor_accounts"][job["contractor_account_id"]]
    branch = db["branches"][order["branch_id"]]
    return job, account, branch


def _version_matches(expected, current):
    """OCC comparison tolerant of JSON string-vs-int transport of the version."""
    try:
        return int(expected) == int(current)
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

@bp.get("/roofing/orders")
def list_orders():
    caller = authorized(ORDER_READ_ROLES)
    return render_list(caller, "orders",
                       filters={"status": request.args.get("status"),
                                "job_account_id": request.args.get("job_account_id"),
                                "takeoff_id": request.args.get("takeoff_id"),
                                "branch_id": request.args.get("branch_id"),
                                "storm_surge_event_id": request.args.get("storm_surge_event_id")})


@bp.get("/roofing/orders/<rid>")
def get_order(rid):
    caller = authorized(ORDER_READ_ROLES_WITH_CONTRACTOR)
    rec = get_or_404("orders", rid, ERR_ORDER_NOT_FOUND)
    job = db["job_accounts"].get(rec["job_account_id"])
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)
    return render_one("orders", rec)


@bp.get("/roofing/orders/<rid>/lines")
def list_order_lines(rid):
    caller = authorized(LINE_READ_ROLES + ["Contractor"])
    order = get_or_404("orders", rid, ERR_ORDER_NOT_FOUND)
    job = db["job_accounts"].get(order["job_account_id"])
    check_contractor_owns(caller, job["contractor_account_id"] if job else None)
    lines = [l for l in db["order_lines"].values() if l["order_id"] == order["id"]]
    return render_list(caller, "order_lines", base_records=lines)


@bp.get("/roofing/order-lines")
def list_all_lines():
    caller = authorized(LINE_READ_ROLES)
    return render_list(caller, "order_lines",
                       filters={"product_id": request.args.get("product_id"),
                                "inventory_lot_id": request.args.get("inventory_lot_id"),
                                "order_id": request.args.get("order_id")})


@bp.get("/roofing/order-lines/<rid>")
def get_line(rid):
    caller = authorized(LINE_READ_ROLES)
    rec = get_or_404("order_lines", rid, ERR_ORDER_LINE_NOT_FOUND)
    return render_one("order_lines", rec)


# ---------------------------------------------------------------------------
# Confirm — the pivot (PRD 3.4)
# ---------------------------------------------------------------------------

@bp.post("/roofing/orders/<rid>/confirm")
def confirm_order(rid):
    caller = authorized(["Contractor"])
    order = get_or_404("orders", rid, ERR_ORDER_NOT_FOUND)
    job, account, branch = _order_context(order)
    check_contractor_owns(caller, account["id"])

    # Optimistic concurrency on the account version (PRD 2.10): a stale credit
    # view is rejected before anything else about the account is trusted.
    data = body()
    expected = data.get("expected_contractor_account_version")
    if expected is not None and not _version_matches(expected, account["version"]):
        raise_error(ERR_STALE_VERSION,
                    "expected_contractor_account_version does not match the account version")

    if order["status"] != "QUOTED":
        raise_error(ERR_ORDER_NOT_QUOTED, "confirm requires the order to be in QUOTED")
    if account["status"] == "SUSPENDED":
        raise_error(ERR_ACCOUNT_NOT_ACTIVE,
                    "new order confirmations are blocked while the account is SUSPENDED")

    lines = order_lines_of(order["id"])

    # Lot availability: every line must find a lot at the fulfilling branch
    # holding the same product with enough available bundles.
    picks = {}
    for line in lines:
        eligible = [lot for lot in db["inventory_lots"].values()
                    if lot["branch_id"] == order["branch_id"]
                    and lot["product_id"] == line["product_id"]
                    and available_bundles(lot) >= line["quantity_bundles"]]
        if not eligible:
            raise_error(ERR_LOT_UNAVAILABLE,
                        "no lot at the fulfilling branch can satisfy every order line")
        eligible.sort(key=lambda l: (l["created_at"], l["_seq"]))
        picks[line["id"]] = eligible[0]  # earliest created_at wins (PRD 2.7)

    # Surge linkage: in SURGE mode the order auto-links to the branch's single
    # ACTIVE event and each line must fit the contractor's unconsumed grant.
    surge_event = None
    if branch["surge_mode"] == "SURGE":
        surge_event = active_surge_event_for_branch(branch["id"])
        for line in lines:
            unconsumed = unconsumed_allocation_for(
                surge_event["id"], account["id"], line["product_id"]) if surge_event else 0
            if line["quantity_bundles"] > unconsumed:
                raise_error(ERR_SURGE_ALLOCATION_EXCEEDED,
                            "line quantity exceeds the contractor's unconsumed surge allocation")

    # Price with locked unit prices before the fiscal gates evaluate.
    for line in lines:
        product = db["products"][line["product_id"]]
        line["unit_price_cents"] = product["base_price_per_bundle_cents"]
        line["extended_price_cents"] = line["quantity_bundles"] * line["unit_price_cents"]
    compute_order_pricing(order, account, branch, surge_event)

    if credit_available(account) < order["total_cents"]:
        raise_error(ERR_CREDIT_LIMIT_EXCEEDED,
                    "credit_available_cents does not cover order total_cents")
    if job["lien_status"] == "LIEN_RECORDED":
        raise_error(ERR_LIEN_BLOCKS_ORDER,
                    "a job account in LIEN_RECORDED blocks new order confirmations")

    # Commit: reserve lots, link surge, consume allocation, place the hold.
    for line in lines:
        lot = picks[line["id"]]
        line["inventory_lot_id"] = lot["id"]
        lot["reserved_bundles"] += line["quantity_bundles"]
        mutate(lot)
        mutate(line)
    if surge_event is not None:
        order["storm_surge_event_id"] = surge_event["id"]
        for line in lines:
            remaining = line["quantity_bundles"]
            targets = [a for a in db["allocations"].values()
                       if a["storm_surge_event_id"] == surge_event["id"]
                       and a["contractor_account_id"] == account["id"]
                       and a["product_id"] == line["product_id"]
                       and a["status"] in ("GRANTED", "PARTIALLY_CONSUMED")]
            targets.sort(key=lambda a: (a["created_at"], a["_seq"]))
            for alloc in targets:
                if remaining <= 0:
                    break
                take = min(remaining, alloc["granted_bundles"] - alloc["consumed_bundles"])
                if take <= 0:
                    continue
                alloc["consumed_bundles"] += take
                remaining -= take
                recompute_allocation_status(alloc)
                mutate(alloc)
    order["status"] = "CONFIRMED"
    mutate(order)
    account["pending_delivery_hold_cents"] += order["total_cents"]
    mutate(account)  # the +1 version mutation stale writers trip over
    return render_one("orders", order)


# ---------------------------------------------------------------------------
# Cancel (both flavors), invoice, close
# ---------------------------------------------------------------------------

@bp.post("/roofing/orders/<rid>/cancel")
def cancel_order(rid):
    caller = authorized(["Contractor", "SalesRep"])
    order = get_or_404("orders", rid, ERR_ORDER_NOT_FOUND)
    job, account, branch = _order_context(order)

    if caller.role == "Contractor":
        check_contractor_owns(caller, account["id"])
        if order["status"] != "QUOTED":
            raise_error(ERR_ORDER_NOT_CANCELLABLE,
                        "a contractor may cancel only while the order is QUOTED")
        # No holds were placed yet — nothing to release.
    else:  # SalesRep
        if order["status"] != "CONFIRMED":
            raise_error(ERR_ORDER_NOT_CANCELLABLE,
                        "a sales rep may cancel only while the order is CONFIRMED")
        active = [d for d in db["deliveries"].values()
                  if d["order_id"] == order["id"] and d["status"] in ("SCHEDULED", "EN_ROUTE")]
        if active:
            raise_error(ERR_ACTIVE_DELIVERY_EXISTS,
                        "an active delivery blocks cancellation")
        for line in order_lines_of(order["id"]):
            lot = db["inventory_lots"].get(line["inventory_lot_id"])
            if lot is not None:
                lot["reserved_bundles"] -= line["quantity_bundles"]
                mutate(lot)
        account["pending_delivery_hold_cents"] -= order["total_cents"]
        mutate(account)
        if order["storm_surge_event_id"]:
            for line in order_lines_of(order["id"]):
                remaining = line["quantity_bundles"]
                targets = [a for a in db["allocations"].values()
                           if a["storm_surge_event_id"] == order["storm_surge_event_id"]
                           and a["contractor_account_id"] == account["id"]
                           and a["product_id"] == line["product_id"]
                           and a["consumed_bundles"] > 0
                           and a["status"] in ("GRANTED", "PARTIALLY_CONSUMED", "CONSUMED")]
                targets.sort(key=lambda a: (a["created_at"], a["_seq"]), reverse=True)
                for alloc in targets:
                    if remaining <= 0:
                        break
                    give = min(remaining, alloc["consumed_bundles"])
                    alloc["consumed_bundles"] -= give
                    remaining -= give
                    recompute_allocation_status(alloc)
                    mutate(alloc)

    order["status"] = "CANCELLED"
    mutate(order)
    return render_one("orders", order)


@bp.post("/roofing/orders/<rid>/invoice")
def invoice_order(rid):
    authorized(["CreditAnalyst"])
    order = get_or_404("orders", rid, ERR_ORDER_NOT_FOUND)
    job, account, branch = _order_context(order)
    if order["status"] != "CONFIRMED":
        raise_error(ERR_ORDER_NOT_CONFIRMED, "invoice requires the order to be CONFIRMED")
    if order["fulfillment_status"] not in ("DELIVERED", "RETURN_ADJUSTED"):
        raise_error(ERR_ORDER_NOT_FULLY_DELIVERED,
                    "an order is invoiced once it has been delivered")
    if order["payment_status"] != "UNPAID":
        raise_error(ERR_ORDER_NOT_CONFIRMED,
                    "invoice requires payment_status UNPAID")
    order["payment_status"] = "INVOICED"
    order["_invoice_outstanding_cents"] = order["total_cents"]
    order["_invoiced_at"] = order["updated_at"]
    mutate(order)
    account["pending_delivery_hold_cents"] -= order["total_cents"]
    account["open_balance_cents"] += order["total_cents"]
    mutate(account)
    job["job_balance_cents"] += order["total_cents"]
    mutate(job)
    return render_one("orders", order)


@bp.post("/roofing/orders/<rid>/close")
def close_order(rid):
    authorized(["SalesRep"])
    order = get_or_404("orders", rid, ERR_ORDER_NOT_FOUND)
    if order["status"] != "CONFIRMED":
        raise_error(ERR_ORDER_NOT_CONFIRMED, "close requires the order to be CONFIRMED")
    if order["fulfillment_status"] not in ("DELIVERED", "RETURN_ADJUSTED"):
        raise_error(ERR_ORDER_NOT_FULLY_DELIVERED,
                    "close requires fulfillment DELIVERED or RETURN_ADJUSTED")
    if order["payment_status"] not in ("PAID", "CREDITED"):
        raise_error(ERR_ORDER_UNPAID, "close requires payment PAID or CREDITED")
    delivery_ids = {d["id"] for d in db["deliveries"].values() if d["order_id"] == order["id"]}
    open_claims = [c for c in db["damage_claims"].values()
                   if c["delivery_id"] in delivery_ids and c["status"] in OPEN_CLAIM_STATES]
    if open_claims:
        raise_error(ERR_OPEN_CLAIMS_EXIST, "a non-terminal damage claim blocks close")
    open_returns = [r for r in db["returns"].values()
                    if r["order_id"] == order["id"] and r["status"] in OPEN_RETURN_STATES]
    if open_returns:
        raise_error(ERR_OPEN_RETURNS_EXIST, "a non-terminal return blocks close")
    order["status"] = "CLOSED"
    mutate(order)
    return render_one("orders", order)
