"""Sales orders: lines, pricing, the two status dimensions and fulfilment."""

from flask import Blueprint, request

from calc import (
    ROLLUP_LINE_STATUSES,
    assess_order_fees,
    contract_remaining,
    lines_of,
    malt_lot_available,
    recompute_brewer,
    refresh_line_derived,
    rollup_order,
    shipments_of_order,
)
from cascades import (
    hold_staged_shipments,
    post_receivable,
    release_commitments,
    supersede_shipments,
)
from db import by_created, db, new_entity, now, set_dt, touch
from errors import ApiError
from middleware import ALL_ROLES, require, scope_brewer
from response import array_response, object_response
from serialize import line_out, order_out
from util import D
from validation import (
    body,
    f_dec,
    f_dt,
    f_enum,
    f_str,
    filter_exists,
    must_exist,
    paginate,
    pagination,
)

bp = Blueprint("orders", __name__)

CANCELLABLE = ("DRAFT", "CONFIRMED", "PICKED", "SHIPPED")


# ---------------------------------------------------------------------------
# Order shell
# ---------------------------------------------------------------------------

@bp.post("/sales-orders")
def create_order():
    actor = require(("Brewer", "AllocationManager"))
    payload = body()
    brewer_id = f_str(payload, "brewer_id", min_len=1)
    ship_date, ship_raw = f_dt(payload, "requested_ship_date", required=True)
    purchase_order_ref = f_str(
        payload, "purchase_order_ref", required=False, max_len=100
    )

    scope_brewer(actor, brewer_id)
    must_exist("brewers", brewer_id)

    order = new_entity()
    order.update(
        {
            "brewer_id": brewer_id,
            "purchase_order_ref": purchase_order_ref,
            "fulfillment_status": "DRAFT",
            "credit_status": "PENDING_REVIEW",
            "subtotal_cents": 0,
            "volume_discount_cents": 0,
            "chargeable_lbs": D(0),
            "freight_cents": 0,
            "pallet_break_fee_cents": 0,
            "small_order_surcharge_cents": 0,
            "total_cents": 0,
            "fee_variant": None,
            "freight_tier_applied": None,
            "final_freight_adjustment_cents": 0,
            "requires_cold_chain": False,
            "line_count": 0,
            "invoiced_at": None,
            "delivered_at": None,
            "cancel_reason": None,
        }
    )
    set_dt(order, "requested_ship_date", ship_date, ship_raw)
    db.orders[order["id"]] = order
    return object_response(order_out(order), 201)


@bp.get("/sales-orders/<order_id>")
def get_order(order_id):
    actor = require(ALL_ROLES)
    order = must_exist("orders", order_id)
    scope_brewer(actor, order["brewer_id"])
    return object_response(order_out(order))


