"""Glass orders, fabrication releases, panel lots and breakage draws."""

from flask import Blueprint

import calc
import domain
from common import created, get_or_404, listing, single
from errors import ApiError
from store import apply, base_row, collection, db, now_iso, touch
from validate import (
    DRAW_REASONS,
    DRAW_STATUSES,
    F,
    GLASS_ORDER_STATES,
    LOT_ADVANCE_TARGETS,
    LOT_STATUSES,
    RELEASE_STATES,
    auth,
    body,
    q_bool,
    q_enum,
    q_str,
    read_fields,
)

bp = Blueprint("glass", __name__)


# ==========================================================================
# GlassOrder
# ==========================================================================
GLASS_ORDER_SPECS = (
    F("package_id", "string"),
    F("supplier_name", "string"),
    F("coating_code", "string"),
    F("quoted_lead_time_days", "int", rng=lambda v: v >= 1),
    F("ordered_lites", "int", rng=lambda v: v >= 1),
    F("expedite_authorized", "bool", required=False, default=False),
)


@bp.post("/glass-orders")
def create_glass_order():
    auth("GlazingProcurement")
    values = read_fields(body(), GLASS_ORDER_SPECS)
    package = get_or_404(db.packages, values["package_id"], "ERR_PACKAGE_NOT_FOUND")
    row = base_row()
    row.update(
        {
            "package_id": package["id"],
            "supplier_name": values["supplier_name"],
            "coating_code": values["coating_code"],
            "quoted_lead_time_days": values["quoted_lead_time_days"],
            "ordered_lites": values["ordered_lites"],
            "expedite_authorized": bool(values["expedite_authorized"]),
            "expedite_tier": 0,
            "state": "ORDERED",
            "coating_revision_count": 0,
            "re_fire_required": False,
            "risk_variant": "NOMINAL",
            "risk_score": calc.D(0),
            "risk_flag": False,
            "effective_lead_days": 0,
            "last_risk_computed_at": None,
            "received_lites": 0,
            "breakage_stock_lites": 0,
        }
    )
    updates, _ = domain.risk_updates(row)
    row.update(updates)
    db.glass_orders[row["id"]] = row
    return created(row, domain.ser_glass_order)


@bp.get("/glass-orders")
def list_glass_orders():
    auth()
    rows = collection(
        db.glass_orders,
        package_id=q_str("package_id"),
        state=q_enum("state", GLASS_ORDER_STATES),
        risk_flag=q_bool("risk_flag"),
    )
    return listing(rows, domain.ser_glass_order)


@bp.get("/glass-orders/<order_id>")
def read_glass_order(order_id):
    auth()
    row = get_or_404(db.glass_orders, order_id, "ERR_GLASS_ORDER_NOT_FOUND")
    return single(row, domain.ser_glass_order)


@bp.post("/glass-orders/<order_id>/start-production")
def start_production(order_id):
    auth("GlazingProcurement")
    order = get_or_404(db.glass_orders, order_id, "ERR_GLASS_ORDER_NOT_FOUND")
    if order["state"] != "ORDERED":
        raise ApiError("ERR_INVALID_STATE")
    apply(order, {"state": "IN_PRODUCTION"})
    return single(order, domain.ser_glass_order)


