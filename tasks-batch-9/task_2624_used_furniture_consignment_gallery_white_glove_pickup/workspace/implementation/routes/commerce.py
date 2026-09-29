"""Sales, white-glove delivery orders and damage claims (PRD 3.8)."""

from flask import Blueprint

import auth
import calc
import envelope
import serializers as ser
import services
import store
import validation as v
from errors import fail
from store import db

bp = Blueprint("commerce", __name__)

FAULT_PARTIES = ("GALLERY", "CONSIGNOR", "BUYER", "UNDETERMINED")


def _return_to_floor(item):
    """The shared 'piece goes back on the floor' cascade (reversal / refusal)."""
    services.recompute_current_price(item)
    if int(item.get("markdown_sequence") or 0) >= 2:
        item["lifecycle_state"] = "MARKED_DOWN"
    else:
        item["lifecycle_state"] = "ON_FLOOR"
    store.touch(item)


def _reverse_sale_ledger(sale, item):
    consignor = db.consignors.get(item["consignor_id"]) if item is not None else None
    if consignor is not None:
        services.mint_entry(
            consignor,
            "SALE_REVERSAL_DEBIT",
            -int(sale["consignor_share_cents"]),
            "sale reversal unwinding the credit on sale %s" % sale["id"],
            item_id=sale["item_id"],
        )


# ---------------------------------------------------------------------------
# sales
# ---------------------------------------------------------------------------
@bp.post("/sales")
def create_sale():
    user_id, role = auth.require("GalleryManager", "FloorOperator")
    data = v.body()

    raw_item = v.raw_fk(data, "item_id")
    if raw_item is not None and raw_item not in db.items:
        fail("ERR_ITEM_NOT_FOUND")
    raw_buyer = v.raw_fk(data, "buyer_id")
    if raw_buyer is not None and raw_buyer not in db.buyers:
        fail("ERR_BUYER_NOT_FOUND")

    item_id = v.req_id(data, "item_id")
    buyer_id = v.req_id(data, "buyer_id")
    sale_price_cents = v.req_int(data, "sale_price_cents", minimum=1)

    item = db.items.get(item_id)
    if item is None:
        fail("ERR_ITEM_NOT_FOUND")
    buyer = db.buyers.get(buyer_id)
    if buyer is None:
        fail("ERR_BUYER_NOT_FOUND")

    if item["lifecycle_state"] not in ("ON_FLOOR", "MARKED_DOWN"):
        fail("ERR_ITEM_STATE_INVALID")
    if item["inventory_state"] != "IN_CUSTODY":
        fail("ERR_ITEM_CUSTODY_INVALID")
    if buyer["status"] != "ACTIVE":
        fail("ERR_BUYER_BLOCKED")
    if sale_price_cents < calc.sale_floor_cents(item["current_price_cents"]):
        fail("ERR_SALE_BELOW_FLOOR")

    pct, consignor_share, gallery_share = calc.consignor_split(
        item["category"], sale_price_cents, item["markdown_sequence"]
    )
    row = store.new_row(
        db.sales,
        {
            "item_id": item_id,
            "buyer_id": buyer_id,
            "sale_price_cents": sale_price_cents,
            "markdown_sequence_at_sale": int(item["markdown_sequence"] or 0),
            "split_pct_applied": float(pct),
            "consignor_share_cents": consignor_share,
            "gallery_share_cents": gallery_share,
            "refund_cents": 0,
            "status": "COMPLETED",
            "sold_at": store.now(),
            "reversed_at": None,
            "sold_by_user_id": user_id,
        },
    )
    item["lifecycle_state"] = "SOLD"
    store.touch(item)
    consignor = db.consignors.get(item["consignor_id"])
    if consignor is not None:
        services.mint_entry(
            consignor,
            "SALE_CREDIT",
            consignor_share,
            "consignor share of sale %s" % row["id"],
            item_id=item_id,
        )
    return envelope.created(ser.sale(row))


@bp.get("/sales/<sale_id>")
def get_sale(sale_id):
    user_id, role = auth.require(
        "GalleryManager", "FloorOperator", "LogisticsCoordinator", "Consignor", "Buyer"
    )
    row = v.lookup(db.sales, sale_id, "ERR_SALE_NOT_FOUND")
    item = db.items.get(row["item_id"])
    auth.scope_consignor(role, user_id, item["consignor_id"] if item else None)
    auth.scope_buyer(role, user_id, row["buyer_id"])
    return envelope.ok(ser.sale(row))