@bp.get("/sales-orders")
def list_orders():
    actor = require(ALL_ROLES)
    limit, offset = pagination()
    args = request.args
    brewer_id = args.get("brewer_id")
    fulfillment_status = args.get("fulfillment_status")
    credit_status = args.get("credit_status")
    if brewer_id:
        scope_brewer(actor, brewer_id)
    filter_exists("brewers", brewer_id)

    items = []
    for order in db.orders.values():
        if brewer_id and order["brewer_id"] != brewer_id:
            continue
        if fulfillment_status and order["fulfillment_status"] != fulfillment_status:
            continue
        if credit_status and order["credit_status"] != credit_status:
            continue
        if actor.is_brewer and order["brewer_id"] != actor.user_id:
            continue
        items.append(order)
    items = by_created(items)
    page = paginate(items, limit, offset)
    return array_response([order_out(o) for o in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Lines
# ---------------------------------------------------------------------------

def _mismatch(message):
    return ApiError("ERR_ITEM_REFERENCE_MISMATCH", message)


@bp.post("/sales-orders/<order_id>/lines")
def add_line(order_id):
    actor = require(("Brewer", "AllocationManager"))
    payload = body()
    item_type = f_enum(payload, "item_type", ("HOP", "MALT", "YEAST"), required=True)
    quantity = f_dec(payload, "quantity", required=True, scale=3, exclusive_min=0)
    uom = f_enum(payload, "uom", ("LB", "L"), required=True)
    allocation_source = f_enum(
        payload, "allocation_source", ("CONTRACT", "SPOT"), required=False, default="SPOT"
    )
    variety_id = f_str(payload, "hop_variety_id", required=False, min_len=1)
    contract_id = f_str(payload, "hop_contract_id", required=False, min_len=1)
    lot_id = f_str(payload, "malt_lot_id", required=False, min_len=1)
    job_id = f_str(payload, "yeast_propagation_job_id", required=False, min_len=1)
    unit_price = f_dec(
        payload, "unit_price_cents", required=False, scale=2, minimum=0
    )

    order = must_exist("orders", order_id)
    scope_brewer(actor, order["brewer_id"])
    variety = must_exist("varieties", variety_id) if variety_id else None
    contract = must_exist("contracts", contract_id) if contract_id else None
    lot = must_exist("malt_lots", lot_id) if lot_id else None
    job = must_exist("jobs", job_id) if job_id else None

    # priority 6: a Brewer actor may only address its own brewery's contracts
    if contract is not None:
        scope_brewer(actor, contract["brewer_id"])

    # priority 8: the contract must belong to the ordering brewery
    if contract is not None and contract["brewer_id"] != order["brewer_id"]:
        raise ApiError(
            "ERR_CONTRACT_BREWER_MISMATCH",
            "The referenced contract belongs to a different brewery",
        )

    # priority 9: exactly the reference set for item_type, and a matching uom
    if item_type == "HOP":
        if variety is None or lot is not None or job is not None or uom != "LB":
            raise _mismatch("A HOP line requires hop_variety_id alone and uom LB")
        if allocation_source == "CONTRACT":
            if contract is None:
                raise _mismatch("A CONTRACT hop line requires hop_contract_id")
            if contract["variety_id"] != variety["id"]:
                raise _mismatch(
                    "hop_contract_id and hop_variety_id name different varieties"
                )
        elif contract is not None:
            raise _mismatch("A SPOT hop line may not name a hop_contract_id")
    elif item_type == "MALT":
        if (
            lot is None
            or variety is not None
            or contract is not None
            or job is not None
            or uom != "LB"
        ):
            raise _mismatch("A MALT line requires malt_lot_id alone and uom LB")
        if allocation_source != "SPOT":
            raise _mismatch("MALT lines are always SPOT")
    else:
        if (
            job is None
            or variety is not None
            or contract is not None
            or lot is not None
            or uom != "L"
        ):
            raise _mismatch(
                "A YEAST line requires yeast_propagation_job_id alone and uom L"
            )
        if allocation_source != "SPOT":
            raise _mismatch("YEAST lines are always SPOT")

    # priority 16: lines may only be added to a DRAFT order
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_ORDER_STATE", "Lines may only be added to a DRAFT order"
        )

    # priority 34: the item's own minimum order quantity
    if item_type == "HOP":
        minimum = D(variety["min_order_lbs"])
        cold_chain = bool(variety["cold_storage_required"])
        default_price = (
            D(contract["price_per_lb_cents"])
            if allocation_source == "CONTRACT"
            else D(variety["spot_price_cents_per_lb"])
        )
    elif item_type == "MALT":
        product = db.malt_products[lot["malt_product_id"]]
        minimum = D(product["min_order_lbs"])
        cold_chain = bool(product["cold_storage_required"])
        default_price = D(product["list_price_cents_per_lb"])
    else:
        strain = db.strains[job["yeast_strain_id"]]
        minimum = D(strain["min_batch_l"])
        cold_chain = bool(strain["cold_storage_required"])
        default_price = D(strain["list_price_cents_per_l"])
    if quantity < minimum:
        raise ApiError(
            "ERR_BELOW_MINIMUM_ORDER_QUANTITY",
            "quantity is below the item's minimum order quantity",
        )

    line = new_entity()
    line.update(
        {
            "sales_order_id": order["id"],
            "hop_contract_id": contract["id"] if contract is not None else None,
            "malt_lot_id": lot["id"] if lot is not None else None,
            "yeast_propagation_job_id": job["id"] if job is not None else None,
            "hop_variety_id": variety["id"] if variety is not None else None,
            "item_type": item_type,
            "allocation_source": allocation_source,
            "quantity": quantity,
            "uom": uom,
            "unit_price_cents": unit_price if unit_price is not None else default_price,
            "extended_cents": 0,
            "pallet_break": False,
            "cold_chain_required": cold_chain,
            "trimmed_lbs": D(0),
            "status": "OPEN",
        }
    )
    db.lines[line["id"]] = line
    refresh_line_derived(line)
    rollup_order(order)
    touch(order)
    return object_response(line_out(line), 201)


@bp.delete("/sales-orders/<order_id>/lines/<line_id>")
def remove_line(order_id, line_id):
    actor = require(("Brewer", "AllocationManager"))
    order = must_exist("orders", order_id)
    line = db.lines.get(line_id)
    if line is None or line["sales_order_id"] != order["id"]:
        raise ApiError("ERR_ORDER_LINE_NOT_FOUND", "No such line on this order")
    scope_brewer(actor, order["brewer_id"])
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_ORDER_STATE", "Lines may only be removed from a DRAFT order"
        )
    line["status"] = "REMOVED"
    touch(line)
    rollup_order(order)
    touch(order)
    return object_response(order_out(order))


