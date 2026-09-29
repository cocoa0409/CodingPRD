"""Export orders, shipment lines, compliance submission, cancel and write-off."""
from decimal import Decimal

import calc
import ledgers
import valid
from authz import apply_page, authenticate, pagination
from core import ApiError, dq, ok, ok_list
from db import insert, ordered, require, serialize, serialize_all, store, touch

from flask import Blueprint, request

bp = Blueprint("orders", __name__)

D = Decimal
INCOTERMS = ("EXW", "FCA", "FOB", "CFR", "CIF", "DAP", "DDP")
ZONES = ("ZONE_1", "ZONE_2", "ZONE_3")
UOMS = ("EA", "KG", "LTR", "MTR", "SET")
ORDER_READ = ("ExportOpsCoordinator", "TradeComplianceOfficer",
              "DocumentaryCreditReviewer", "FinanceCollectionsOfficer", "PlatformAdmin")
ORDER_LIST = ORDER_READ + ("ForeignBuyer",)
LINE_READ = ("ExportOpsCoordinator", "DocumentaryCreditReviewer",
             "TradeComplianceOfficer", "PlatformAdmin")

MONEY_FIELDS = ("ordered_goods_value_usd", "shipped_goods_value_usd",
                "provisional_seller_cost_usd", "provisional_buyer_cost_usd",
                "final_seller_cost_usd", "final_buyer_cost_usd",
                "cost_allocation_variance_usd", "outstanding_receivable_usd",
                "licensed_value_allocated_usd", "insured_exposure_usd",
                "short_shipped_value_usd")


def guard_restricted(buyer):
    if buyer["restricted_party_flag"]:
        raise ApiError("ERR_RESTRICTED_PARTY_BLOCKED", 409,
                       "the buyer is flagged as a restricted party")


def guard_embargo(buyer):
    if buyer["sanctions_tier"] == "EMBARGOED":
        raise ApiError("ERR_PROHIBITED_DESTINATION", 409,
                       "the buyer's sanctions tier is EMBARGOED")


@bp.post("/export-orders")
def create_order():
    caller = authenticate(("ExportOpsCoordinator",))
    body = valid.body()
    buyer = valid.fk(body, "buyer_id", store.buyers, "ERR_BUYER_NOT_FOUND")
    incoterm = valid.enum(body, "incoterm", INCOTERMS)
    named_place = valid.string(body, "incoterm_named_place", max_len=200)
    origin = valid.string(body, "origin_country_code", pattern=r"^[A-Z]{2}$",
                          min_len=2, max_len=2)
    destination = valid.string(body, "destination_country_code", pattern=r"^[A-Z]{2}$",
                              min_len=2, max_len=2)
    zone = valid.enum(body, "destination_zone", ZONES)
    currency = valid.string(body, "invoice_currency", required=False,
                            pattern=r"^[A-Z]{3}$", min_len=3, max_len=3, default="USD")
    fx = valid.decimal(body, "fx_rate_usd_to_invoice", 6, required=False,
                       minimum=0, exclusive_min=True, default=D("1.000000"))
    if currency == "USD" and fx != D("1.000000"):
        valid.bad("fx_rate_usd_to_invoice must be exactly 1.000000 for USD invoices")
    ship_by_raw, ship_by = valid.instant(body, "ship_by_date")

    row = {
        "buyer_id": buyer["id"],
        "prepared_by_user_id": caller.user_id,
        "incoterm": incoterm,
        "incoterm_named_place": named_place,
        "origin_country_code": origin,
        "destination_country_code": destination,
        "destination_zone": zone,
        "invoice_currency": currency,
        "fx_rate_usd_to_invoice": dq(fx, 6),
        "ship_by_date": ship_by_raw,
        "fulfillment_status": "DRAFT",
        "settlement_status": "UNSECURED",
    }
    for field in MONEY_FIELDS:
        row[field] = D("0.00")
    row["_ship_by_dt"] = ship_by
    row["_charged_policy_id"] = None
    insert(store.orders, row)
    ledgers.recompute_open_order_count(buyer)
    return ok(serialize(row), 201)