@bp.get("/sales")
def list_sales():
    auth.require("GalleryManager", "FloorOperator", "LogisticsCoordinator")
    limit, offset = v.pagination()
    rows = store.ordered(db.sales)
    for field in ("item_id", "buyer_id", "status"):
        wanted = v.q(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.sale, page), limit, offset, len(rows))


@bp.post("/sales/<sale_id>/reverse")
def reverse_sale(sale_id):
    auth.require("GalleryManager")
    row = v.lookup(db.sales, sale_id, "ERR_SALE_NOT_FOUND")
    if row["status"] != "COMPLETED":
        fail("ERR_SALE_ALREADY_REVERSED")
    item = db.items.get(row["item_id"])
    if item is not None and item["inventory_state"] != "IN_CUSTODY":
        fail("ERR_ITEM_CUSTODY_INVALID")

    row["status"] = "REVERSED"
    row["reversed_at"] = store.now()
    store.touch(row)
    _reverse_sale_ledger(row, item)
    if item is not None:
        _return_to_floor(item)
    for order in store.ordered(db.delivery_orders):
        if order["sale_id"] == row["id"] and order["status"] == "SCHEDULED":
            order["status"] = "CANCELLED"
            store.touch(order)
    return envelope.ok(ser.sale(row))


# ---------------------------------------------------------------------------
# delivery orders
# ---------------------------------------------------------------------------
@bp.post("/delivery-orders")
def create_delivery_order():
    user_id, role = auth.require("LogisticsCoordinator")
    data = v.body()

    raw_sale = v.raw_fk(data, "sale_id")
    if raw_sale is not None and raw_sale not in db.sales:
        fail("ERR_SALE_NOT_FOUND")
    raw_crew = v.raw_fk(data, "crew_id")
    if raw_crew is not None and raw_crew not in db.crews:
        fail("ERR_CREW_NOT_FOUND")

    sale_id = v.req_id(data, "sale_id")
    crew_id = v.req_id(data, "crew_id")
    window_start = v.req_dt(data, "window_start")
    window_end = v.req_dt(data, "window_end")

    sale = db.sales.get(sale_id)
    if sale is None:
        fail("ERR_SALE_NOT_FOUND")
    crew = db.crews.get(crew_id)
    if crew is None:
        fail("ERR_CREW_NOT_FOUND")
    item = db.items.get(sale["item_id"])

    if item is not None and item["inventory_state"] != "IN_CUSTODY":
        fail("ERR_ITEM_CUSTODY_INVALID")
    if sale["status"] != "COMPLETED":
        fail("ERR_SALE_ALREADY_REVERSED")

    overlapping = 0
    for other in db.delivery_orders.values():
        if other["crew_id"] != crew_id or other["status"] != "SCHEDULED":
            continue
        if window_start < other["window_end"] and other["window_start"] < window_end:
            overlapping += 1
    if overlapping + 1 > int(crew["max_concurrent_jobs"]):
        fail("ERR_CREW_CAPACITY_EXCEEDED")

    if not window_start < window_end:
        fail("ERR_WINDOW_ORDER_INVALID")

    buyer = db.buyers.get(sale["buyer_id"])
    elevator_used = bool(buyer["has_elevator"]) if buyer else False
    if elevator_used:
        stair_flights = 0
    else:
        stair_flights = max(int(buyer["floor_number"]) - 1, 0) if buyer else 0
    fee = calc.delivery_fee(stair_flights, elevator_used, item["category"] if item else None)

    row = store.new_row(
        db.delivery_orders,
        {
            "sale_id": sale_id,
            "crew_id": crew_id,
            "window_start": window_start,
            "window_end": window_end,
            "stair_flights": stair_flights,
            "elevator_used": elevator_used,
            "delivery_fee_cents": fee,
            "status": "SCHEDULED",
            "outcome_recorded_at": None,
            "claim_window_ends_at": None,
            "scheduled_by_user_id": user_id,
        },
    )
    return envelope.created(ser.delivery_order(row))