@bp.get("/order-lines/<line_id>")
def get_line(line_id):
    actor = require(ALL_ROLES)
    line = must_exist("lines", line_id)
    order = db.orders[line["sales_order_id"]]
    scope_brewer(actor, order["brewer_id"])
    return object_response(line_out(line))


@bp.get("/order-lines")
def list_lines():
    actor = require(ALL_ROLES)
    limit, offset = pagination()
    args = request.args
    order_id = args.get("sales_order_id")
    contract_id = args.get("hop_contract_id")
    lot_id = args.get("malt_lot_id")
    job_id = args.get("yeast_propagation_job_id")
    variety_id = args.get("hop_variety_id")
    item_type = args.get("item_type")
    allocation_source = args.get("allocation_source")
    status = args.get("status")
    filter_exists("orders", order_id)
    filter_exists("contracts", contract_id)
    filter_exists("malt_lots", lot_id)
    filter_exists("jobs", job_id)
    filter_exists("varieties", variety_id)
    if order_id:
        scope_brewer(actor, db.orders[order_id]["brewer_id"])

    items = []
    for line in db.lines.values():
        if order_id and line["sales_order_id"] != order_id:
            continue
        if contract_id and line["hop_contract_id"] != contract_id:
            continue
        if lot_id and line["malt_lot_id"] != lot_id:
            continue
        if job_id and line["yeast_propagation_job_id"] != job_id:
            continue
        if variety_id and line["hop_variety_id"] != variety_id:
            continue
        if item_type and line["item_type"] != item_type:
            continue
        if allocation_source and line["allocation_source"] != allocation_source:
            continue
        if status and line["status"] != status:
            continue
        if actor.is_brewer:
            owner = db.orders.get(line["sales_order_id"])
            if owner is None or owner["brewer_id"] != actor.user_id:
                continue
        items.append(line)
    items = by_created(items)
    page = paginate(items, limit, offset)
    return array_response([line_out(l) for l in page], len(items), limit, offset)


# ---------------------------------------------------------------------------
# Fulfilment
# ---------------------------------------------------------------------------

def _live_lines(order):
    return [l for l in lines_of(order["id"]) if l["status"] in ROLLUP_LINE_STATUSES]