@bp.get("/export-orders")
def list_orders():
    caller = authenticate(ORDER_LIST)
    limit, offset = pagination()
    rows = ordered(store.orders)
    if caller.is_buyer:
        rows = [r for r in rows if r["buyer_id"] == caller.user_id]
    buyer_id = request.args.get("buyer_id")
    if buyer_id:
        rows = [r for r in rows if r["buyer_id"] == buyer_id]
    fulfillment = request.args.get("fulfillment_status")
    if fulfillment:
        rows = [r for r in rows if r["fulfillment_status"] == fulfillment]
    settlement = request.args.get("settlement_status")
    if settlement:
        rows = [r for r in rows if r["settlement_status"] == settlement]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/export-orders/<export_order_id>")
def read_order(export_order_id):
    authenticate(ORDER_READ)
    row = require(store.orders, export_order_id, "ERR_ORDER_NOT_FOUND")
    return ok(serialize(row))


@bp.get("/export-orders/<export_order_id>/cost-allocation")
def read_cost_allocation(export_order_id):
    authenticate(("ExportOpsCoordinator", "FinanceCollectionsOfficer", "PlatformAdmin"))
    order = require(store.orders, export_order_id, "ERR_ORDER_NOT_FOUND")
    _b, provisional_seller, provisional_buyer = calc.cost_allocation(order, "provisional")
    _b2, final_seller, final_buyer = calc.cost_allocation(order, "final")
    view = serialize(order)
    view["provisional_seller_cost_usd"] = float(provisional_seller)
    view["provisional_buyer_cost_usd"] = float(provisional_buyer)
    view["final_seller_cost_usd"] = float(final_seller)
    view["final_buyer_cost_usd"] = float(final_buyer)
    view["cost_allocation_variance_usd"] = float(dq(final_seller - provisional_seller, 2))
    return ok(view)


@bp.post("/export-orders/<export_order_id>/shipment-lines")
def create_shipment_line(export_order_id):
    authenticate(("ExportOpsCoordinator",))
    order = require(store.orders, export_order_id, "ERR_ORDER_NOT_FOUND")
    body = valid.body()
    line_no = valid.integer(body, "line_no", minimum=1)
    description = valid.string(body, "goods_description", max_len=500)
    hs_code = valid.string(body, "hs_code", pattern=r"^(\d{6}|\d{10})$",
                           min_len=6, max_len=10)
    quantity = valid.decimal(body, "quantity", 3, minimum=0, exclusive_min=True)
    uom = valid.enum(body, "uom", UOMS)
    unit_price = valid.decimal(body, "unit_price_usd", 4, minimum=0, exclusive_min=True)
    discount = valid.decimal(body, "line_discount_pct", 2, required=False, minimum=0,
                             maximum=40, default=D("0.00"))
    net_weight = valid.decimal(body, "net_weight_kg", 3, minimum=0, exclusive_min=True)
    gross_weight = valid.decimal(body, "gross_weight_kg", 3, minimum=0,
                                 exclusive_min=True)
    package_count = valid.integer(body, "package_count", minimum=1)

    existing = calc.order_lines(order["id"])
    if len(existing) >= calc.MAX_LINES:
        valid.bad("an order may carry at most %d shipment lines" % calc.MAX_LINES)
    if gross_weight < net_weight:
        valid.inconsistent("gross_weight_kg must be at least net_weight_kg")
    ledgers.require_fulfillment(order, ("DRAFT",))
    if any(line["line_no"] == line_no for line in existing):
        raise ApiError("ERR_DUPLICATE_LINE_NO", 409,
                       "line_no %s already exists on the order" % line_no)

    extended = dq(quantity * unit_price, 2)
    line_discount = dq(extended * discount / D(100), 2)
    row = {
        "export_order_id": order["id"],
        "line_no": line_no,
        "goods_description": description,
        "hs_code": hs_code,
        "quantity": dq(quantity, 3),
        "uom": uom,
        "unit_price_usd": dq(unit_price, 4),
        "line_discount_pct": dq(discount, 2),
        "net_weight_kg": dq(net_weight, 3),
        "gross_weight_kg": dq(gross_weight, 3),
        "package_count": package_count,
        "shipped_quantity": D("0.000"),
        "line_extended_usd": extended,
        "line_net_usd": dq(extended - line_discount, 2),
        "apportioned_freight_usd": D("0.00"),
    }
    insert(store.shipment_lines, row)
    order["ordered_goods_value_usd"] = calc.ordered_goods_value(order["id"])
    touch(order)
    return ok(serialize(row), 201)


