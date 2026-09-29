"""Vessel sailings, freight bookings and bill-of-lading issuance."""
from datetime import timedelta
from decimal import Decimal

import calc
import ledgers
import valid
from authz import apply_page, authenticate, pagination
from core import ApiError, dq, fmt_dt, fmt_instant, ok, ok_list
from db import insert, ordered, require, serialize, serialize_all, store, touch
from routes_docs import build_document
from routes_orders import guard_embargo, guard_restricted

from flask import Blueprint, request

bp = Blueprint("freight", __name__)

D = Decimal
ZONES = ("ZONE_1", "ZONE_2", "ZONE_3")
CONTAINERS = ("LCL", "DRY_20", "DRY_40", "REEFER_40")
SAILING_READ = ("ExportOpsCoordinator", "FinanceCollectionsOfficer", "PlatformAdmin")
BOOKING_READ = ("ExportOpsCoordinator", "FinanceCollectionsOfficer",
                "TradeComplianceOfficer", "PlatformAdmin")


def booking_state_invalid(message="the booking state does not permit this"):
    raise ApiError("ERR_BOOKING_STATE_INVALID", 409, message)


def sailing_not_open(message="the sailing is not bookable"):
    raise ApiError("ERR_SAILING_NOT_OPEN", 409, message)


def issued_document(order_id, doc_type):
    for document in ordered(store.documents):
        if document["export_order_id"] == order_id \
                and document["doc_type"] == doc_type \
                and document["status"] == "ISSUED":
            return document
    return None


def accepted_lc(order_id):
    for lc in ordered(store.lcs):
        if lc["export_order_id"] == order_id and lc["status"] == "ACCEPTED":
            return lc
    return None


@bp.post("/vessel-sailings")
def publish_sailing():
    authenticate(("ExportOpsCoordinator", "PlatformAdmin"))
    body = valid.body()
    scac = valid.string(body, "carrier_scac", pattern=r"^[A-Z]{4}$", min_len=4, max_len=4)
    vessel_name = valid.string(body, "vessel_name", max_len=200)
    voyage_no = valid.string(body, "voyage_no", max_len=50)
    loading = valid.string(body, "port_of_loading", max_len=20)
    discharge = valid.string(body, "port_of_discharge", max_len=20)
    zone = valid.enum(body, "destination_zone", ZONES)
    cutoff_raw, cutoff_dt = valid.instant(body, "cutoff_at")
    etd_raw, etd_dt = valid.instant(body, "etd")
    eta_raw, eta_dt = valid.instant(body, "eta")
    capacity = valid.decimal(body, "capacity_weight_kg", 3, minimum=0, exclusive_min=True)
    tariff = valid.decimal(body, "tariff_rate_per_1000kg_usd", 2, minimum=0,
                           exclusive_min=True)

    if etd_dt <= cutoff_dt:
        valid.inconsistent("etd must be strictly after cutoff_at")
    if eta_dt <= etd_dt:
        valid.inconsistent("eta must be strictly after etd")
    for other in store.sailings.values():
        if other["carrier_scac"] == scac and other["voyage_no"] == voyage_no:
            raise ApiError("ERR_DUPLICATE_VOYAGE", 409,
                           "voyage_no already exists for this carrier")

    row = insert(store.sailings, {
        "carrier_scac": scac,
        "vessel_name": vessel_name,
        "voyage_no": voyage_no,
        "port_of_loading": loading,
        "port_of_discharge": discharge,
        "destination_zone": zone,
        "cutoff_at": cutoff_raw,
        "etd": etd_raw,
        "eta": eta_raw,
        "capacity_weight_kg": dq(capacity, 3),
        "booked_weight_kg": D("0.000"),
        "tariff_rate_per_1000kg_usd": dq(tariff, 2),
        "status": "OPEN",
        "_cutoff_dt": cutoff_dt,
        "_etd_dt": etd_dt,
        "_eta_dt": eta_dt,
    })
    return ok(serialize(row), 201)