@bp.post("/sales-orders/<order_id>/confirm")
def confirm_order(order_id):
    actor = require(("Brewer",))
    body()
    order = must_exist("orders", order_id)
    scope_brewer(actor, order["brewer_id"])
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Only a DRAFT order may be confirmed")

    brewer = db.brewers[order["brewer_id"]]
    recompute_brewer(brewer, bump=False)
    lines = _live_lines(order)

    # priority 21: cold-chain certification
    if order["requires_cold_chain"] and not brewer["cold_chain_certified"]:
        raise ApiError(
            "ERR_COLD_CHAIN_NOT_CERTIFIED",
            "The brewery is not certified to receive cold-chain goods",
        )

    # priority 27: the requested ship date must sit inside every contract window
    ship_date = order["requested_ship_date"]
    for line in lines:
        if line["item_type"] != "HOP" or line["allocation_source"] != "CONTRACT":
            continue
        contract = db.contracts[line["hop_contract_id"]]
        if not (
            contract["delivery_window_start"]
            <= ship_date
            <= contract["delivery_window_end"]
        ):
            raise ApiError(
                "ERR_SHIP_DATE_OUTSIDE_DELIVERY_WINDOW",
                "requested_ship_date falls outside the contract's delivery window",
            )

    # priority 33: at least one live line
    if not lines:
        raise ApiError("ERR_ORDER_HAS_NO_LINES", "The order carries no live lines")

    # priorities 41-43: the three aggregate volume gates
    contract_draw = {}
    lot_draw = {}
    spot_draw = {}
    for line in lines:
        quantity = D(line["quantity"])
        if line["item_type"] == "HOP" and line["allocation_source"] == "CONTRACT":
            key = line["hop_contract_id"]
            contract_draw[key] = contract_draw.get(key, D(0)) + quantity
        elif line["item_type"] == "HOP":
            key = line["hop_variety_id"]
            spot_draw[key] = spot_draw.get(key, D(0)) + quantity
        elif line["item_type"] == "MALT":
            key = line["malt_lot_id"]
            lot_draw[key] = lot_draw.get(key, D(0)) + quantity

    for contract_id, drawn in contract_draw.items():
        if contract_remaining(db.contracts[contract_id]) < drawn:
            raise ApiError(
                "ERR_CONTRACT_VOLUME_EXHAUSTED",
                "The contract does not hold enough undrawn poundage",
            )
    for lot_id, drawn in lot_draw.items():
        if malt_lot_available(db.malt_lots[lot_id]) < drawn:
            raise ApiError(
                "ERR_MALT_LOT_INSUFFICIENT_QUANTITY",
                "The malt lot does not hold enough available poundage",
            )
    for variety_id, drawn in spot_draw.items():
        if D(db.varieties[variety_id]["available_spot_lbs"]) < drawn:
            raise ApiError(
                "ERR_SPOT_INVENTORY_INSUFFICIENT",
                "The variety does not hold enough spot inventory",
            )

    # priority 44: the brewery must not be on credit hold
    if brewer["credit_status"] == "HOLD":
        raise ApiError(
            "ERR_BREWER_CREDIT_HOLD", "The brewery is on credit hold"
        )

    # priority 45: the credit limit, judged on the freshly priced total
    rollup_order(order)
    provisional = assess_order_fees(order, "PROVISIONAL", persist=False)
    exposure = int(brewer["credit_exposure_cents"]) + int(provisional["total_cents"])
    if exposure > int(brewer["credit_limit_cents"]):
        raise ApiError(
            "ERR_CREDIT_LIMIT_EXCEEDED",
            "This order would push the brewery past its credit limit",
        )

    # commit poundage in three places
    for contract_id, drawn in contract_draw.items():
        contract = db.contracts[contract_id]
        contract["committed_lbs"] = D(contract["committed_lbs"]) + drawn
        touch(contract)
    for variety_id, drawn in spot_draw.items():
        variety = db.varieties[variety_id]
        variety["available_spot_lbs"] = D(variety["available_spot_lbs"]) - drawn
        touch(variety)

    order["fulfillment_status"] = "CONFIRMED"
    rollup_order(order)
    assess_order_fees(order, "PROVISIONAL")
    touch(order)
    recompute_brewer(brewer, bump=False)
    touch(brewer)
    return object_response(order_out(order))


@bp.post("/sales-orders/<order_id>/credit-decision")
def credit_decision(order_id):
    require(("CreditManager",))
    payload = body()
    decision = f_enum(payload, "decision", ("APPROVE", "HOLD"), required=True)
    f_str(payload, "decision_note", required=False, max_len=1000)

    order = must_exist("orders", order_id)
    if order["fulfillment_status"] in ("CANCELLED", "DELIVERED"):
        raise ApiError(
            "ERR_INVALID_ORDER_STATE",
            "A credit decision cannot be recorded on a cancelled or delivered order",
        )
    brewer = db.brewers[order["brewer_id"]]
    if decision == "APPROVE":
        if brewer["credit_status"] == "HOLD":
            raise ApiError(
                "ERR_BREWER_CREDIT_HOLD",
                "A brewery on credit hold cannot have its orders approved",
            )
        order["credit_status"] = "APPROVED"
    else:
        order["credit_status"] = "ON_HOLD"
    touch(order)
    if decision == "HOLD":
        hold_staged_shipments(order)
    return object_response(order_out(order))


