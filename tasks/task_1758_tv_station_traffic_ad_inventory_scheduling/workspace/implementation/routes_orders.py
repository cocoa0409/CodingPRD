"""Order and order-line routes: entry, lines, and the approval pipeline
(PRD §3.4). Validation pipeline order per PRD §2.10."""

from flask import Blueprint

from domain import (
    SPOT_LENGTHS, active_lines, compute_post_buy, order_has_aired_spot,
    recompute_budget, spawn_spots, teardown_order_spots, cancel_spot_tree,
    spots_of_line,
)
from helpers import (
    auth, created_key, fail, json_body, list_response, new_record, ok_object,
    opt_version_field, parse_iso_date, query_filter, req_int, req_number, touch,
)
from serializers import ser_order, ser_order_line, ser_spot
from store import db

bp = Blueprint("orders", __name__)

READERS_OPS = ("SalesRep", "TrafficManager", "BillingClerk", "StationAdmin")
METHOD_VARIANTS = {"per_spot_strict", "week_averaged"}


def get_order_or_404(order_id):
    rec = db.orders.get(order_id)
    if rec is None:
        fail("ERR_NOT_FOUND", "order %s not found" % order_id)
    return rec


def get_line_or_404(line_id):
    rec = db.order_lines.get(line_id)
    if rec is None:
        fail("ERR_NOT_FOUND", "order line %s not found" % line_id)
    return rec


# ---------------------------------------------------------------------------
# Orders (PRD §3.4)
# ---------------------------------------------------------------------------

@bp.post("/traffic/orders")
def create_order():
    auth("SalesRep")
    data = json_body()
    # Existence (priority 3): body *_id references resolve.
    advertiser_id = data.get("advertiser_id")
    if advertiser_id is not None and advertiser_id not in db.advertisers:
        fail("ERR_NOT_FOUND", "advertiser %s not found" % advertiser_id)
    # Date-window coherence (priority 5): flight end must not precede start.
    start_raw = data.get("flight_start_date")
    end_raw = data.get("flight_end_date")
    start = end = None
    if isinstance(start_raw, str):
        try:
            start = parse_iso_date(start_raw, "flight_start_date").isoformat()
        except Exception:
            start = None
    if isinstance(end_raw, str):
        try:
            end = parse_iso_date(end_raw, "flight_end_date").isoformat()
        except Exception:
            end = None
    if start is not None and end is not None and end < start:
        fail("ERR_DATE_WINDOW", "flight_end_date precedes flight_start_date")
    # Field sanity (priority 13).
    if advertiser_id is None:
        fail("ERR_INVALID_REQUEST", "advertiser_id is required")
    if start is None:
        fail("ERR_INVALID_REQUEST", "flight_start_date is required and must be an ISO date (YYYY-MM-DD)")
    if end is None:
        fail("ERR_INVALID_REQUEST", "flight_end_date is required and must be an ISO date (YYYY-MM-DD)")
    rec = new_record()
    rec.update(
        {
            "advertiser_id": advertiser_id,
            "flight_start_date": start,
            "flight_end_date": end,
            "status": "DRAFT",
            "gross_budget_cents": 0,
            "revision_no": 0,
        }
    )
    db.orders[rec["id"]] = rec
    return ok_object(ser_order(rec), 201)