def _lines_sorted(rows):
    return sorted(rows, key=lambda r: (r["export_order_id"], r["line_no"]))


@bp.get("/export-orders/<export_order_id>/shipment-lines")
def list_order_lines(export_order_id):
    authenticate(LINE_READ)
    order = require(store.orders, export_order_id, "ERR_ORDER_NOT_FOUND")
    limit, offset = pagination()
    rows = sorted(calc.order_lines(order["id"]), key=lambda r: r["line_no"])
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/shipment-lines")
def list_lines():
    authenticate(LINE_READ)
    limit, offset = pagination()
    rows = list(store.shipment_lines.values())
    order_id = request.args.get("export_order_id")
    if order_id:
        rows = [r for r in rows if r["export_order_id"] == order_id]
    hs_code = request.args.get("hs_code")
    if hs_code:
        rows = [r for r in rows if r["hs_code"] == hs_code]
    rows = _lines_sorted(rows)
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/shipment-lines/<shipment_line_id>")
def read_line(shipment_line_id):
    authenticate(LINE_READ)
    row = require(store.shipment_lines, shipment_line_id, "ERR_ORDER_NOT_FOUND")
    return ok(serialize(row))


@bp.post("/export-orders/<export_order_id>/submit-for-compliance")
def submit_for_compliance(export_order_id):
    authenticate(("ExportOpsCoordinator",))
    order = require(store.orders, export_order_id, "ERR_ORDER_NOT_FOUND")
    buyer = store.buyers[order["buyer_id"]]
    ledgers.require_fulfillment(order, ("DRAFT",))
    guard_restricted(buyer)
    guard_embargo(buyer)
    lines = calc.order_lines(order["id"])
    if not lines:
        raise ApiError("ERR_NO_SHIPMENT_LINES", 422,
                       "the order carries no shipment lines")

    order["fulfillment_status"] = "COMPLIANCE_PENDING"
    order["ordered_goods_value_usd"] = calc.ordered_goods_value(order["id"])
    touch(order)
    insert(store.screenings, {
        "export_order_id": order["id"],
        "ruleset_version": 1,
        "decided_by_user_id": None,
        "eccn": None,
        "denied_party_hits": 0,
        "license_determination": None,
        "export_license_id": None,
        "status": "INITIATED",
        "cleared_at": None,
        "notes": None,
    })
    return ok(serialize(order))


@bp.post("/export-orders/<export_order_id>/cancel")
def cancel_order(export_order_id):
    authenticate(("ExportOpsCoordinator",))
    order = require(store.orders, export_order_id, "ERR_ORDER_NOT_FOUND")
    ledgers.require_fulfillment(order, ("DRAFT", "COMPLIANCE_PENDING", "COMPLIANCE_BLOCKED"))
    for document in store.documents.values():
        if document["export_order_id"] == order["id"] and document["status"] == "ISSUED":
            raise ApiError("ERR_ORDER_STATE_INVALID", 409,
                           "the order carries an ISSUED trade document")
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    buyer = store.buyers.get(order["buyer_id"])
    if buyer is not None:
        ledgers.recompute_open_order_count(buyer)
    return ok(serialize(order))


@bp.post("/export-orders/<export_order_id>/write-off")
def write_off(export_order_id):
    authenticate(("FinanceCollectionsOfficer",))
    order = require(store.orders, export_order_id, "ERR_ORDER_NOT_FOUND")
    body = valid.body()
    valid.string(body, "reason", max_len=1000)
    ledgers.require_settlement(order, ("DISHONORED", "CLAIM_FILED"))
    closed = any(d["export_order_id"] == order["id"]
                 and d["status"] == "CLOSED_NO_SETTLEMENT"
                 for d in store.disputes.values())
    if order["settlement_status"] == "CLAIM_FILED" and not closed:
        raise ApiError("ERR_ORDER_STATE_INVALID", 409,
                       "the linked dispute is not CLOSED_NO_SETTLEMENT")
    if order["settlement_status"] == "DISHONORED" \
            and order["insured_exposure_usd"] != 0 and not closed:
        raise ApiError("ERR_ORDER_STATE_INVALID", 409,
                       "insured exposure is still charged and no dispute is closed")

    order["settlement_status"] = "WRITTEN_OFF"
    ledgers.release_exposure(order)
    ledgers.auto_close(order)
    touch(order)
    return ok(serialize(order))