@bp.post("/sales-orders/<order_id>/pick")
def pick_order(order_id):
    require(("WarehouseOperator",))
    body()
    order = must_exist("orders", order_id)
    if order["fulfillment_status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Only a CONFIRMED order may be picked")

    lines = _live_lines(order)
    for line in lines:
        if line["item_type"] != "MALT":
            continue
        if db.malt_lots[line["malt_lot_id"]]["status"] != "RELEASED":
            raise ApiError(
                "ERR_MALT_LOT_NOT_RELEASED", "A malt line references an unreleased lot"
            )
    for line in lines:
        if line["item_type"] != "YEAST":
            continue
        if db.jobs[line["yeast_propagation_job_id"]]["status"] != "READY":
            raise ApiError(
                "ERR_YEAST_NOT_READY", "A yeast line references a job that is not READY"
            )
    if order["credit_status"] != "APPROVED":
        raise ApiError(
            "ERR_ORDER_CREDIT_NOT_APPROVED", "The order's credit decision is not APPROVED"
        )

    order["fulfillment_status"] = "PICKED"
    touch(order)
    return object_response(order_out(order))


@bp.post("/sales-orders/<order_id>/ship")
def ship_order(order_id):
    require(("WarehouseOperator",))
    body()
    order = must_exist("orders", order_id)
    if order["fulfillment_status"] != "PICKED":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Only a PICKED order may be shipped")

    shipments = shipments_of_order(order["id"])
    for shipment in shipments:
        if shipment["status"] == "EXCURSION_FLAGGED":
            raise ApiError(
                "ERR_COLD_CHAIN_EXCURSION", "A flagged reefer load blocks the shipment"
            )
    if order["requires_cold_chain"]:
        if not any(s["status"] == "IN_TRANSIT" for s in shipments):
            raise ApiError(
                "ERR_INVALID_SHIPMENT_STATE",
                "A cold-chain order needs a reefer load in IN_TRANSIT to ship",
            )

    order["fulfillment_status"] = "SHIPPED"
    set_dt(order, "invoiced_at", now())
    touch(order)
    for line in _live_lines(order):
        if line["item_type"] != "YEAST":
            continue
        job = db.jobs.get(line["yeast_propagation_job_id"])
        if job is not None and job["status"] == "READY":
            job["status"] = "SHIPPED"
            touch(job)
    brewer = db.brewers[order["brewer_id"]]
    post_receivable(brewer, int(order["total_cents"]))
    return object_response(order_out(order))


@bp.post("/sales-orders/<order_id>/deliver")
def deliver_order(order_id):
    require(("WarehouseOperator",))
    body()
    order = must_exist("orders", order_id)
    if order["fulfillment_status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Only a SHIPPED order may be delivered")

    shipments = shipments_of_order(order["id"])
    for shipment in shipments:
        if shipment["status"] == "EXCURSION_FLAGGED":
            raise ApiError(
                "ERR_COLD_CHAIN_EXCURSION", "A flagged reefer load blocks the delivery"
            )

    order["fulfillment_status"] = "DELIVERED"
    set_dt(order, "delivered_at", now())
    for shipment in shipments:
        if shipment["status"] == "IN_TRANSIT":
            shipment["status"] = "DELIVERED"
            touch(shipment)
    assess_order_fees(order, "FINAL")
    touch(order)
    brewer = db.brewers[order["brewer_id"]]
    post_receivable(brewer, int(order["final_freight_adjustment_cents"]))
    return object_response(order_out(order))


@bp.post("/sales-orders/<order_id>/cancel")
def cancel_order(order_id):
    actor = require(("Brewer", "AllocationManager"))
    payload = body()
    cancel_reason = f_str(payload, "cancel_reason", min_len=1, max_len=1000)

    order = must_exist("orders", order_id)
    scope_brewer(actor, order["brewer_id"])
    if order["fulfillment_status"] not in CANCELLABLE:
        raise ApiError(
            "ERR_INVALID_ORDER_STATE",
            "Only a DRAFT, CONFIRMED, PICKED or SHIPPED order may be cancelled",
        )

    if order["fulfillment_status"] != "DRAFT":
        release_commitments(order)
    for line in lines_of(order["id"]):
        if line["status"] in ROLLUP_LINE_STATUSES:
            line["status"] = "REMOVED"
            touch(line)
    supersede_shipments(order)

    memo = 0
    if order.get("invoiced_at") is not None:
        memo = int(order["total_cents"]) + int(order["final_freight_adjustment_cents"])
    order["fulfillment_status"] = "CANCELLED"
    order["cancel_reason"] = cancel_reason
    touch(order)
    brewer = db.brewers[order["brewer_id"]]
    post_receivable(brewer, -memo)
    return object_response(order_out(order))