@bp.get("/traffic/orders")
def list_orders():
    auth(*READERS_OPS)
    items = list(db.orders.values())
    advertiser_id = query_filter("advertiser_id")
    if advertiser_id is not None:
        items = [o for o in items if o["advertiser_id"] == advertiser_id]
    status = query_filter("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    return list_response(items, ser_order)


@bp.get("/traffic/orders/<order_id>")
def get_order(order_id):
    auth(*READERS_OPS)
    return ok_object(ser_order(get_order_or_404(order_id)))


# ---------------------------------------------------------------------------
# Order lines (PRD §3.4)
# ---------------------------------------------------------------------------

@bp.post("/traffic/orders/<order_id>/lines")
def create_order_line(order_id):
    auth("SalesRep")
    order = get_order_or_404(order_id)  # path id first
    data = json_body()
    program_id = data.get("program_id")
    if program_id is not None and program_id not in db.programs:
        fail("ERR_NOT_FOUND", "program %s not found" % program_id)
    # State legality (priority 4): lines may be added only in DRAFT/REVISED.
    if order["status"] not in ("DRAFT", "REVISED"):
        fail(
            "ERR_INVALID_STATE",
            "order in status %s cannot accept new lines" % order["status"],
        )
    # Field sanity (priority 13).
    if program_id is None:
        fail("ERR_INVALID_REQUEST", "program_id is required")
    weeks_requested = req_int(data, "weeks_requested", min_value=1)
    spots_per_week = req_int(data, "spots_per_week", min_value=1)
    spot_length_seconds = req_int(data, "spot_length_seconds", domain=SPOT_LENGTHS)
    gross_rate_cents = req_int(data, "gross_rate_cents", min_value=1)
    guaranteed_rating = req_number(data, "guaranteed_rating", min_value=0)
    rec = new_record()
    rec.update(
        {
            "order_id": order["id"],
            "program_id": program_id,
            "weeks_requested": weeks_requested,
            "spots_per_week": spots_per_week,
            "spot_length_seconds": spot_length_seconds,
            "gross_rate_cents": gross_rate_cents,
            "guaranteed_rating": guaranteed_rating,
            "status": "ACTIVE",
        }
    )
    db.order_lines[rec["id"]] = rec
    recompute_budget(order)
    touch(order)
    return ok_object(ser_order_line(rec), 201)


@bp.get("/traffic/orders/<order_id>/lines")
def list_order_lines(order_id):
    auth(*READERS_OPS)
    get_order_or_404(order_id)
    items = [l for l in db.order_lines.values() if l["order_id"] == order_id]
    status = query_filter("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    return list_response(items, ser_order_line)


@bp.get("/traffic/order-lines/<line_id>")
def get_order_line(line_id):
    auth(*READERS_OPS)
    return ok_object(ser_order_line(get_line_or_404(line_id)))


@bp.post("/traffic/order-lines/<line_id>/cancel")
def cancel_order_line(line_id):
    auth("SalesRep")
    line = get_line_or_404(line_id)
    order = db.orders[line["order_id"]]
    # State legality: single-line cancel only while the order is DRAFT/REVISED
    # and the line is still ACTIVE.
    if order["status"] not in ("DRAFT", "REVISED") or line["status"] != "ACTIVE":
        fail(
            "ERR_INVALID_STATE",
            "line cannot be cancelled in its current state",
        )
    line["status"] = "CANCELLED"
    touch(line)
    # Cancel the line's non-aired spots; SCHEDULED spots on unfinalized log
    # dates release their booked seconds (PRD §3.4).
    for spot in sorted(spots_of_line(line["id"]), key=created_key):
        cancel_spot_tree(spot)
    recompute_budget(order)
    touch(order)
    return ok_object(ser_order_line(line))


@bp.get("/traffic/order-lines/<line_id>/spots")
def list_line_spots(line_id):
    auth(*READERS_OPS)
    get_line_or_404(line_id)
    items = spots_of_line(line_id)
    status = query_filter("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    return list_response(items, ser_spot)


# ---------------------------------------------------------------------------
# Order workflow actions (PRD §3.4, SCAFFOLD §1.2 Order machine)
# ---------------------------------------------------------------------------

@bp.post("/traffic/orders/<order_id>/submit")
def submit_order(order_id):
    auth("SalesRep")
    order = get_order_or_404(order_id)
    if order["status"] not in ("DRAFT", "REVISED"):
        fail(
            "ERR_INVALID_STATE",
            "order in status %s cannot be submitted" % order["status"],
        )
    if not active_lines(order):
        fail("ERR_INVALID_STATE", "order has no ACTIVE order line")
    order["status"] = "SUBMITTED"
    touch(order)
    return ok_object(ser_order(order))


@bp.post("/traffic/orders/<order_id>/approve")
def approve_order(order_id):
    auth("TrafficManager")
    order = get_order_or_404(order_id)
    data = json_body()
    if order["status"] != "SUBMITTED":
        fail(
            "ERR_INVALID_STATE",
            "order in status %s cannot be approved" % order["status"],
        )
    # Credit rule (priority 12): outstanding exposure over APPROVED/COMPLETED
    # orders plus this order's budget must not exceed the credit limit; a
    # total exactly equal to the limit passes (PRD §3.4).
    advertiser = db.advertisers[order["advertiser_id"]]
    outstanding = sum(
        o["gross_budget_cents"]
        for o in db.orders.values()
        if o["advertiser_id"] == advertiser["id"] and o["status"] in ("APPROVED", "COMPLETED")
    )
    if outstanding + order["gross_budget_cents"] > advertiser["credit_limit_cents"]:
        fail(
            "ERR_CREDIT_LIMIT",
            "approval would push advertiser outstanding exposure above credit_limit_cents",
        )
    # OCC guard (priority 14): expected_order_version is a non-optional input
    # and is checked last (PRD §2.8/§2.10).
    expected = opt_version_field(data, "expected_order_version")
    if expected is None:
        fail("ERR_INVALID_REQUEST", "expected_order_version is required")
    if expected != order["version"]:
        fail(
            "ERR_STALE_ORDER_VERSION",
            "order version has advanced since the client's last read",
        )
    order["status"] = "APPROVED"
    spawn_spots(order)
    touch(order)
    return ok_object(ser_order(order))


@bp.post("/traffic/orders/<order_id>/reject")
def reject_order(order_id):
    auth("TrafficManager")
    order = get_order_or_404(order_id)
    if order["status"] != "SUBMITTED":
        fail(
            "ERR_INVALID_STATE",
            "order in status %s cannot be rejected" % order["status"],
        )
    order["status"] = "DRAFT"
    touch(order)
    return ok_object(ser_order(order))


@bp.post("/traffic/orders/<order_id>/revise")
def revise_order(order_id):
    auth("SalesRep")
    order = get_order_or_404(order_id)
    if order["status"] != "APPROVED":
        fail(
            "ERR_INVALID_STATE",
            "order in status %s cannot be revised" % order["status"],
        )
    if order_has_aired_spot(order):
        fail("ERR_INVALID_STATE", "order with AIRED spots cannot be revised")
    teardown_order_spots(order)
    order["status"] = "REVISED"
    order["revision_no"] += 1
    touch(order)
    return ok_object(ser_order(order))


@bp.post("/traffic/orders/<order_id>/cancel")
def cancel_order(order_id):
    auth("SalesRep")
    order = get_order_or_404(order_id)
    if order["status"] in ("DRAFT", "SUBMITTED", "REVISED"):
        pass  # unconditional from these states (PRD §3.4)
    elif order["status"] == "APPROVED":
        if order_has_aired_spot(order):
            fail("ERR_INVALID_STATE", "order with AIRED spots cannot be cancelled")
        teardown_order_spots(order)
    else:
        fail(
            "ERR_INVALID_STATE",
            "order in status %s cannot be cancelled" % order["status"],
        )
    order["status"] = "CANCELLED"
    touch(order)
    return ok_object(ser_order(order))


# ---------------------------------------------------------------------------
# Post-buy report (PRD §3.8)
# ---------------------------------------------------------------------------

@bp.get("/traffic/orders/<order_id>/post-buy")
def post_buy_report(order_id):
    auth(*READERS_OPS)
    order = get_order_or_404(order_id)
    variant = query_filter("method_variant") or "per_spot_strict"
    if variant not in METHOD_VARIANTS:
        fail(
            "ERR_INVALID_REQUEST",
            "method_variant must be one of %s" % sorted(METHOD_VARIANTS),
        )
    return ok_object(compute_post_buy(order, variant))