@bp.get("/delivery-orders/<order_id>")
def get_delivery_order(order_id):
    user_id, role = auth.require("LogisticsCoordinator", "GalleryManager", "Buyer")
    row = v.lookup(db.delivery_orders, order_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    sale = db.sales.get(row["sale_id"])
    auth.scope_buyer(role, user_id, sale["buyer_id"] if sale else None)
    return envelope.ok(ser.delivery_order(row))


@bp.get("/delivery-orders")
def list_delivery_orders():
    auth.require("LogisticsCoordinator", "GalleryManager")
    limit, offset = v.pagination()
    rows = store.ordered(db.delivery_orders)
    for field in ("sale_id", "crew_id", "status"):
        wanted = v.q(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.delivery_order, page), limit, offset, len(rows))


@bp.post("/delivery-orders/<order_id>/complete")
def complete_delivery_order(order_id):
    auth.require("LogisticsCoordinator")
    row = v.lookup(db.delivery_orders, order_id, "ERR_DELIVERY_ORDER_NOT_FOUND")
    data = v.body()
    outcome = v.req_enum(data, "outcome", ("DELIVERED", "REFUSED"))

    sale = db.sales.get(row["sale_id"])
    if sale is None or sale["status"] != "COMPLETED":
        fail("ERR_SALE_ALREADY_REVERSED")
    if row["status"] != "SCHEDULED":
        fail("ERR_SALE_ALREADY_REVERSED")
    item = db.items.get(sale["item_id"])

    if outcome == "DELIVERED":
        if item is not None and item["inventory_state"] != "IN_CUSTODY":
            fail("ERR_ITEM_CUSTODY_INVALID")
        row["status"] = "DELIVERED"
        row["outcome_recorded_at"] = store.now()
        row["claim_window_ends_at"] = store.add_days(store.now(), calc.CLAIM_WINDOW_DAYS)
        sale["status"] = "SETTLED"
        store.touch(sale)
        if item is not None:
            item["lifecycle_state"] = "SETTLED"
            item["inventory_state"] = "RELEASED"
            item["placement_zone_id"] = None
            store.touch(item)
        store.touch(row)
        return envelope.ok(ser.delivery_order(row))

    row["status"] = "REFUSED"
    row["outcome_recorded_at"] = store.now()
    store.touch(row)
    sale["status"] = "REVERSED"
    sale["reversed_at"] = store.now()
    store.touch(sale)
    _reverse_sale_ledger(sale, item)
    if item is not None:
        _return_to_floor(item)
    return envelope.ok(ser.delivery_order(row))


# ---------------------------------------------------------------------------
# damage claims
# ---------------------------------------------------------------------------
def _claim_context(claim):
    order = db.delivery_orders.get(claim["delivery_order_id"])
    sale = db.sales.get(order["sale_id"]) if order else None
    item = db.items.get(sale["item_id"]) if sale else None
    return order, sale, item


@bp.post("/damage-claims")
def create_claim():
    user_id, role = auth.require("Buyer", "LogisticsCoordinator")
    data = v.body()

    raw_order = v.raw_fk(data, "delivery_order_id")
    if raw_order is not None and raw_order not in db.delivery_orders:
        fail("ERR_DELIVERY_ORDER_NOT_FOUND")

    delivery_order_id = v.req_id(data, "delivery_order_id")
    claim_amount_cents = v.req_int(data, "claim_amount_cents", minimum=1)
    description = v.req_str(data, "description")
    fault_party = v.opt_enum(data, "fault_party", FAULT_PARTIES)

    order = db.delivery_orders.get(delivery_order_id)
    if order is None:
        fail("ERR_DELIVERY_ORDER_NOT_FOUND")
    sale = db.sales.get(order["sale_id"])
    auth.scope_buyer(role, user_id, sale["buyer_id"] if sale else None)

    ends_at = order["claim_window_ends_at"]
    if ends_at is None or store.now() >= ends_at:
        fail("ERR_CLAIM_WINDOW_CLOSED")
    if sale is not None and claim_amount_cents > int(sale["sale_price_cents"]):
        fail("ERR_CLAIM_EXCEEDS_SALE")

    row = store.new_row(
        db.damage_claims,
        {
            "delivery_order_id": delivery_order_id,
            "claim_amount_cents": claim_amount_cents,
            "description": description,
            "status": "SUBMITTED",
            "resubmission_count": 0,
            "fault_party": fault_party,
            "adjudicated_amount_cents": None,
            "gallery_absorbed_cents": None,
            "consignor_debited_cents": None,
            "info_request_note": None,
            "adjudicated_by_user_id": None,
        },
    )
    return envelope.created(ser.damage_claim(row))


