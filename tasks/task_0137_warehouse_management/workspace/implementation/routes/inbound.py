"""Inbound: ASN, AsnLine, ReceiptEvent, LicensePlate reads (PRD §3.2, §3.3, §3.5)."""
from flask import Blueprint, request

from common import (
    new_record, touch, serialize, get_json_body, require_str, require_int,
    optional_enum, paginate, lookup, lookup_fk,
)
from db import store
from errors import err
from middleware import get_identity, require_roles
from response import success, list_success
import calc

bp = Blueprint("inbound", __name__)


# ---------------------------------------------------------------------------
# InboundAsn
# ---------------------------------------------------------------------------
@bp.route("/warehouse/inbound-asns", methods=["POST"])
def create_asn():
    _, role = get_identity()
    require_roles(role, ["ReceivingClerk"])
    body = get_json_body()
    asn_number = require_str(body, "asn_number")
    supplier_name = require_str(body, "supplier_name", allow_empty=True)
    handling_mode = optional_enum(body, "handling_mode", {"PUTAWAY", "CROSS_DOCK"}, "PUTAWAY")
    if any(a["asn_number"] == asn_number for a in store.inbound_asns.values()):
        raise err("ERR_DUPLICATE_CODE", "asn_number already exists.")
    rec = new_record()
    rec.update({
        "asn_number": asn_number,
        "supplier_name": supplier_name,
        "handling_mode": handling_mode,
        "status": "ANNOUNCED",
        "received_by_user_id": None,
    })
    store.inbound_asns[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.route("/warehouse/inbound-asns/<asn_id>", methods=["GET"])
def get_asn(asn_id):
    get_identity()
    rec = lookup(store.inbound_asns, asn_id)
    return success(serialize(rec))


@bp.route("/warehouse/inbound-asns", methods=["GET"])
def list_asns():
    get_identity()
    items = list(store.inbound_asns.values())
    status = request.args.get("status")
    if status:
        items = [a for a in items if a["status"] == status]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


# ---------------------------------------------------------------------------
# AsnLine
# ---------------------------------------------------------------------------
@bp.route("/warehouse/inbound-asns/<asn_id>/lines", methods=["POST"])
def add_asn_line(asn_id):
    _, role = get_identity()
    require_roles(role, ["ReceivingClerk"])
    asn = lookup(store.inbound_asns, asn_id)
    body = get_json_body()
    sku_id = require_str(body, "sku_id")
    sku = lookup_fk(store.skus, sku_id, "sku_id")
    expected_qty = require_int(body, "expected_qty", exclusive_min=0)
    if asn["status"] != "ANNOUNCED":
        raise err("ERR_INVALID_STATE", "Lines may only be added while the ASN is ANNOUNCED.")
    rec = new_record()
    rec.update({
        "asn_id": asn_id,
        "sku_id": sku["id"],
        "expected_qty": expected_qty,
        "received_qty": 0,
        "line_status": "OPEN",
    })
    store.asn_lines[rec["id"]] = rec
    return success(serialize(rec), status=201)


@bp.route("/warehouse/inbound-asns/<asn_id>/lines", methods=["GET"])
def list_asn_lines_of_asn(asn_id):
    get_identity()
    lookup(store.inbound_asns, asn_id)
    items = [l for l in store.asn_lines.values() if l["asn_id"] == asn_id]
    for l in items:
        calc.refresh_asn_line(l)
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/asn-lines/<line_id>", methods=["GET"])
def get_asn_line(line_id):
    get_identity()
    rec = lookup(store.asn_lines, line_id)
    calc.refresh_asn_line(rec)
    return success(serialize(rec))


@bp.route("/warehouse/asn-lines", methods=["GET"])
def list_asn_lines():
    get_identity()
    items = list(store.asn_lines.values())
    asn_id = request.args.get("asn_id")
    sku_id = request.args.get("sku_id")
    if asn_id:
        items = [l for l in items if l["asn_id"] == asn_id]
    if sku_id:
        items = [l for l in items if l["sku_id"] == sku_id]
    for l in items:
        calc.refresh_asn_line(l)
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


# ---------------------------------------------------------------------------
# ReceiptEvent / receiving
# ---------------------------------------------------------------------------
def _mint_lpn(sku_id, qty, source_asn_id):
    lpn = new_record()
    # generate a unique system lpn_code
    code = "LPN-" + lpn["id"][:8]
    lpn.update({
        "lpn_code": code,
        "sku_id": sku_id,
        "location_id": None,
        "source_asn_id": source_asn_id,
        "qty": qty,
        "disposition": "PUTAWAY_PENDING",
    })
    store.license_plates[lpn["id"]] = lpn
    return lpn


@bp.route("/warehouse/inbound-asns/<asn_id>/receipts", methods=["POST"])
def post_receipt(asn_id):
    user_id, role = get_identity()
    require_roles(role, ["ReceivingClerk"])
    asn = lookup(store.inbound_asns, asn_id)
    body = get_json_body()
    asn_line_id = require_str(body, "asn_line_id")
    line = lookup_fk(store.asn_lines, asn_line_id, "asn_line_id")
    received_qty = require_int(body, "received_qty", exclusive_min=0)
    # state: ASN must be ANNOUNCED (first) or RECEIVING (subsequent)
    if asn["status"] not in ("ANNOUNCED", "RECEIVING"):
        raise err("ERR_INVALID_STATE", "ASN is not in a receivable state.")
    # referenced line must belong to this ASN
    if line["asn_id"] != asn_id:
        raise err("ERR_NOT_FOUND", "AsnLine does not belong to this ASN.")
    # first receipt advances ANNOUNCED -> RECEIVING and pins clerk
    if asn["status"] == "ANNOUNCED":
        asn["status"] = "RECEIVING"
        asn["received_by_user_id"] = user_id
    # mint LPN
    lpn = _mint_lpn(line["sku_id"], received_qty, asn_id)
    # append receipt event (id + created_at only)
    rec = new_record(with_version=False)
    rec.update({
        "asn_id": asn_id,
        "asn_line_id": asn_line_id,
        "lpn_id": lpn["id"],
        "received_qty": received_qty,
    })
    store.receipt_events[rec["id"]] = rec
    # recompute derived fields
    calc.refresh_asn_line(line)
    sku = store.skus.get(line["sku_id"])
    if sku is not None:
        calc.refresh_sku(sku)
    # every receipt increments the ASN version
    touch(asn)
    return success(serialize(rec), status=201)


@bp.route("/warehouse/inbound-asns/<asn_id>/receipts", methods=["GET"])
def list_receipts_of_asn(asn_id):
    get_identity()
    lookup(store.inbound_asns, asn_id)
    items = [r for r in store.receipt_events.values() if r["asn_id"] == asn_id]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


@bp.route("/warehouse/receipt-events/<event_id>", methods=["GET"])
def get_receipt_event(event_id):
    get_identity()
    rec = lookup(store.receipt_events, event_id)
    return success(serialize(rec))


@bp.route("/warehouse/receipt-events", methods=["GET"])
def list_receipt_events():
    get_identity()
    items = list(store.receipt_events.values())
    asn_line_id = request.args.get("asn_line_id")
    lpn_id = request.args.get("lpn_id")
    asn_id = request.args.get("asn_id")
    if asn_line_id:
        items = [r for r in items if r["asn_line_id"] == asn_line_id]
    if lpn_id:
        items = [r for r in items if r["lpn_id"] == lpn_id]
    if asn_id:
        items = [r for r in items if r["asn_id"] == asn_id]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Close (putaway / cross-dock fork), close-crossdock, cancel
# ---------------------------------------------------------------------------
@bp.route("/warehouse/inbound-asns/<asn_id>/close", methods=["POST"])
def close_asn(asn_id):
    _, role = get_identity()
    require_roles(role, ["ReceivingClerk"])
    asn = lookup(store.inbound_asns, asn_id)
    if asn["status"] != "RECEIVING":
        raise err("ERR_INVALID_STATE", "ASN can only be closed from RECEIVING.")
    # no OPEN line (priority 14)
    lines = [l for l in store.asn_lines.values() if l["asn_id"] == asn_id]
    for l in lines:
        calc.refresh_asn_line(l)
    if any(l["line_status"] == "OPEN" for l in lines):
        raise err("ERR_ASN_LINES_OPEN", "Every ASN line must be SATISFIED or OVER to close.")
    pending_lpns = [
        lp for lp in store.license_plates.values()
        if lp["source_asn_id"] == asn_id and lp["disposition"] == "PUTAWAY_PENDING"
    ]
    if asn["handling_mode"] == "PUTAWAY":
        asn["status"] = "PUT_AWAY"
        for lp in pending_lpns:
            task = new_record()
            task.update({
                "lpn_id": lp["id"],
                "target_location_id": None,
                "status": "CREATED",
            })
            store.putaway_tasks[task["id"]] = task
    else:  # CROSS_DOCK
        asn["status"] = "CROSS_DOCKED"
        affected_locations = set()
        affected_skus = set()
        for lp in sorted(pending_lpns, key=lambda x: (x["created_at"], x.get("_seq", 0))):
            loc = calc.crossdock_location_select(lp)
            if loc is None:
                # No eligible cross-dock lane; per PRD there is no declared error
                # for this path, so leave the LPN PUTAWAY_PENDING (best effort).
                continue
            lp["location_id"] = loc["id"]
            lp["disposition"] = "STORED"
            touch(lp)
            affected_locations.add(loc["id"])
            affected_skus.add(lp["sku_id"])
        for loc_id in affected_locations:
            calc.refresh_location(store.locations[loc_id])
        for sku_id in affected_skus:
            calc.refresh_sku(store.skus[sku_id])
    touch(asn)
    return success(serialize(asn))


@bp.route("/warehouse/inbound-asns/<asn_id>/close-crossdock", methods=["POST"])
def close_crossdock(asn_id):
    _, role = get_identity()
    require_roles(role, ["ReceivingClerk"])
    asn = lookup(store.inbound_asns, asn_id)
    if asn["status"] != "CROSS_DOCKED":
        raise err("ERR_INVALID_STATE", "ASN is not CROSS_DOCKED.")
    asn["status"] = "CLOSED"
    touch(asn)
    return success(serialize(asn))


@bp.route("/warehouse/inbound-asns/<asn_id>/cancel", methods=["POST"])
def cancel_asn(asn_id):
    _, role = get_identity()
    require_roles(role, ["ReceivingClerk"])
    asn = lookup(store.inbound_asns, asn_id)
    if asn["status"] != "ANNOUNCED":
        raise err("ERR_INVALID_STATE", "Only an ANNOUNCED ASN with no receipts may be cancelled.")
    asn["status"] = "CANCELLED"
    touch(asn)
    return success(serialize(asn))


# ---------------------------------------------------------------------------
# LicensePlate reads
# ---------------------------------------------------------------------------
@bp.route("/warehouse/license-plates/<lpn_id>", methods=["GET"])
def get_lpn(lpn_id):
    get_identity()
    rec = lookup(store.license_plates, lpn_id)
    return success(serialize(rec))


@bp.route("/warehouse/license-plates", methods=["GET"])
def list_lpns():
    get_identity()
    items = list(store.license_plates.values())
    sku_id = request.args.get("sku_id")
    location_id = request.args.get("location_id")
    source_asn_id = request.args.get("source_asn_id")
    disposition = request.args.get("disposition")
    if sku_id:
        items = [lp for lp in items if lp["sku_id"] == sku_id]
    if location_id:
        items = [lp for lp in items if lp["location_id"] == location_id]
    if source_asn_id:
        items = [lp for lp in items if lp["source_asn_id"] == source_asn_id]
    if disposition:
        items = [lp for lp in items if lp["disposition"] == disposition]
    page, limit, offset, total = paginate(items)
    return list_success(page, limit, offset, total)
