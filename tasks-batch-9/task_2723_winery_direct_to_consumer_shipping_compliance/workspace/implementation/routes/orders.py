"""Orders, their lines, the screening endpoint and the exception workflow."""
from flask import Blueprint

import clock
import response
import validate
from errors import ApiError
from middleware import require, own_both, own_winery, own_consumer
from routes import common
from services import derive, orders_svc, screening, serialize
from store import db, base_row, touch

bp = Blueprint("orders", __name__)

BOTTLE_MLS = (375, 500, 750, 1000, 1500, 3000)
COMPLIANCE_STATUSES = ("DRAFT", "CLEARED", "REJECTED", "OVERRIDE_PENDING", "SUSPENDED_PERMIT")
FULFILLMENT_STATUSES = ("UNFULFILLED", "LABELED", "IN_TRANSIT", "DELIVERED", "RETURNED")
EXCEPTION_STATUSES = ("OPEN", "APPROVED", "DENIED")
DECISIONS = ("APPROVED", "DENIED")
MAX_LINES = 20


def _read_lines(b):
    raw = b.get("lines")
    if not isinstance(raw, list):
        validate.bad("Field 'lines' must be an array.")
    if len(raw) < 1 or len(raw) > MAX_LINES:
        validate.bad("Field 'lines' must hold between 1 and %d elements." % MAX_LINES)
    out = []
    for element in raw:
        if not isinstance(element, dict):
            validate.bad("Every element of 'lines' must be an object.")
        out.append({
            "sku": validate.field_str(element, "sku"),
            "bottle_ml": validate.field_int(element, "bottle_ml"),
            "bottles": validate.field_int(element, "bottles", minimum=1),
            "unit_price_cents": validate.field_int(element, "unit_price_cents", minimum=1),
        })
        if out[-1]["bottle_ml"] not in BOTTLE_MLS:
            validate.bad("A line's 'bottle_ml' must be one of %s."
                         % ", ".join(str(v) for v in BOTTLE_MLS))
    return out


@bp.route("/dtc/orders", methods=["POST"])
def create_order():
    uid, role = require("Consumer", "WineryOperator", "ComplianceOfficer")
    peek = validate.raw_body()
    own_winery(uid, role, peek.get("winery_id"))
    own_consumer(uid, role, peek.get("consumer_id"))
    b = validate.body()
    winery_id = validate.field_str(b, "winery_id")
    consumer_id = validate.field_str(b, "consumer_id")
    sub_id = validate.field_str(b, "club_subscription_id", required=False)
    address = validate.field_str(b, "ship_to_address_line")
    code = validate.state_code(b, "ship_to_state_code")
    zip_value = validate.zip_code(b, "ship_to_zip")
    line_inputs = _read_lines(b)
    expected = validate.field_int(b, "expected_consumer_version")

    winery = common.winery(winery_id)
    consumer = common.consumer(consumer_id)
    if sub_id is not None:
        common.club_subscription(sub_id)
    rule = common.rule_for_state(code)

    if expected != consumer["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_consumer_version %s does not match the consumer's current "
                       "version %s." % (expected, consumer["version"]))

    if winery["status"] == "SUSPENDED":
        raise ApiError("ERR_WINERY_SUSPENDED",
                       "The winery is suspended; no order may be created.")

    order = orders_svc.create_order(winery, consumer, rule, sub_id, address, code,
                                    zip_value, line_inputs)
    return response.obj(serialize.order(order), 201)


@bp.route("/dtc/orders/<oid>", methods=["GET"])
def read_order(oid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "Consumer")
    order = common.order(oid)
    own_both(uid, role, order["winery_id"], order["consumer_id"])
    return response.obj(serialize.order(order))


@bp.route("/dtc/orders", methods=["GET"])
def list_orders():
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "Consumer")
    winery_id = common.scope_winery(common.arg("winery_id"), uid, role)
    consumer_id = common.scope_consumer(common.arg("consumer_id"), uid, role)
    sub_id = common.arg("club_subscription_id")
    compliance = validate.query_enum("compliance_status", COMPLIANCE_STATUSES)
    fulfillment = validate.query_enum("fulfillment_status", FULFILLMENT_STATUSES)
    rows = [o for o in db.orders.values()
            if (winery_id is None or o["winery_id"] == winery_id)
            and (consumer_id is None or o["consumer_id"] == consumer_id)
            and (sub_id is None or o["club_subscription_id"] == sub_id)
            and (compliance is None or o["compliance_status"] == compliance)
            and (fulfillment is None or o["fulfillment_status"] == fulfillment)]
    return common.listing(rows, serialize.order)