@bp.get("/vessel-sailings/<vessel_sailing_id>")
def read_sailing(vessel_sailing_id):
    authenticate(SAILING_READ)
    row = require(store.sailings, vessel_sailing_id, "ERR_SAILING_NOT_FOUND")
    return ok(serialize(row))


@bp.post("/freight-bookings")
def create_booking():
    authenticate(("ExportOpsCoordinator",))
    body = valid.body()
    order = valid.fk(body, "export_order_id", store.orders, "ERR_ORDER_NOT_FOUND")
    sailing = valid.fk(body, "vessel_sailing_id", store.sailings, "ERR_SAILING_NOT_FOUND")
    weight = valid.decimal(body, "booked_weight_kg", 3, minimum=0, exclusive_min=True)
    container = valid.enum(body, "container_type", CONTAINERS)
    expected = valid.integer(body, "expected_vessel_sailing_version", minimum=0)

    screening = ledgers.screening_for_order(order["id"])
    if screening is not None and screening["status"] == "CLEARED":
        ledgers.require_fulfillment(order, ("COMPLIANCE_CLEARED",))
    if screening is None or screening["status"] != "CLEARED":
        raise ApiError("ERR_ORDER_NOT_COMPLIANCE_CLEARED", 409,
                       "the order's screening is not CLEARED")
    if sailing["status"] != "OPEN":
        sailing_not_open()
    if sailing["destination_zone"] != order["destination_zone"]:
        valid.bad("the sailing does not serve the order's destination_zone")
    if expected != sailing["version"]:
        raise ApiError("ERR_STALE_SAILING_VERSION", 412,
                       "expected_vessel_sailing_version is stale")
    buyer = store.buyers[order["buyer_id"]]
    guard_restricted(buyer)
    guard_embargo(buyer)

    license_row = None
    if screening["license_determination"] == "LICENSE_REQUIRED":
        if not screening.get("export_license_id"):
            raise ApiError("ERR_EXPORT_LICENSE_REQUIRED", 409,
                           "the screening carries no export license")
        license_row = store.licenses.get(screening["export_license_id"])
        if license_row is not None \
                and not (license_row["_from_dt"] <= store.clock <= license_row["_to_dt"]):
            raise ApiError("ERR_LICENSE_NOT_VALID_AT_DATE", 409,
                           "the license window does not cover the clock")
    if store.clock >= sailing["_cutoff_dt"]:
        raise ApiError("ERR_SAILING_CUTOFF_PASSED", 409,
                       "the sailing's documentation cut-off has passed")

    window_start = sailing["_cutoff_dt"]
    window_end = sailing["_etd_dt"] + timedelta(hours=calc.DOC_BUFFER_HOURS)
    for other in ordered(store.bookings):
        if other["export_order_id"] != order["id"]:
            continue
        if other["status"] not in calc.LIVE_BOOKING_STATES:
            continue
        if window_start < other["_window_end"] and other["_window_start"] < window_end:
            raise ApiError("ERR_BOOKING_WINDOW_OVERLAP", 409,
                           "the order already holds a booking over this window")
    if dq(sailing["booked_weight_kg"] + weight, 3) > sailing["capacity_weight_kg"]:
        raise ApiError("ERR_SAILING_CAPACITY_EXCEEDED", 409,
                       "the sailing has no capacity headroom left")
    required = dq(order["ordered_goods_value_usd"], 2)
    if license_row is not None:
        if dq(license_row["consumed_value_usd"] + required, 2) \
                > license_row["licensed_value_usd"]:
            raise ApiError("ERR_LICENSE_VALUE_EXHAUSTED", 409,
                           "the license has insufficient remaining value")

    minimum = calc.CONTAINER_MIN_KG[container]
    row = insert(store.bookings, {
        "export_order_id": order["id"],
        "vessel_sailing_id": sailing["id"],
        "booked_weight_kg": dq(weight, 3),
        "container_type": container,
        "effective_window_start": fmt_instant(window_start),
        "effective_window_end": fmt_instant(window_end),
        "chargeable_weight_kg": dq(weight if weight > minimum else minimum, 3),
        "status": "BOOKED",
        "cancel_reason": None,
        "_window_start": window_start,
        "_window_end": window_end,
    })
    ledgers.recompute_sailing(sailing)
    order["fulfillment_status"] = "BOOKED"
    _b, seller, buyer_side = calc.cost_allocation(order, "provisional")
    order["provisional_seller_cost_usd"] = seller
    order["provisional_buyer_cost_usd"] = buyer_side
    if license_row is not None:
        order["licensed_value_allocated_usd"] = required
    touch(order)
    if license_row is not None:
        ledgers.recompute_license(license_row)
    return ok(serialize(row), 201)


