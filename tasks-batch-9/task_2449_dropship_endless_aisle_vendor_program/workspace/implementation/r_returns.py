"""Return authorizations: open, authorize, receive, reject."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import serialize
import validate as v
from auth import authenticate
from db import db, new_row, touch
from errors import api_error
from response import created, listing, ok, paginate, pagination

bp = Blueprint("returns", __name__)

REASON_CODES = ("DEFECTIVE", "NOT_AS_DESCRIBED", "BUYER_REMORSE", "LATE_DELIVERY")
RETURN_STATUSES = ("REQUESTED", "AUTHORIZED", "RECEIVED", "REJECTED")
REJECTION_REASONS = ("OUTSIDE_DEFECT_WINDOW", "NOT_RECEIVED", "POLICY")


def get_return(return_id):
    """Validation rank 7."""
    row = db.returns.get(return_id)
    if row is None:
        api_error("ERR_RETURN_NOT_FOUND", "return %s does not exist" % return_id)
    return row


def _inside_defect_window(line):
    """Validation rank 35."""
    item = calc.item_of(line)
    if line["shipped_at"] is None or item is None:
        return False
    last_day = line["shipped_at"].date() + timedelta(days=item["defect_window_days"])
    return calc.clock_date() <= last_day


@bp.post("/dropship/returns")
def create_return():
    authenticate(("CareAgent", "PlatformAdmin"))
    body = v.payload()

    # rank 6
    if not v.has_value(body, "line_id") or not isinstance(body["line_id"], str):
        api_error("ERR_INVALID_REQUEST", "line_id is required")
    line = db.lines.get(body["line_id"])
    if line is None:
        api_error("ERR_LINE_NOT_FOUND", "order line %s does not exist" % body["line_id"])

    # rank 12
    reason_code = v.req_enum(body, "reason_code", REASON_CODES)
    quantity = v.req_int(body, "quantity_returned", 1, None)

    # rank 22
    if line["status"] != "SHIPPED":
        api_error("ERR_LINE_INVALID_STATE", "a return requires a SHIPPED line")

    # rank 35
    if not _inside_defect_window(line):
        api_error("ERR_OUTSIDE_DEFECT_WINDOW", "the defect window for this line has closed")

    # rank 36
    if quantity + calc.line_returned_units(line) > line["quantity"]:
        api_error("ERR_RETURN_QUANTITY_EXCEEDS_SHIPPED",
                  "quantity_returned exceeds the units shipped on this line")

    row = new_row()
    row.update({
        "line_id": line["id"],
        "routed_vendor_id": None,
        "reason_code": reason_code,
        "quantity_returned": quantity,
        "status": "REQUESTED",
        "routing_destination": None,
        "reverse_freight_owner": None,
        "restock_disposition": None,
        "refund_base_cents": None,
        "restocking_fee_cents": None,
        "customer_freight_charge_cents": None,
        "refund_cents": None,
        "vendor_chargeback_cents": None,
        "restocked_units": 0,
        "rejection_reason": None,
    })
    db.returns[row["id"]] = row
    return created(serialize.ret(row))


@bp.get("/dropship/returns/<return_id>")
def read_return(return_id):
    authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager",
                  "VendorUser", "CareAgent"))
    row = get_return(return_id)
    return ok(serialize.ret(row))


@bp.get("/dropship/returns")
def list_returns():
    authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager",
                  "VendorUser", "CareAgent"))

    line_id = v.filter_str(request.args, "line_id")
    routed_vendor_id = v.filter_str(request.args, "routed_vendor_id")
    status = v.filter_enum(request.args, "status", RETURN_STATUSES)
    reason_code = v.filter_enum(request.args, "reason_code", REASON_CODES)
    limit, offset = pagination(request.args)

    rows = list(db.returns.values())
    if line_id is not None:
        rows = [r for r in rows if r["line_id"] == line_id]
    if routed_vendor_id is not None:
        rows = [r for r in rows if r["routed_vendor_id"] == routed_vendor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if reason_code is not None:
        rows = [r for r in rows if r["reason_code"] == reason_code]

    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return listing([serialize.ret(r) for r in page], limit, offset, total)


@bp.post("/dropship/returns/<return_id>/authorize")
def authorize_return(return_id):
    authenticate(("CareAgent", "MerchandiseManager", "PlatformAdmin"))
    ra = get_return(return_id)
    line = db.lines.get(ra["line_id"])

    # rank 22
    if line is None or line["status"] != "SHIPPED":
        api_error("ERR_LINE_INVALID_STATE", "the referenced line is not SHIPPED")

    # rank 23
    if ra["status"] != "REQUESTED":
        api_error("ERR_RETURN_INVALID_STATE",
                  "authorize is not allowed from %s" % ra["status"])

    # rank 35
    if not _inside_defect_window(line):
        api_error("ERR_OUTSIDE_DEFECT_WINDOW", "the defect window for this line has closed")

    calc.return_routing(ra, line)
    calc.return_financials(ra, line)
    ra["status"] = "AUTHORIZED"
    touch(ra)

    if ra["routing_destination"] == "VENDOR" and ra["vendor_chargeback_cents"]:
        routed = db.vendors.get(ra["routed_vendor_id"])
        if routed is not None:
            calc.post_chargeback(routed, ra["vendor_chargeback_cents"])

    order = db.orders[line["order_id"]]
    touch(order)
    return ok(serialize.ret(ra))


@bp.post("/dropship/returns/<return_id>/receive")
def receive_return(return_id):
    caller = authenticate(("VendorUser", "PlatformAdmin", "CareAgent"))
    ra = get_return(return_id)

    body = v.payload()
    v.opt_int(body, "restocked_units", None, 0, None)

    # rank 23
    if ra["status"] != "AUTHORIZED":
        api_error("ERR_RETURN_INVALID_STATE",
                  "receive is not allowed from %s" % ra["status"])

    if caller.is_vendor_user and caller.user_id != ra["routed_vendor_id"]:
        api_error("ERR_VENDOR_SCOPE_VIOLATION",
                  "the receiving vendor must be the routed vendor")

    ra["status"] = "RECEIVED"
    if ra["restock_disposition"] == "DESTROY":
        ra["restocked_units"] = 0
    else:
        ra["restocked_units"] = ra["quantity_returned"]
    touch(ra)
    return ok(serialize.ret(ra))


@bp.post("/dropship/returns/<return_id>/reject")
def reject_return(return_id):
    authenticate(("MerchandiseManager", "PlatformAdmin"))
    ra = get_return(return_id)

    body = v.payload()
    reason = v.req_enum(body, "rejection_reason", REJECTION_REASONS)

    # rank 23
    if ra["status"] not in ("REQUESTED", "AUTHORIZED"):
        api_error("ERR_RETURN_INVALID_STATE",
                  "reject is not allowed from %s" % ra["status"])

    compensating = ra["status"] == "AUTHORIZED"
    ra["status"] = "REJECTED"
    ra["rejection_reason"] = reason
    touch(ra)

    if compensating:
        if ra["routing_destination"] == "VENDOR" and ra["vendor_chargeback_cents"]:
            routed = db.vendors.get(ra["routed_vendor_id"])
            if routed is not None:
                calc.reverse_chargeback(routed, ra["vendor_chargeback_cents"])
        line = db.lines.get(ra["line_id"])
        if line is not None:
            order = db.orders.get(line["order_id"])
            if order is not None:
                touch(order)

    return ok(serialize.ret(ra))
