"""Logical clock (PRD section 2.4) and the net exposure report (PRD 3.9)."""

from datetime import date, timedelta

from flask import Blueprint, request

from store import TABLES, clock_now, clock_set, clock_iso
from helpers import (
    auth, success, err, get_body, req_str, parse_iso_datetime, parse_iso_date,
    sorted_by_created, touch, find, dec, q2, round_half_up_int, num_out,
    lot_age_days, recompute_all_warehouses, recompute_lot_value,
    latest_published_line_for,
)

bp = Blueprint("misc", __name__)

ADMIN = ["DeskAdmin"]
EXPOSURE_ROLES = ["DeskAdmin", "Trader", "RiskOfficer"]


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(ADMIN)
    body = get_body()
    raw = req_str(body, "to_iso8601")
    target = parse_iso_datetime(raw, "to_iso8601")
    clock_set(target)
    today = target.date()

    expired_lot_ids = []
    # Sweep 1: AVAILABLE lots aged strictly beyond shelf life -> EXPIRED.
    for lot in sorted_by_created(TABLES["inventory_lots"].values()):
        if lot["status"] != "AVAILABLE":
            continue
        product = find("products", lot["product_id"])
        if product is None:
            continue
        if lot_age_days(lot) > product["shelf_life_days"]:
            lot["status"] = "EXPIRED"
            touch(lot)
            expired_lot_ids.append(lot["id"])
    if expired_lot_ids:
        recompute_all_warehouses()

    # Sweep 2: OPEN contracts whose delivery week has fully elapsed with
    # delivered < committed -> DEFAULTED.
    defaulted_contract_ids = []
    for c in sorted_by_created(TABLES["forward_contracts"].values()):
        if c["status"] != "OPEN":
            continue
        week_end = date.fromisoformat(c["delivery_week_start"]) + timedelta(days=7)
        if today >= week_end and dec(c["delivered_lbs"]) < dec(c["committed_lbs"]):
            c["status"] = "DEFAULTED"
            touch(c)
            defaulted_contract_ids.append(c["id"])

    # Clock advance is also a valuation trigger: graded lots re-price with
    # their new age band.
    for lot in TABLES["inventory_lots"].values():
        if lot.get("unit_value_cents_per_lb") is not None:
            old = lot["unit_value_cents_per_lb"]
            recompute_lot_value(lot)
            if lot["unit_value_cents_per_lb"] != old:
                touch(lot)

    return success({
        "current_utc": clock_iso(),
        "expired_lot_ids": expired_lot_ids,
        "defaulted_contract_ids": defaulted_contract_ids,
    })


@bp.route("/api/exposure", methods=["GET"])
def exposure():
    auth(EXPOSURE_ROLES)
    product_id = request.args.get("product_id")
    week_start = request.args.get("week_start")
    if not product_id or not isinstance(product_id, str):
        err("ERR_INVALID_REQUEST", 400, "product_id query parameter is required")
    if not week_start or not isinstance(week_start, str):
        err("ERR_INVALID_REQUEST", 400, "week_start query parameter is required")
    parse_iso_date(week_start, "week_start")
    product = TABLES["products"].get(product_id)
    if product is None:
        err("ERR_PRODUCT_NOT_FOUND", 404, f"Product {product_id} not found")

    physical = dec(0)
    for lot in TABLES["inventory_lots"].values():
        if lot["product_id"] == product_id and lot["status"] == "AVAILABLE":
            physical += dec(lot["current_weight_lbs"])

    inbound = dec(0)
    for po in TABLES["purchase_orders"].values():
        if po["product_id"] == product_id and po["status"] == "BOOKED":
            inbound += dec(po["ordered_weight_lbs"])

    forward = dec(0)
    for c in TABLES["forward_contracts"].values():
        if c["product_id"] == product_id and c["status"] == "OPEN" \
                and c["delivery_week_start"] == week_start:
            forward += dec(c["committed_lbs"]) - dec(c["delivered_lbs"])

    spot = dec(0)
    for a in TABLES["allocations"].values():
        if a["status"] != "CONFIRMED":
            continue
        line = find("price_sheet_lines", a["price_sheet_line_id"])
        if line is None or line["product_id"] != product_id:
            continue
        sheet = find("price_sheets", line["price_sheet_id"])
        if sheet is None or sheet["week_start_date"] != week_start:
            continue
        spot += dec(a["allocated_lbs"])

    net = physical + inbound - forward - spot
    line = latest_published_line_for(product_id)
    basis = line["price_per_lb_cents"] if line is not None else 0
    value = round_half_up_int(net * basis)
    return success({
        "product_id": product_id,
        "week_start": week_start,
        "physical_lbs": num_out(q2(physical)),
        "inbound_lbs": num_out(q2(inbound)),
        "forward_lbs": num_out(q2(forward)),
        "spot_lbs": num_out(q2(spot)),
        "exposure_lbs": num_out(q2(net)),
        "exposure_value_cents": value,
    })
