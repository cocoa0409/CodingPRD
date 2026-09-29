"""Order-line vendor interactions: acknowledge, ship-confirm, cancel, retransmit."""

from flask import Blueprint, request

import calc
import serialize
import validate as v
from auth import authenticate, require_line_scope, require_vendor_scope
from db import db, new_row, now, touch
from errors import api_error
from response import created, listing, ok, paginate, pagination

bp = Blueprint("lines", __name__)

LINE_STATUSES = (
    "PENDING_TRANSMIT", "TRANSMITTED", "ACKNOWLEDGED",
    "BACKORDERED", "SHIPPED", "CANCELLED_BY_VENDOR",
)
CARRIERS = ("UPS", "FEDEX", "USPS", "LTL_CARRIER")
ACK_DISPOSITIONS = ("ACCEPTED", "BACKORDERED", "REJECTED")


def get_line(line_id):
    """Validation rank 6."""
    row = db.lines.get(line_id)
    if row is None:
        api_error("ERR_LINE_NOT_FOUND", "order line %s does not exist" % line_id)
    return row


@bp.get("/dropship/order-lines/<line_id>")
def read_line(line_id):
    caller = authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager",
                           "VendorUser", "CareAgent"))
    line = get_line(line_id)
    require_line_scope(caller, line)
    return ok(serialize.line(line))


@bp.get("/dropship/order-lines")
def list_lines():
    authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager",
                  "VendorUser", "CareAgent"))

    order_id = v.filter_str(request.args, "order_id")
    item_id = v.filter_str(request.args, "item_id")
    status = v.filter_enum(request.args, "status", LINE_STATUSES)
    limit, offset = pagination(request.args)

    rows = list(db.lines.values())
    if order_id is not None:
        rows = [l for l in rows if l["order_id"] == order_id]
    if item_id is not None:
        rows = [l for l in rows if l["item_id"] == item_id]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]

    rows = sorted(rows, key=lambda l: (l["created_at"], l["_seq"]))
    page, total = paginate(rows, limit, offset)
    return listing([serialize.line(l) for l in page], limit, offset, total)


@bp.post("/dropship/order-lines/<line_id>/acknowledge")
def acknowledge_line(line_id):
    caller = authenticate(("VendorUser", "PlatformAdmin"))
    line = get_line(line_id)
    require_line_scope(caller, line)

    body = v.payload()
    disposition = v.req_enum(body, "ack_disposition", ACK_DISPOSITIONS)

    # rank 22
    if line["status"] != "TRANSMITTED":
        api_error("ERR_LINE_INVALID_STATE",
                  "acknowledge is not allowed from %s" % line["status"])

    # rank 26
    vendor = calc.vendor_of_line(line)
    if vendor is None or vendor["onboarding_status"] != "ACTIVE":
        api_error("ERR_VENDOR_NOT_ACTIVE", "the offer's vendor is not ACTIVE")

    line["acknowledged_at"] = now()
    if disposition == "REJECTED":
        calc.cancel_line_cascade(line)
    else:
        line["status"] = "ACKNOWLEDGED" if disposition == "ACCEPTED" else "BACKORDERED"
        touch(line)
    return ok(serialize.line(line))


