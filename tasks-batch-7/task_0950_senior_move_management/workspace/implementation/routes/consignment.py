"""Consignment lots: markdowns, sale arithmetic and the non-monotone settlement."""

from flask import Blueprint

import calc
import constants as K
import derive
import gates
import services
import store
from errors import ApiError
from routes.helpers import one, listing, filtered
from util import D, parse_dt, parse_date

bp = Blueprint("consignment", __name__)

LOT_READ = ["MOVE_MANAGER", "VENDOR", "BILLING_ADMIN", "CLIENT", "POWER_OF_ATTORNEY"]
LOT_TERMINAL = ["HAULED"]


@bp.route("/consignment-lots", methods=["POST"])
def create_lot():
    req = gates.preflight(["MOVE_MANAGER"],
                          required=[("engagement_id", "string"), ("vendor_id", "string"),
                                    ("list_price_cents", "int"), ("listed_on", "date"),
                                    ("item_ids", "list")])
    fks = gates.resolve_body_fks(req.body)
    engagement = fks["engagement_id"]
    vendor = fks["vendor_id"]
    items = fks.get("item_ids", [])
    gates.gate3(engagement)
    for item in items:
        gates.gate7_not_held(item)
    if vendor["vendor_type"] != K.SERVICE_KIND_TO_VENDOR_TYPE["CONSIGNMENT_PICKUP"]:
        raise ApiError("ERR_VENDOR_TYPE_MISMATCH")

    record = store.base_record()
    record.update({
        "engagement_id": engagement["id"],
        "vendor_id": vendor["id"],
        "status": "LISTED",
        "list_price_cents": req.body["list_price_cents"],
        "current_price_cents": calc.consignment_current_price(req.body["list_price_cents"], 0),
        "markdown_round": 0,
        "listed_on": req.body["listed_on"],
        "sold_on": None,
        "gross_sale_price_cents": None,
        "commission_cents": 0,
        "fees_cents": 0,
        "net_proceeds_cents": 0,
        "credited": False,
        "reversed": False,
        "disposal_fee_cents": 0,
    })
    store.insert("consignment_lots", record)
    for item in items:
        item["consignment_lot_id"] = record["id"]
        store.touch(item)
    return one("consignment_lots", record, 201)


@bp.route("/consignment-lots", methods=["GET"])
def list_lots():
    req = gates.preflight(LOT_READ, is_list=True)
    rows = filtered(store.all_of("consignment_lots"), req.args,
                    ["engagement_id", "vendor_id", "status"])
    return listing("consignment_lots", req, rows)


@bp.route("/consignment-lots/<lid>", methods=["GET"])
def read_lot(lid):
    req = gates.preflight(LOT_READ)
    record = gates.path_record("consignment_lots", lid)
    gates.gate4_ownership(req, engagement=store.get("engagements", record["engagement_id"]),
                          vendor_id=record["vendor_id"])
    return one("consignment_lots", record)


def _lot_context(lid):
    record = gates.path_record("consignment_lots", lid)
    engagement = store.get("engagements", record["engagement_id"])
    return record, engagement


@bp.route("/consignment-lots/<lid>/mark-down", methods=["POST"])
def mark_down_lot(lid):
    req = gates.preflight(["MOVE_MANAGER", "VENDOR"])
    record, engagement = _lot_context(lid)
    gates.gate3(engagement)
    gates.gate4_ownership(req, vendor_id=record["vendor_id"])
    gates.gate10_state(record["status"], ["LISTED", "MARKED_DOWN"], LOT_TERMINAL)
    if record["markdown_round"] >= K.MAX_MARKDOWN_ROUNDS:
        raise ApiError("ERR_MARKDOWN_ROUNDS_EXHAUSTED")

    record["markdown_round"] = record["markdown_round"] + 1
    record["current_price_cents"] = calc.consignment_current_price(
        record["list_price_cents"], record["markdown_round"])
    record["status"] = "MARKED_DOWN"
    store.touch(record)
    return one("consignment_lots", record)


@bp.route("/consignment-lots/<lid>/record-sale", methods=["POST"])
def record_sale(lid):
    req = gates.preflight(["VENDOR", "MOVE_MANAGER"],
                          required=[("gross_sale_price_cents", "int"), ("sold_on", "date")])
    record, engagement = _lot_context(lid)
    gates.gate3(engagement)
    gates.gate4_ownership(req, vendor_id=record["vendor_id"])
    gates.gate10_state(record["status"], ["LISTED", "MARKED_DOWN"], LOT_TERMINAL)

    members = derive.lot_items(record["id"])
    if req.body["gross_sale_price_cents"] <= 0 or not members or \
            parse_date(req.body["sold_on"]) < parse_date(record["listed_on"]):
        raise ApiError("ERR_INVALID_SALE_PRICE")

    gross = req.body["gross_sale_price_cents"]
    commission = calc.consignment_commission(gross)
    fees = calc.consignment_fees(len(members))
    record["status"] = "SOLD"
    record["gross_sale_price_cents"] = gross
    record["sold_on"] = req.body["sold_on"]
    record["commission_cents"] = commission
    record["fees_cents"] = fees
    record["net_proceeds_cents"] = calc.consignment_net_proceeds(gross, commission, fees)
    store.touch(record)
    return one("consignment_lots", record)