@bp.post("/glass-orders/<order_id>/coating-revision")
def coating_revision(order_id):
    auth("GlazingProcurement")
    values = read_fields(
        body(), (F("coating_code", "string"), F("re_fire_required", "bool"))
    )
    order = get_or_404(db.glass_orders, order_id, "ERR_GLASS_ORDER_NOT_FOUND")
    if order["state"] in ("RECEIVED", "CLOSED"):
        raise ApiError("ERR_COATING_REVISION_AFTER_RECEIPT")
    if order["state"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE")

    previous_flag = bool(order["risk_flag"])
    revisions = int(order["coating_revision_count"]) + 1
    updates, new_flag = domain.risk_updates(order, coating_revision_count=revisions)
    updates.update(
        {
            "state": "ORDERED",
            "coating_code": values["coating_code"],
            "coating_revision_count": revisions,
            "re_fire_required": True,
            "risk_variant": "EXPEDITE_ADJUSTED",
        }
    )
    apply(order, updates)
    if new_flag and not previous_flag:
        domain.revoke_releases("GLASS_RE_FIRE", glass_order_id=order["id"])
    return single(order, domain.ser_glass_order)


@bp.post("/glass-orders/<order_id>/request-expedite")
def request_expedite(order_id):
    auth("GlazingProcurement")
    values = read_fields(
        body(), (F("expedite_tier", "int", rng=lambda v: v in (1, 2)),)
    )
    order = get_or_404(db.glass_orders, order_id, "ERR_GLASS_ORDER_NOT_FOUND")
    if order["state"] == "CLOSED":
        raise ApiError("ERR_TERMINAL_STATE")
    tier = values["expedite_tier"]
    updates, _ = domain.risk_updates(order, expedite_tier=tier)
    updates.update({"expedite_tier": tier, "risk_variant": "EXPEDITE_ADJUSTED"})
    apply(order, updates)
    return single(order, domain.ser_glass_order)


@bp.post("/glass-orders/<order_id>/receive")
def receive_glass(order_id):
    auth("GlazingProcurement")
    values = read_fields(body(), (F("received_lites", "int", rng=lambda v: v >= 1),))
    order = get_or_404(db.glass_orders, order_id, "ERR_GLASS_ORDER_NOT_FOUND")
    if order["state"] != "IN_PRODUCTION":
        raise ApiError("ERR_INVALID_STATE")
    received = values["received_lites"]
    apply(
        order,
        {
            "state": "RECEIVED",
            "received_lites": received,
            "breakage_stock_lites": calc.breakage_stock_lites(received),
        },
    )
    return single(order, domain.ser_glass_order)


@bp.post("/glass-orders/<order_id>/recompute-risk")
def recompute_risk(order_id):
    auth("GlazingProcurement", "CWProjectManager")
    order = get_or_404(db.glass_orders, order_id, "ERR_GLASS_ORDER_NOT_FOUND")
    updates, _ = domain.risk_updates(order)
    apply(order, updates)
    return single(order, domain.ser_glass_order)


@bp.get("/glass-orders/<order_id>/panel-lots")
def order_panel_lots(order_id):
    auth()
    order = get_or_404(db.glass_orders, order_id, "ERR_GLASS_ORDER_NOT_FOUND")
    rows = collection(
        db.lots,
        glass_order_id=order["id"],
        fabrication_status=q_enum("fabrication_status", LOT_STATUSES),
    )
    return listing(rows, domain.ser_lot, paginated=False)


# ==========================================================================
# FabricationRelease
# ==========================================================================
RELEASE_SPECS = (
    F("package_id", "string"),
    F("submittal_id", "string"),
    F("glass_order_id", "string"),
    F("zone_ids", "array"),
    F("panels_per_zone", "int", rng=lambda v: v >= 1),
    F("lites_per_panel", "int", rng=lambda v: v >= 1),
    F("expected_package_version", "int"),
)


@bp.post("/fabrication-releases")
def create_release():
    auth("CWProjectManager")
    payload = body()
    raw_zone_ids = payload.get("zone_ids")
    if isinstance(raw_zone_ids, list):
        for element in raw_zone_ids:
            if not isinstance(element, str):
                raise ApiError(
                    "ERR_INVALID_REQUEST", "zone_ids must contain only strings"
                )
    values = read_fields(payload, RELEASE_SPECS)

    package = get_or_404(db.packages, values["package_id"], "ERR_PACKAGE_NOT_FOUND")
    submittal = get_or_404(
        db.submittals, values["submittal_id"], "ERR_SUBMITTAL_NOT_FOUND"
    )
    order = get_or_404(
        db.glass_orders, values["glass_order_id"], "ERR_GLASS_ORDER_NOT_FOUND"
    )
    zones = []
    for zone_id in values["zone_ids"]:
        zone = db.zones.get(zone_id)
        if zone is None or zone["package_id"] != package["id"]:
            raise ApiError("ERR_ZONE_NOT_FOUND")
        zones.append(zone)

    if int(values["expected_package_version"]) != int(package["version"]):
        raise ApiError("ERR_STALE_PACKAGE_VERSION")

    if submittal["state"] not in ("APPROVED", "APPROVED_AS_NOTED"):
        raise ApiError("ERR_SUBMITTAL_NOT_APPROVED")
    if package["engineering_posture"] == "FROZEN":
        raise ApiError("ERR_ENGINEERING_POSTURE_FROZEN")
    if not package["mockup_qualified"]:
        raise ApiError("ERR_MOCKUP_NOT_QUALIFIED")

    requested_lites = len(zones) * int(values["panels_per_zone"]) * calc.LITES_PER_PANEL
    if requested_lites > domain.order_ledger(order)["unallocated_lites"]:
        raise ApiError("ERR_GLASS_BALANCE_INSUFFICIENT")
    if order["risk_flag"]:
        raise ApiError("ERR_GLASS_RISK_THRESHOLD_EXCEEDED")

    release = base_row()
    release.update(
        {
            "package_id": package["id"],
            "submittal_id": submittal["id"],
            "glass_order_id": order["id"],
            "zone_ids": list(values["zone_ids"]),
            "panels_per_zone": values["panels_per_zone"],
            "lites_per_panel": values["lites_per_panel"],
            "state": "RELEASED",
            "system_type_at_release": package["system_type"],
            "lot_count": 0,
            "revoked_reason": None,
            "released_at": now_iso(),
        }
    )
    db.releases[release["id"]] = release

    created_lots = 0
    for zone in zones:
        lot = base_row()
        lot.update(
            {
                "release_id": release["id"],
                "glass_order_id": order["id"],
                "zone_id": zone["id"],
                "lot_code": "LOT-F%s-%s" % (zone["floor_number"], zone["elevation_label"]),
                "panel_count": values["panels_per_zone"],
                "lite_count": int(values["panels_per_zone"])
                * int(values["lites_per_panel"]),
                "fabrication_status": "BATCHED",
                "hold_reason": None,
                "status_before_hold": None,
                "shipped_at": None,
            }
        )
        db.lots[lot["id"]] = lot
        created_lots += 1
    release["lot_count"] = created_lots

    domain.unhold_lots_for_release(release, {zone["id"] for zone in zones})

    if package["state"] == "MOCKUP_QUALIFIED":
        domain.sync_package(package, {"state": "IN_FABRICATION"})
    return created(release, domain.ser_release)


@bp.get("/fabrication-releases")
def list_releases():
    auth()
    rows = collection(
        db.releases,
        package_id=q_str("package_id"),
        submittal_id=q_str("submittal_id"),
        glass_order_id=q_str("glass_order_id"),
        state=q_enum("state", RELEASE_STATES),
    )
    return listing(rows, domain.ser_release)


@bp.get("/fabrication-releases/<release_id>")
def read_release(release_id):
    auth()
    row = get_or_404(db.releases, release_id, "ERR_LOT_NOT_FOUND")
    return single(row, domain.ser_release)


@bp.get("/fabrication-releases/<release_id>/panel-lots")
def release_panel_lots(release_id):
    auth()
    release = get_or_404(db.releases, release_id, "ERR_LOT_NOT_FOUND")
    rows = collection(
        db.lots,
        release_id=release["id"],
        fabrication_status=q_enum("fabrication_status", LOT_STATUSES),
    )
    return listing(rows, domain.ser_lot, paginated=False)


# ==========================================================================
# PanelLot
# ==========================================================================
@bp.get("/panel-lots")
def list_lots():
    auth()
    rows = collection(
        db.lots,
        release_id=q_str("release_id"),
        glass_order_id=q_str("glass_order_id"),
        zone_id=q_str("zone_id"),
        fabrication_status=q_enum("fabrication_status", LOT_STATUSES),
    )
    return listing(rows, domain.ser_lot)


@bp.get("/panel-lots/<lot_id>")
def read_lot(lot_id):
    auth()
    row = get_or_404(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    return single(row, domain.ser_lot)


@bp.post("/panel-lots/<lot_id>/advance-fabrication")
def advance_fabrication(lot_id):
    auth("FieldSuperintendent")
    values = read_fields(body(), (F("to_status", "enum", enum=LOT_ADVANCE_TARGETS),))
    lot = get_or_404(db.lots, lot_id, "ERR_LOT_NOT_FOUND")
    to_status = values["to_status"]

    if lot["fabrication_status"] == "SHIPPED":
        raise ApiError("ERR_TERMINAL_STATE")

    release = db.releases.get(lot["release_id"])
    order = db.glass_orders.get(lot["glass_order_id"])
    if to_status == "GLAZED":
        if lot["fabrication_status"] != "BATCHED":
            raise ApiError("ERR_INVALID_STATE")
        if release is None or release["state"] != "RELEASED":
            raise ApiError("ERR_INVALID_STATE")
        if order is None or order["state"] != "RECEIVED":
            raise ApiError("ERR_INVALID_STATE")
    else:
        if lot["fabrication_status"] != "GLAZED":
            raise ApiError("ERR_INVALID_STATE")
        if release is None or release["state"] != "RELEASED":
            raise ApiError("ERR_INVALID_STATE")

    zone = db.zones.get(lot["zone_id"])
    package = None
    if zone is not None:
        package = db.packages.get(zone["package_id"])
    if package is None and release is not None:
        package = db.packages.get(release["package_id"])
    if package is not None and package["engineering_posture"] == "FROZEN":
        raise ApiError("ERR_ENGINEERING_POSTURE_FROZEN")

    if to_status == "GLAZED":
        apply(lot, {"fabrication_status": "GLAZED"})
    else:
        apply(lot, {"fabrication_status": "SHIPPED", "shipped_at": now_iso()})
        if release is not None:
            domain.maybe_close_release(release)
        if order is not None:
            domain.maybe_close_order(order)
    return single(lot, domain.ser_lot)


# ==========================================================================
# BreakageDraw
# ==========================================================================
DRAW_SPECS = (
    F("glass_order_id", "string"),
    F("panel_lot_id", "string"),
    F("quantity_lites", "int", rng=lambda v: v >= 1),
    F("reason", "enum", enum=DRAW_REASONS),
    F("expected_glass_order_version", "int"),
)


@bp.post("/breakage-draws")
def create_draw():
    auth("GlazingProcurement")
    values = read_fields(body(), DRAW_SPECS)
    order = get_or_404(
        db.glass_orders, values["glass_order_id"], "ERR_GLASS_ORDER_NOT_FOUND"
    )
    lot = get_or_404(db.lots, values["panel_lot_id"], "ERR_LOT_NOT_FOUND")

    if int(values["expected_glass_order_version"]) != int(order["version"]):
        raise ApiError("ERR_STALE_GLASS_ORDER_VERSION")

    quantity = int(values["quantity_lites"])
    ledger = domain.order_ledger(order)
    if quantity > ledger["available_stock_lites"]:
        raise ApiError("ERR_BREAKAGE_STOCK_EXHAUSTED")
    if quantity > int(lot["lite_count"]):
        raise ApiError("ERR_DRAW_QUANTITY_INVALID")

    draw = base_row()
    draw.update(
        {
            "glass_order_id": order["id"],
            "panel_lot_id": lot["id"],
            "quantity_lites": quantity,
            "reason": values["reason"],
            "status": "DRAWN",
            "cancelled_reason": None,
        }
    )
    db.draws[draw["id"]] = draw
    touch(order)
    return created(draw, domain.ser_draw)


@bp.get("/breakage-draws")
def list_draws():
    auth()
    rows = collection(
        db.draws,
        glass_order_id=q_str("glass_order_id"),
        panel_lot_id=q_str("panel_lot_id"),
        status=q_enum("status", DRAW_STATUSES),
    )
    return listing(rows, domain.ser_draw)


@bp.get("/breakage-draws/<draw_id>")
def read_draw(draw_id):
    auth()
    row = get_or_404(db.draws, draw_id, "ERR_RESOURCE_NOT_FOUND")
    return single(row, domain.ser_draw)


@bp.post("/breakage-draws/<draw_id>/cancel")
def cancel_draw(draw_id):
    auth("GlazingProcurement")
    values = read_fields(body(), (F("cancelled_reason", "string"),))
    draw = get_or_404(db.draws, draw_id, "ERR_RESOURCE_NOT_FOUND")
    if draw["status"] == "CANCELLED":
        raise ApiError("ERR_TERMINAL_STATE")
    apply(
        draw,
        {"status": "CANCELLED", "cancelled_reason": values["cancelled_reason"]},
    )
    order = db.glass_orders.get(draw["glass_order_id"])
    if order is not None:
        touch(order)
    return single(draw, domain.ser_draw)