@bp.post("/dropship/order-lines/<line_id>/ship-confirm")
def ship_confirm_line(line_id):
    caller = authenticate(("VendorUser", "PlatformAdmin"))
    line = get_line(line_id)
    require_line_scope(caller, line)

    body = v.payload()
    carrier = v.req_enum(body, "carrier", CARRIERS)
    tracking = v.req_str(body, "tracking_number", 4, 40)
    shipped_units = v.req_int(body, "shipped_units", 1, None)
    package_count = v.opt_int(body, "package_count", 1, 1, None)
    if shipped_units != line["quantity"]:
        api_error("ERR_INVALID_REQUEST",
                  "shipped_units must equal the line quantity (%d)" % line["quantity"])

    # rank 22
    if line["status"] != "ACKNOWLEDGED":
        api_error("ERR_LINE_INVALID_STATE",
                  "ship-confirm is not allowed from %s" % line["status"])

    item = calc.item_of(line)
    vendor = calc.vendor_of(item)
    # rank 26
    if vendor is None or vendor["onboarding_status"] != "ACTIVE":
        api_error("ERR_VENDOR_NOT_ACTIVE", "the offer's vendor is not ACTIVE")

    order = db.orders[line["order_id"]]
    clock = now()

    confirmation = new_row(versioned=False)
    confirmation.update({
        "line_id": line["id"],
        "carrier": carrier,
        "tracking_number": tracking,
        "ship_date": clock.date(),
        "shipped_units": shipped_units,
        "package_count": package_count,
        "ship_hours": calc.ship_hours(line),
        "on_time": line["ship_deadline_at"] is not None and clock <= line["ship_deadline_at"],
    })
    db.shipments[confirmation["id"]] = confirmation

    line["status"] = "SHIPPED"
    line["shipped_at"] = clock
    touch(line)

    item["reserved_units"] = item["reserved_units"] - line["quantity"]
    item["lifetime_shipped_units"] = item["lifetime_shipped_units"] + line["quantity"]
    touch(item)

    calc.credit_settlement(
        vendor, line["unit_cost_cents"] * line["quantity"] + line["surcharge_cents"]
    )

    calc.refresh_order_promises(order)
    touch(order)

    return created(serialize.shipment(confirmation))


@bp.get("/dropship/order-lines/<line_id>/shipment-confirmations")
def list_shipment_confirmations(line_id):
    authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager",
                  "VendorUser", "CareAgent"))
    get_line(line_id)
    limit, offset = pagination(request.args)

    rows = [s for s in db.shipments.values() if s["line_id"] == line_id]
    rows = sorted(rows, key=lambda s: (s["created_at"], s["_seq"]))
    page, total = paginate(rows, limit, offset)
    return listing([serialize.shipment(s) for s in page], limit, offset, total)


@bp.post("/dropship/order-lines/<line_id>/cancel")
def cancel_line(line_id):
    caller = authenticate(("VendorUser", "PlatformAdmin"))
    line = get_line(line_id)
    require_line_scope(caller, line)

    # rank 22
    if line["status"] not in ("TRANSMITTED", "ACKNOWLEDGED", "BACKORDERED"):
        api_error("ERR_LINE_INVALID_STATE",
                  "cancel is not allowed from %s" % line["status"])

    calc.cancel_line_cascade(line)
    return ok(serialize.line(line))


@bp.post("/dropship/order-lines/<line_id>/retransmit")
def retransmit_line(line_id):
    authenticate(("PlatformAdmin", "MerchandiseManager"))
    line = get_line(line_id)

    # rank 22
    if line["status"] != "BACKORDERED":
        api_error("ERR_LINE_INVALID_STATE",
                  "retransmit is not allowed from %s" % line["status"])

    old_item = calc.item_of(line)
    old_vendor = calc.vendor_of(old_item)
    # rank 26
    if old_vendor is None or old_vendor["onboarding_status"] != "ACTIVE":
        api_error("ERR_VENDOR_NOT_ACTIVE", "the sourcing offer's vendor is not ACTIVE")

    # rank 32
    if calc.blackout_covering(old_vendor["id"], calc.clock_date()) is not None:
        api_error("ERR_VENDOR_BLACKOUT", "the sourcing offer's vendor is blacked out today")

    order = db.orders[line["order_id"]]
    target, rule = calc.retransmit_target(line, order)
    # rank 39
    if target is None:
        api_error("ERR_NO_ELIGIBLE_FALLBACK_VENDOR",
                  "no eligible endless-aisle fallback offer is available")

    old_item["reserved_units"] = old_item["reserved_units"] - line["quantity"]
    old_item["lifetime_released_units"] = old_item["lifetime_released_units"] + line["quantity"]
    touch(old_item, bump=False)

    line["item_id"] = target["id"]
    target["reserved_units"] = target["reserved_units"] + line["quantity"]
    target["lifetime_reserved_units"] = target["lifetime_reserved_units"] + line["quantity"]
    touch(target, bump=False)

    line["acknowledged_at"] = None
    calc.transmit_line(line, target, calc.vendor_of(target), order, rule)

    calc.refresh_order_promises(order)
    touch(order)
    return ok(serialize.line(line))