@bp.get("/freight-bookings")
def list_bookings():
    authenticate(BOOKING_READ)
    limit, offset = pagination()
    rows = ordered(store.bookings)
    for field in ("export_order_id", "vessel_sailing_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    page, total = apply_page(rows, limit, offset)
    return ok_list(serialize_all(page), limit, offset, total)


@bp.get("/freight-bookings/<booking_id>")
def read_booking(booking_id):
    authenticate(BOOKING_READ)
    row = require(store.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    return ok(serialize(row))


@bp.post("/freight-bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    authenticate(("ExportOpsCoordinator",))
    booking = require(store.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    order = store.orders[booking["export_order_id"]]
    sailing = store.sailings[booking["vessel_sailing_id"]]

    if booking["status"] != "BOOKED":
        booking_state_invalid("only a BOOKED booking may be confirmed")
    ledgers.require_fulfillment(order, ("BOOKED",))
    if sailing["status"] not in ("OPEN", "FULL"):
        sailing_not_open("the sailing has passed its cut-off or departed")
    for doc_type in ("COMMERCIAL_INVOICE", "PACKING_LIST"):
        if issued_document(order["id"], doc_type) is None:
            raise ApiError("ERR_REQUIRED_DOCUMENT_MISSING", 409,
                           "the order has no ISSUED %s" % doc_type)

    booking["status"] = "CONFIRMED"
    touch(booking)
    return ok(serialize(booking))


@bp.post("/freight-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    authenticate(("ExportOpsCoordinator",))
    booking = require(store.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    body = valid.body()
    reason = valid.string(body, "cancel_reason", max_len=1000)
    order = store.orders[booking["export_order_id"]]
    sailing = store.sailings[booking["vessel_sailing_id"]]

    if booking["status"] not in ("BOOKED", "CONFIRMED"):
        booking_state_invalid("only a BOOKED or CONFIRMED booking may be cancelled")
    if sailing["status"] == "DEPARTED":
        sailing_not_open("the sailing has departed")
    if booking["status"] == "CONFIRMED" \
            and issued_document(order["id"], "BILL_OF_LADING") is not None:
        booking_state_invalid("the order already carries an ISSUED bill of lading")

    booking["status"] = "CANCELLED"
    booking["cancel_reason"] = reason
    touch(booking)
    ledgers.recompute_sailing(sailing)
    license_row = ledgers.license_for_order(order)
    if order["fulfillment_status"] == "BOOKED":
        order["fulfillment_status"] = "COMPLIANCE_CLEARED"
    order["licensed_value_allocated_usd"] = D("0.00")
    touch(order)
    if license_row is not None:
        ledgers.recompute_license(license_row)
    return ok(serialize(booking))


def _shipped_map(order, entries):
    """Resolves a shipped_lines collection into {line_id: Decimal}."""
    lines = calc.order_lines(order["id"])
    by_id = dict((line["id"], line) for line in lines)
    by_no = dict((line["line_no"], line) for line in lines)
    resolved = {}
    for entry in entries:
        if not isinstance(entry, dict):
            valid.bad("shipped_lines entries must be objects")
        line = None
        for key in ("shipment_line_id", "line_id", "id"):
            if entry.get(key):
                line = by_id.get(entry[key])
                break
        if line is None and isinstance(entry.get("line_no"), int):
            line = by_no.get(entry["line_no"])
        if line is None:
            valid.bad("shipped_lines references an unknown shipment line")
        quantity = None
        for key in ("shipped_quantity", "quantity"):
            if key in entry and entry[key] is not None:
                quantity = valid.decimal(entry, key, 3, minimum=0)
                break
        if quantity is None:
            valid.bad("shipped_lines entries must carry shipped_quantity")
        if quantity <= 0 or quantity > line["quantity"]:
            raise ApiError("ERR_ZERO_SHIPPED_QUANTITY", 422,
                           "shipped_quantity must be above zero and at most the "
                           "ordered quantity")
        resolved[line["id"]] = quantity
    return lines, resolved


@bp.post("/freight-bookings/<booking_id>/bill-of-lading")
def issue_bill_of_lading(booking_id):
    caller = authenticate(("ExportOpsCoordinator",))
    booking = require(store.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    body = valid.body()
    on_board_raw, on_board_dt = valid.instant(body, "on_board_date")
    entries = body.get("shipped_lines")
    if entries is None:
        valid.bad("shipped_lines is required")
    if not isinstance(entries, list):
        valid.bad("shipped_lines must be an array")
    order = store.orders[booking["export_order_id"]]

    # PRD §2.11: entity state errors (priority 11) precede cross-entity state
    # preconditions (priority 12), so a booking that has not been confirmed answers on
    # its own state table before ERR_BOOKING_NOT_CONFIRMED can be reached.
    if booking["status"] not in ("CONFIRMED", "SHIPPED"):
        booking_state_invalid("only a CONFIRMED booking may issue a bill of lading")
    ledgers.require_fulfillment(order, ("BOOKED",))
    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_BOOKING_NOT_CONFIRMED", 409,
                       "the booking is not CONFIRMED")
    lc = accepted_lc(order["id"])
    if lc is not None and on_board_dt > lc["_latest_shipment_dt"]:
        raise ApiError("ERR_LATEST_SHIPMENT_DATE_PASSED", 409,
                       "on_board_date is after the credit's latest_shipment_date")
    if on_board_dt > order["_ship_by_dt"]:
        raise ApiError("ERR_LATEST_SHIPMENT_DATE_PASSED", 409,
                       "on_board_date is after the order's ship_by_date")
    if not entries:
        raise ApiError("ERR_ZERO_SHIPPED_QUANTITY", 422, "shipped_lines is empty")
    lines, resolved = _shipped_map(order, entries)

    full = True
    for line in lines:
        quantity = resolved.get(line["id"], D("0.000"))
        line["shipped_quantity"] = dq(quantity, 3)
        if line["shipped_quantity"] != line["quantity"]:
            full = False
    order["shipped_goods_value_usd"] = calc.shipped_goods_value(order["id"])
    booking["status"] = "SHIPPED"
    touch(booking)

    order["fulfillment_status"] = "SHIPPED" if full else "SHORT_SHIPPED"
    if full:
        order["short_shipped_value_usd"] = D("0.00")
    else:
        order["short_shipped_value_usd"] = dq(
            order["ordered_goods_value_usd"] - order["shipped_goods_value_usd"], 2)
    _b, seller, buyer_side = calc.cost_allocation(order, "final")
    order["final_seller_cost_usd"] = seller
    order["final_buyer_cost_usd"] = buyer_side
    order["cost_allocation_variance_usd"] = dq(
        seller - order["provisional_seller_cost_usd"], 2)
    touch(order)

    document = build_document(order, "BILL_OF_LADING", caller.user_id, revision=1,
                              status="ISSUED", on_board_date=on_board_raw)
    license_row = ledgers.license_for_order(order)
    if license_row is not None:
        ledgers.recompute_license(license_row)
    return ok(serialize(document), 201)