@bp.route("/consignment-lots/<lid>/settle", methods=["POST"])
def settle_lot(lid):
    req = gates.preflight(["MOVE_MANAGER", "BILLING_ADMIN"])
    record, engagement = _lot_context(lid)
    gates.gate3(engagement)
    gates.gate9_not_finalized(engagement, "ERR_BILLING_CLOSED")
    gates.gate10_state(record["status"], ["SOLD"], LOT_TERMINAL)
    if record["credited"]:
        raise ApiError("ERR_LOT_ALREADY_CREDITED")

    invoice = derive.invoice_of(engagement["id"])
    services.append_line(invoice, "CONSIGNMENT_CREDIT", -record["net_proceeds_cents"],
                         "Consignment credit", "SYSTEM",
                         source_consignment_lot_id=record["id"])
    record["status"] = "SETTLED"
    record["credited"] = True
    store.touch(record)
    return one("consignment_lots", record)


@bp.route("/consignment-lots/<lid>/declare-unsold", methods=["POST"])
def declare_unsold(lid):
    req = gates.preflight(["MOVE_MANAGER", "VENDOR"])
    record, engagement = _lot_context(lid)
    gates.gate3(engagement)
    gates.gate4_ownership(req, vendor_id=record["vendor_id"])
    gates.gate10_state(record["status"], ["LISTED", "MARKED_DOWN"], LOT_TERMINAL)
    elapsed = (parse_dt(store.now_iso()).date() - parse_date(record["listed_on"])).days
    if elapsed < K.CONSIGN_UNSOLD_WINDOW_DAYS:
        raise ApiError("ERR_UNSOLD_WINDOW_NOT_ELAPSED")
    record["status"] = "UNSOLD"
    store.touch(record)
    return one("consignment_lots", record)


@bp.route("/consignment-lots/<lid>/return-to-client", methods=["POST"])
def return_lot(lid):
    req = gates.preflight(["MOVE_MANAGER"], required=[("reason", "nes")])
    record, engagement = _lot_context(lid)
    gates.gate3(engagement)
    if record["status"] in ("SOLD", "SETTLED"):
        gates.gate9_not_finalized(engagement, "ERR_BILLING_CLOSED")
    gates.gate10_state(record["status"], ["SOLD", "SETTLED", "UNSOLD"], LOT_TERMINAL)

    from_status = record["status"]
    record["status"] = "RETURNED"
    if record["credited"] and not record["reversed"]:
        invoice = derive.invoice_of(engagement["id"])
        posted = None
        for line in derive.lines_of(invoice["id"]):
            if line["line_type"] == "CONSIGNMENT_CREDIT" and \
                    line["source_consignment_lot_id"] == record["id"]:
                posted = line
        # the reversal mirrors the amount actually credited, never a recomputation
        services.append_line(invoice, "CONSIGNMENT_REVERSAL", -posted["amount_cents"],
                             "Consignment reversal", "SYSTEM",
                             source_consignment_lot_id=record["id"])
        record["reversed"] = True
        if derive.billing_hold(engagement):
            services.cascade_reopen_milestone(engagement["id"], "CLOSE_OUT")
    if from_status == "UNSOLD":
        # only the unsold leg clears membership; the settled/sold legs do not
        for item in derive.lot_items(record["id"]):
            item["consignment_lot_id"] = None
            store.touch(item)
    store.touch(record)
    return one("consignment_lots", record)


@bp.route("/consignment-lots/<lid>/haul-away", methods=["POST"])
def haul_away_lot(lid):
    gates.preflight(["MOVE_MANAGER"])
    record, engagement = _lot_context(lid)
    gates.gate3(engagement)
    gates.gate9_not_finalized(engagement, "ERR_BILLING_CLOSED")
    gates.gate10_state(record["status"], ["UNSOLD", "RETURNED"], LOT_TERMINAL)

    members = derive.lot_items(record["id"])
    volume = sum((D(i["volume_cft"]) for i in members), D(0))
    fee = calc.disposal_fee(volume)
    record["disposal_fee_cents"] = fee
    record["status"] = "HAULED"
    invoice = derive.invoice_of(engagement["id"])
    services.append_line(invoice, "DISPOSAL_FEE", fee, "Disposal fee", "SYSTEM")
    for item in members:
        item["disposition"] = "HAUL_AWAY"
        item["handling_state"] = "REMOVED"
        store.touch(item)
    store.touch(record)
    return one("consignment_lots", record)
