from flask import Blueprint, request

from core import (store, require, get_body, get_or_404, ok, ok_list, paginate, common_create, touch,
                  clock, parse_iso, ApiError,
                  ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_FORBIDDEN,
                  ERR_ORDER_NOT_FULFILLABLE, ERR_BATCH_NOT_SALEABLE, ERR_INSUFFICIENT_LIVE_STOCK,
                  ERR_ORDER_ALREADY_CLOSED, ERR_PHYTO_REQUIRED, ERR_PHYTO_INVALID,
                  ERR_PHYTO_EXPIRED, ERR_PHYTO_DESTINATION_MISMATCH)
import services as svc

bp = Blueprint("shipments", __name__)

ROLES = ["SalesCoordinator", "Broker"]
LINE_ID_KEYS = ("order_line_id", "line_id", "id")


def _line_ref(item):
    for k in LINE_ID_KEYS:
        if isinstance(item, dict) and k in item and item[k] is not None:
            return item[k]
    return None


def _batch_for_line(line):
    entry = store.availability.get(line["availability_entry_id"])
    if entry is None:
        return None
    return store.batches.get(entry["batch_id"])


@bp.post("/nursery/shipments")
def create_shipment():
    require(["SalesCoordinator"])
    body = get_body()
    raw_oid = body.get("order_id")
    if isinstance(raw_oid, str) and raw_oid not in store.orders:
        raise ApiError(ERR_NOT_FOUND, "Order not found")
    order_id = body.get("order_id")
    if not isinstance(order_id, str) or order_id.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST, "order_id is required")
    if order_id not in store.orders:
        raise ApiError(ERR_NOT_FOUND, "Order not found")
    phyto_certificate_id = body.get("phyto_certificate_id")
    if phyto_certificate_id is not None:
        if not isinstance(phyto_certificate_id, str):
            raise ApiError(ERR_INVALID_REQUEST, "phyto_certificate_id must be a string")
        if phyto_certificate_id not in store.phyto_certs:
            raise ApiError(ERR_NOT_FOUND, "Phyto certificate not found")
    lines = body.get("lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise ApiError(ERR_INVALID_REQUEST, "lines must be a non-empty array")

    dispatch_lines = []
    ship_units = 0
    for item in lines:
        lref = _line_ref(item)
        qty = item.get("quantity") if isinstance(item, dict) else None
        if lref is None or qty is None:
            raise ApiError(ERR_INVALID_REQUEST, "each line needs an order line id and quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise ApiError(ERR_INVALID_REQUEST, "line quantity must be a positive integer")
        line = store.order_lines.get(lref)
        if line is None:
            raise ApiError(ERR_NOT_FOUND, "Order line not found")
        if line["order_id"] != order_id:
            raise ApiError(ERR_INVALID_REQUEST, "Order line does not belong to this order")
        remaining = line["quantity"] - line["shipped_quantity"]
        if qty > remaining:
            raise ApiError(ERR_INVALID_REQUEST, "quantity exceeds remaining committed quantity")
        dispatch_lines.append({"order_line_id": line["id"], "quantity": qty})
        ship_units += qty

    sh = common_create({
        "order_id": order_id,
        "phyto_certificate_id": phyto_certificate_id,
        "ship_units": ship_units,
        "shipped_at": None,
        "status": "DRAFT",
    })
    sh["_lines"] = dispatch_lines
    store.shipments[sh["id"]] = sh
    return ok(sh, 201)


@bp.get("/nursery/shipments/<sid>")
def get_shipment(sid):
    uid, role = require(ROLES)
    sh = get_or_404(store.shipments, sid)
    if role == "Broker":
        o = store.orders.get(sh["order_id"])
        if o is None or o["broker_id"] != uid:
            raise ApiError(ERR_FORBIDDEN, "Broker may only read its own shipments")
    return ok(sh)


@bp.get("/nursery/shipments")
def list_shipments():
    uid, role = require(ROLES)
    rows = list(store.shipments.values())
    if role == "Broker":
        owned = {o["id"] for o in store.orders.values() if o["broker_id"] == uid}
        rows = [s for s in rows if s["order_id"] in owned]
    for key in ("order_id", "status", "phyto_certificate_id"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r[key] == val]
    page, limit, offset, total = paginate(rows)
    return ok_list(page, limit, offset, total)


@bp.post("/nursery/shipments/<sid>/dispatch")
def dispatch_shipment(sid):
    require(["SalesCoordinator"])
    sh = get_or_404(store.shipments, sid)
    if sh["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, "Only a DRAFT shipment can be dispatched")
    order = store.orders.get(sh["order_id"])
    if order["status"] not in ("CONFIRMED", "FULFILLING"):
        raise ApiError(ERR_ORDER_NOT_FULFILLABLE, "Order is not CONFIRMED or FULFILLING")
    broker = store.brokers.get(order["broker_id"])

    # ---- validate all lines before applying (atomic) ----
    remaining_live = {}
    requires_phyto = False
    for dl in sh["_lines"]:
        line = store.order_lines.get(dl["order_line_id"])
        if line is None:
            raise ApiError(ERR_NOT_FOUND, "Order line not found")
        batch = _batch_for_line(line)
        if batch is None or batch["status"] != "SALEABLE":
            raise ApiError(ERR_BATCH_NOT_SALEABLE, "Line does not draw on a SALEABLE batch")
        if batch["id"] not in remaining_live:
            remaining_live[batch["id"]] = batch["live_count"]
        if dl["quantity"] > remaining_live[batch["id"]]:
            raise ApiError(ERR_INSUFFICIENT_LIVE_STOCK, "Batch live stock is insufficient")
        remaining_live[batch["id"]] -= dl["quantity"]
        variety = store.varieties.get(batch["variety_id"])
        if variety and variety.get("requires_phyto"):
            requires_phyto = True

    if requires_phyto:
        cert_id = sh.get("phyto_certificate_id")
        if not cert_id:
            raise ApiError(ERR_PHYTO_REQUIRED, "A phytosanitary certificate is required")
        cert = store.phyto_certs.get(cert_id)
        if cert is None:
            raise ApiError(ERR_PHYTO_REQUIRED, "A phytosanitary certificate is required")
        if cert["status"] == "CONSUMED":
            raise ApiError(ERR_PHYTO_INVALID, "Certificate is not VALID")
        if cert["status"] == "EXPIRED" or clock.now() > parse_iso(cert["valid_until"]):
            raise ApiError(ERR_PHYTO_EXPIRED, "Certificate has expired")
        if cert["destination_state"] != broker["ship_to_state"]:
            raise ApiError(ERR_PHYTO_DESTINATION_MISMATCH, "Certificate destination does not match")

    # ---- apply ----
    affected_zones = set()
    for dl in sh["_lines"]:
        line = store.order_lines[dl["order_line_id"]]
        batch = _batch_for_line(line)
        qty = dl["quantity"]
        line["shipped_quantity"] += qty
        touch(line)
        batch["shipped_count"] += qty
        svc.recompute_live(batch)
        touch(batch)
        affected_zones.add(batch["zone_id"])
    for zid in affected_zones:
        zone = store.zones.get(zid)
        if zone:
            svc.cascade_zone(zone)

    # advance order
    if order["status"] == "CONFIRMED":
        order["status"] = "FULFILLING"
    committed = [l for l in store.order_lines.values()
                 if l["order_id"] == order["id"] and l["status"] in ("COMMITTED", "SHIPPED")]
    if committed and all(l["shipped_quantity"] >= l["quantity"] for l in committed):
        order["status"] = "SHIPPED"
        for l in committed:
            if l["status"] != "SHIPPED":
                l["status"] = "SHIPPED"
                touch(l)
        if broker is not None:
            broker["open_balance_cents"] -= order["order_total_cents"]
            touch(broker)
    touch(order)

    # consume cert
    cert_id = sh.get("phyto_certificate_id")
    if cert_id:
        cert = store.phyto_certs.get(cert_id)
        if cert is not None and cert["status"] == "VALID":
            cert["status"] = "CONSUMED"
            touch(cert)

    sh["shipped_at"] = clock.now_iso()
    sh["status"] = "DISPATCHED"
    touch(sh)
    return ok(sh)


@bp.post("/nursery/shipments/<sid>/void")
def void_shipment(sid):
    require(["SalesCoordinator"])
    sh = get_or_404(store.shipments, sid)
    if sh["status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, "Only a DISPATCHED shipment can be voided")
    order = store.orders.get(sh["order_id"])
    if order is not None and order["status"] == "SHIPPED":
        raise ApiError(ERR_ORDER_ALREADY_CLOSED, "Order is already closed")
    broker = store.brokers.get(order["broker_id"]) if order else None

    affected_zones = set()
    for dl in sh["_lines"]:
        line = store.order_lines.get(dl["order_line_id"])
        if line is None:
            continue
        qty = dl["quantity"]
        line["shipped_quantity"] -= qty
        if line["status"] == "SHIPPED":
            line["status"] = "COMMITTED"
        touch(line)
        batch = _batch_for_line(line)
        if batch is not None:
            batch["shipped_count"] -= qty
            svc.recompute_live(batch)
            touch(batch)
            affected_zones.add(batch["zone_id"])
    for zid in affected_zones:
        zone = store.zones.get(zid)
        if zone:
            svc.cascade_zone(zone)

    if order is not None:
        any_shipped = any(l["shipped_quantity"] > 0 for l in store.order_lines.values()
                          if l["order_id"] == order["id"])
        if order["status"] == "FULFILLING" and not any_shipped:
            order["status"] = "CONFIRMED"
        touch(order)

    cert_id = sh.get("phyto_certificate_id")
    if cert_id:
        cert = store.phyto_certs.get(cert_id)
        if cert is not None and cert["status"] == "CONSUMED":
            cert["status"] = "VALID"
            touch(cert)

    sh["status"] = "VOIDED"
    touch(sh)
    return ok(sh)