@bp.route("/dtc/orders/<oid>/lines", methods=["GET"])
def list_order_lines(oid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator", "Consumer")
    order = common.order(oid)
    own_both(uid, role, order["winery_id"], order["consumer_id"])
    limit, offset = validate.pagination()
    rows = orders_svc.lines_of(order["id"])
    window = validate.page(rows, limit, offset)
    return response.arr([serialize.order_line(r) for r in window], limit, offset, len(rows))


@bp.route("/dtc/orders/<oid>/screen", methods=["POST"])
def screen_order(oid):
    uid, role = require("ComplianceOfficer", "WineryOperator")
    order = common.order(oid)
    own_winery(uid, role, order["winery_id"])
    if order["compliance_status"] not in ("DRAFT", "SUSPENDED_PERMIT"):
        raise ApiError("ERR_ORDER_ALREADY_SCREENED",
                       "Only a DRAFT or SUSPENDED_PERMIT order may be screened.")
    orders_svc.screen(order)
    return response.obj(serialize.order(order))


# ---- compliance exceptions ------------------------------------------------
@bp.route("/dtc/orders/<oid>/compliance-exceptions", methods=["POST"])
def raise_exception(oid):
    uid, _role = require("ComplianceOfficer")
    order = common.order(oid)
    b = validate.body()
    raised = validate.field_enum(b, "raised_rule", screening.OVERRIDABLE)
    justification = validate.field_str(b, "justification")
    if order["compliance_status"] != "OVERRIDE_PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "An exception may only be raised on an OVERRIDE_PENDING order.")
    if raised != order["rejection_error_id"]:
        validate.bad("raised_rule must equal the order's recorded rejection_error_id.")
    row = base_row()
    row.update({
        "order_id": order["id"],
        "raised_rule": raised,
        "justification": justification,
        "status": "OPEN",
        "requested_by_user_id": uid,
        "decided_by_user_id": None,
        "decision_note": None,
        "decided_at": None,
    })
    db.compliance_exceptions[row["id"]] = row
    winery = db.wineries.get(order["winery_id"])
    if winery is not None:
        derive.bump_winery(winery)
    return response.obj(serialize.compliance_exception(row), 201)


@bp.route("/dtc/orders/<oid>/compliance-exceptions", methods=["GET"])
def list_order_exceptions(oid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator")
    order = common.order(oid)
    own_winery(uid, role, order["winery_id"])
    status = validate.query_enum("status", EXCEPTION_STATUSES)
    rows = [e for e in db.compliance_exceptions.values()
            if e["order_id"] == order["id"]
            and (status is None or e["status"] == status)]
    return common.listing(rows, serialize.compliance_exception)


@bp.route("/dtc/compliance-exceptions/<xid>", methods=["GET"])
def read_exception(xid):
    uid, role = require("PlatformAdmin", "ComplianceOfficer", "WineryOperator")
    exception = common.compliance_exception(xid)
    order = db.orders.get(exception["order_id"])
    if order is not None:
        own_winery(uid, role, order["winery_id"])
    return response.obj(serialize.compliance_exception(exception))


@bp.route("/dtc/compliance-exceptions/<xid>/decision", methods=["POST"])
def decide_exception(xid):
    uid, _role = require("ComplianceOfficer")
    exception = common.compliance_exception(xid)
    b = validate.body()
    decision = validate.field_enum(b, "decision", DECISIONS)
    note = validate.field_str(b, "decision_note", required=False, allow_empty=True)

    if exception["status"] != "OPEN":
        raise ApiError("ERR_EXCEPTION_ALREADY_DECIDED",
                       "The exception is already %s." % exception["status"])
    order = db.orders.get(exception["order_id"])
    if order is None or order["compliance_status"] != "OVERRIDE_PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The referenced order is not in OVERRIDE_PENDING.")
    if uid == exception["requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "The deciding officer may not be the officer who raised the exception.")

    exception["status"] = decision
    exception["decided_by_user_id"] = uid
    exception["decision_note"] = note
    exception["decided_at"] = clock.now_iso()
    touch(exception)

    winery = db.wineries.get(order["winery_id"])
    if decision == "APPROVED":
        order["override_applied"] = True
        orders_svc.apply_clearance(order, first_clear=True)
        touch(order)
    else:
        order["compliance_status"] = "REJECTED"
        touch(order)
        consumer = db.consumers.get(order["consumer_id"])
        if consumer is not None:
            derive.bump_consumer(consumer)
        if winery is not None:
            derive.bump_winery(winery)
    return response.obj(serialize.compliance_exception(exception))