@bp.get("/damage-claims/<claim_id>")
def get_claim(claim_id):
    user_id, role = auth.require(
        "GalleryManager", "LogisticsCoordinator", "Buyer", "Consignor"
    )
    row = v.lookup(db.damage_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    order, sale, item = _claim_context(row)
    auth.scope_buyer(role, user_id, sale["buyer_id"] if sale else None)
    auth.scope_consignor(role, user_id, item["consignor_id"] if item else None)
    return envelope.ok(ser.damage_claim(row))


@bp.get("/damage-claims")
def list_claims():
    auth.require("GalleryManager", "LogisticsCoordinator")
    limit, offset = v.pagination()
    rows = store.ordered(db.damage_claims)
    for field in ("delivery_order_id", "status"):
        wanted = v.q(field)
        if wanted is not None:
            rows = [r for r in rows if r[field] == wanted]
    page = v.window(rows, limit, offset)
    return envelope.listing(ser.many(ser.damage_claim, page), limit, offset, len(rows))


@bp.post("/damage-claims/<claim_id>/request-info")
def request_info(claim_id):
    auth.require("GalleryManager")
    row = v.lookup(db.damage_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    data = v.body()
    note = v.req_str(data, "info_request_note")

    if row["status"] != "SUBMITTED":
        fail("ERR_CLAIM_STATE_INVALID")
    if int(row["resubmission_count"]) >= 2:
        fail("ERR_CLAIM_RESUBMIT_LIMIT")

    row["status"] = "INFO_REQUESTED"
    row["info_request_note"] = note
    store.touch(row)
    return envelope.ok(ser.damage_claim(row))


@bp.post("/damage-claims/<claim_id>/resubmit")
def resubmit_claim(claim_id):
    auth.require("Buyer")
    row = v.lookup(db.damage_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    data = v.body()
    description = v.req_str(data, "description")
    withdraw = v.opt_bool(data, "withdraw", False)

    if row["status"] != "INFO_REQUESTED":
        fail("ERR_CLAIM_STATE_INVALID")
    if int(row["resubmission_count"]) >= 2:
        fail("ERR_CLAIM_RESUBMIT_LIMIT")

    if withdraw:
        row["status"] = "WITHDRAWN"
    else:
        row["status"] = "SUBMITTED"
        row["resubmission_count"] = int(row["resubmission_count"]) + 1
        row["description"] = description
    store.touch(row)
    return envelope.ok(ser.damage_claim(row))


@bp.post("/damage-claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    user_id, role = auth.require("GalleryManager")
    row = v.lookup(db.damage_claims, claim_id, "ERR_CLAIM_NOT_FOUND")
    order, sale, item = _claim_context(row)
    # ladder 3: the coordinator who booked the delivery may not rule on it
    if order is not None and order.get("scheduled_by_user_id") == user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")

    data = v.body()
    approve = v.req_bool(data, "approve")
    fault_party = v.req_enum(data, "fault_party", FAULT_PARTIES)

    if row["status"] != "SUBMITTED":
        fail("ERR_CLAIM_STATE_INVALID")
    if sale is not None and int(row["claim_amount_cents"]) > int(sale["sale_price_cents"]):
        fail("ERR_CLAIM_EXCEEDS_SALE")

    row["fault_party"] = fault_party
    row["adjudicated_by_user_id"] = user_id
    if not approve:
        row["status"] = "DENIED"
        row["adjudicated_amount_cents"] = 0
        row["gallery_absorbed_cents"] = 0
        row["consignor_debited_cents"] = 0
        store.touch(row)
        return envelope.ok(ser.damage_claim(row))

    adjudicated, gallery_absorbed, consignor_debited = calc.damage_allocation(
        row["claim_amount_cents"], sale["sale_price_cents"] if sale else 0, fault_party
    )
    row["status"] = "APPROVED"
    row["adjudicated_amount_cents"] = adjudicated
    row["gallery_absorbed_cents"] = gallery_absorbed
    row["consignor_debited_cents"] = consignor_debited
    store.touch(row)

    if sale is not None:
        sale["refund_cents"] = int(sale["refund_cents"]) + adjudicated
        store.touch(sale)
    if consignor_debited > 0 and item is not None:
        consignor = db.consignors.get(item["consignor_id"])
        if consignor is not None:
            services.mint_entry(
                consignor,
                "DAMAGE_ALLOCATION_DEBIT",
                -consignor_debited,
                "damage chargeback on claim %s" % row["id"],
                item_id=item["id"],
            )
    return envelope.ok(ser.damage_claim(row))
