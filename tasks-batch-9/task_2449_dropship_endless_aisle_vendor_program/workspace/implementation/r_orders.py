"""Order placement, reads and transmission."""

from flask import Blueprint

import calc
import serialize
import validate as v
from auth import authenticate
from db import db, iso_date, new_row, now, touch
from errors import api_error
from response import created, ok

bp = Blueprint("orders", __name__)


def get_order(order_id):
    """Validation rank 5."""
    row = db.orders.get(order_id)
    if row is None:
        api_error("ERR_ORDER_NOT_FOUND", "order %s does not exist" % order_id)
    return row


@bp.post("/dropship/orders")
def create_order():
    authenticate(("CareAgent", "PlatformAdmin", "MerchandiseManager"))
    body = v.payload()

    raw_lines = body.get("lines")

    # rank 4: every referenced offer exists
    if isinstance(raw_lines, list):
        for element in raw_lines:
            if isinstance(element, dict) and isinstance(element.get("item_id"), str):
                if element["item_id"] not in db.items:
                    api_error("ERR_ITEM_NOT_FOUND",
                              "offer %s does not exist" % element["item_id"])

    # rank 12
    order_ref = v.req_str(body, "order_ref", 1, 40)
    zone_code = v.req_str(body, "customer_zone_code", 1, 16, v.UPPER_CODE_RE)
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        api_error("ERR_INVALID_REQUEST", "lines must be a non-empty array")
    requested = []
    for index, element in enumerate(raw_lines):
        if not isinstance(element, dict):
            api_error("ERR_INVALID_REQUEST", "lines[%d] must be an object" % index)
        item_id = element.get("item_id")
        if not isinstance(item_id, str) or item_id == "":
            api_error("ERR_INVALID_REQUEST", "lines[%d].item_id is required" % index)
        quantity = element.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            api_error("ERR_INVALID_REQUEST", "lines[%d].quantity must be an integer" % index)
        if quantity < 1:
            api_error("ERR_INVALID_REQUEST", "lines[%d].quantity must be >= 1" % index)
        requested.append((db.items[item_id], quantity))

    # rank 16
    for existing in db.orders.values():
        if existing["order_ref"] == order_ref:
            api_error("ERR_DUPLICATE_ORDER_REF", "order_ref %s already exists" % order_ref)

    # rank 21
    for item, _quantity in requested:
        if item["status"] != "ACTIVE":
            api_error("ERR_ITEM_NOT_ORDERABLE", "offer %s is not ACTIVE" % item["id"])

    # rank 31
    for item, _quantity in requested:
        if calc.best_coverage_rule(item["vendor_id"], zone_code, item["ship_method"]) is None:
            api_error("ERR_ZONE_NOT_SERVICEABLE",
                      "no ACTIVE coverage row serves zone %s by %s" % (zone_code, item["ship_method"]))

    # rank 37
    for item, _quantity in requested:
        if calc.availability(item)["inventory_is_stale"]:
            api_error("ERR_INVENTORY_STALE", "the inventory feed for offer %s is stale" % item["id"])

    # rank 38
    for item, quantity in requested:
        if quantity > calc.availability(item)["available_units"]:
            api_error("ERR_INSUFFICIENT_AVAILABILITY",
                      "offer %s cannot supply %d units" % (item["id"], quantity))

    order = new_row()
    order.update({
        "order_ref": order_ref,
        "customer_zone_code": zone_code,
        "placed_at": now(),
        "quoted_promise_date": None,
        "recomputed_promise_date": None,
    })
    db.orders[order["id"]] = order

    for index, (item, quantity) in enumerate(requested):
        line = new_row()
        line.update({
            "order_id": order["id"],
            "item_id": item["id"],
            "line_number": index + 1,
            "quantity": quantity,
            "unit_retail_cents": item["unit_retail_cents"],
            "unit_cost_cents": 0,
            "surcharge_cents": 0,
            "status": "PENDING_TRANSMIT",
            "transmitted_at": None,
            "acknowledged_at": None,
            "shipped_at": None,
            "ack_deadline_at": None,
            "ship_deadline_at": None,
            "transmit_attempt_count": 0,
            "_quoted_promise_date": None,
            "_recomputed_promise_date": None,
        })
        db.lines[line["id"]] = line
        line["_quoted_promise_date"] = calc.promise_date(
            item, order, "QUOTED", order["placed_at"]
        )
        item["reserved_units"] = item["reserved_units"] + quantity
        item["lifetime_reserved_units"] = item["lifetime_reserved_units"] + quantity
        touch(item, bump=False)

    calc.refresh_order_promises(order)
    return created(serialize.order(order))


@bp.get("/dropship/orders/<order_id>")
def read_order(order_id):
    authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager", "CareAgent"))
    order = get_order(order_id)
    return ok(serialize.order(order))


@bp.get("/dropship/orders/<order_id>/promise")
def read_promise(order_id):
    authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager", "CareAgent"))
    order = get_order(order_id)
    return ok({
        "order_id": order["id"],
        "quoted_promise_date": iso_date(order["quoted_promise_date"]),
        "recomputed_promise_date": iso_date(order["recomputed_promise_date"]),
        "promise_variant_in_effect": calc.promise_variant_in_effect(order),
        "promise_divergence_days": calc.promise_divergence_days(order),
    })


@bp.post("/dropship/orders/<order_id>/transmit")
def transmit_order(order_id):
    authenticate(("PlatformAdmin", "MerchandiseManager"))
    order = get_order(order_id)

    pending = [l for l in calc.order_lines(order_id) if l["status"] == "PENDING_TRANSMIT"]
    # rank 22
    if not pending:
        api_error("ERR_LINE_INVALID_STATE", "the order has no PENDING_TRANSMIT line")

    # every guard is evaluated over every pending line before anything is written
    for line in pending:
        item = calc.item_of(line)
        if item is None or item["status"] != "ACTIVE":
            api_error("ERR_ITEM_INVALID_STATE", "offer %s is not ACTIVE" % line["item_id"])

    for line in pending:
        vendor = calc.vendor_of_line(line)
        if vendor is None or vendor["onboarding_status"] != "ACTIVE":
            api_error("ERR_VENDOR_NOT_ACTIVE", "the offer's vendor is not ACTIVE")

    rules = {}
    for line in pending:
        item = calc.item_of(line)
        rule = calc.best_coverage_rule(
            item["vendor_id"], order["customer_zone_code"], item["ship_method"]
        )
        if rule is None:
            api_error("ERR_ZONE_NOT_SERVICEABLE",
                      "no ACTIVE coverage row serves zone %s by %s"
                      % (order["customer_zone_code"], item["ship_method"]))
        rules[line["id"]] = rule

    today = calc.clock_date()
    for line in pending:
        item = calc.item_of(line)
        if calc.blackout_covering(item["vendor_id"], today) is not None:
            api_error("ERR_VENDOR_BLACKOUT", "the offer's vendor is blacked out today")

    for line in pending:
        item = calc.item_of(line)
        vendor = calc.vendor_of(item)
        calc.transmit_line(line, item, vendor, order, rules[line["id"]])

    calc.refresh_order_promises(order)
    touch(order)
    return ok(serialize.order(order))
