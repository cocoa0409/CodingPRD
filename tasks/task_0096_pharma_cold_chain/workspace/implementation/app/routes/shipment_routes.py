"""Outbound shipment routes."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from flask import Flask

from ..audit import emit_sync_event, write_audit
from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_filter, parse_limit_offset
from ..response import paginate
from ..services.calculations import (
    PACKAGING_FOR_ZONE,
    compute_shipment_total_cents,
)
from ..services.fefo import pick_fefo_lot
from ..services.posture import recompute_after_bin_change
from ..services.validation import (
    check_occ,
    require_enum,
    require_int,
    require_keys,
    require_number,
    require_str,
)
from ..store import LOCK, bump_version, common_fields_create, get_store
from ._helpers import created, get_json_body, list_ok, ok


_PACKAGINGS = {"INSULATED_PCM", "INSULATED_DRY_ICE", "AMBIENT"}


def _in_range(temp_c: float | int | Decimal, zone_low, zone_high) -> bool:
    t = Decimal(str(temp_c))
    lo = Decimal(str(zone_low))
    hi = Decimal(str(zone_high))
    return lo <= t <= hi


def _ref_zone_for_product(warehouse_id: str, product: dict[str, Any]) -> dict[str, Any] | None:
    """Find any zone of the product's required_zone_type in this warehouse to read bounds."""
    for z in get_store().zones.values():
        if z["warehouse_id"] == warehouse_id and z["zone_type"] == product["required_zone_type"]:
            return z
    return None


def register(app: Flask) -> None:
    # ------------------------------------------------------------------
    # Create shipment
    # ------------------------------------------------------------------
    @app.route("/warehouses/<wid>/shipments", methods=["POST"])
    @require_auth("Picker")
    def create_shipment(wid: str):
        body = get_json_body()
        store = get_store()
        if wid not in store.warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        require_keys(
            body,
            [
                "customer_id",
                "product_id",
                "quantity_units",
                "packaging_kind",
                "pick_temp_c",
                "vehicle_precondition_temp_c",
            ],
        )
        product = store.products.get(body["product_id"])
        if not product:
            raise ApiError("ERR_NOT_FOUND", "Product not found")
        qty_raw = body["quantity_units"]
        if isinstance(qty_raw, bool) or not isinstance(qty_raw, int):
            raise ApiError("ERR_QUANTITY_INVALID", "quantity_units must be integer")
        if qty_raw <= 0:
            raise ApiError("ERR_QUANTITY_INVALID", "quantity_units must be > 0")
        packaging = require_enum(body["packaging_kind"], "packaging_kind", _PACKAGINGS)
        with LOCK:
            sh = common_fields_create()
            sh.update(
                {
                    "warehouse_id": wid,
                    "customer_id": require_str(body["customer_id"], "customer_id"),
                    "product_id": body["product_id"],
                    "quantity_units": qty_raw,
                    "packaging_kind": packaging,
                    "pick_lot_id": None,
                    "pick_temp_c": require_number(body["pick_temp_c"], "pick_temp_c"),
                    "vehicle_precondition_temp_c": require_number(
                        body["vehicle_precondition_temp_c"], "vehicle_precondition_temp_c"
                    ),
                    "logger_armed": False,
                    "dispatched_at_minutes": None,
                    "status": "PLANNED",
                }
            )
            store.shipments[sh["id"]] = sh
        return created(sh)

    # ------------------------------------------------------------------
    # List/get shipment
    # ------------------------------------------------------------------
    @app.route("/warehouses/<wid>/shipments", methods=["GET"])
    @require_auth("Picker", "QAOfficer", "RecallOfficer", "WarehouseAdmin")
    def list_shipments(wid: str):
        store = get_store()
        if wid not in store.warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        limit, offset = parse_limit_offset()
        status_f = parse_filter("status")
        items = [s for s in store.shipments.values() if s["warehouse_id"] == wid]
        if status_f is not None:
            items = [s for s in items if s["status"] == status_f]
        items.sort(key=lambda s: s["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)

    @app.route("/shipments/<sid>", methods=["GET"])
    @require_auth("Picker", "QAOfficer", "RecallOfficer", "WarehouseAdmin")
    def get_shipment(sid: str):
        sh = get_store().shipments.get(sid)
        if not sh:
            raise ApiError("ERR_NOT_FOUND", "Shipment not found")
        return ok(sh)

    # ------------------------------------------------------------------
    # Shipment summary (computed) — PRD §3.6
    # ------------------------------------------------------------------
    @app.route("/shipments/<sid>/summary", methods=["GET"])
    @require_auth("Picker", "WarehouseAdmin")
    def shipment_summary(sid: str):
        store = get_store()
        sh = store.shipments.get(sid)
        if not sh:
            raise ApiError("ERR_NOT_FOUND", "Shipment not found")
        product = store.products.get(sh["product_id"])
        if not product:
            raise ApiError("ERR_NOT_FOUND", "Product not found")
        total = compute_shipment_total_cents(
            required_zone_type=product["required_zone_type"],
            packaging_kind=sh["packaging_kind"],
            quantity_units=int(sh["quantity_units"]),
            product_special_tag=product.get("special_storage_tag", "NONE"),
        )
        return ok(
            {
                "shipment_id": sh["id"],
                "total_cents": total,
                "required_zone_type": product["required_zone_type"],
                "packaging_kind": sh["packaging_kind"],
                "quantity_units": int(sh["quantity_units"]),
                "special_storage_tag": product.get("special_storage_tag", "NONE"),
            }
        )

    # ------------------------------------------------------------------
    # Pick (Picker)
    # ------------------------------------------------------------------
    @app.route("/shipments/<sid>/pick", methods=["POST"])
    @require_auth("Picker")
    def pick_shipment(sid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            sh = store.shipments.get(sid)
            if not sh:
                raise ApiError("ERR_NOT_FOUND", "Shipment not found")
            if sh["status"] != "PLANNED":
                raise ApiError("ERR_SHIPMENT_STATE_INVALID", "Shipment not in PLANNED")
            check_occ(sh, body)
            warehouse = store.warehouses[sh["warehouse_id"]]
            product = store.products[sh["product_id"]]

            lot = pick_fefo_lot(
                warehouse_id=sh["warehouse_id"],
                product_id=sh["product_id"],
                quantity_units=int(sh["quantity_units"]),
                clock_minutes=int(warehouse["clock_minutes"]),
            )

            # Zone-frozen check on lot's current bin's parent zone.
            bin_row = store.bins.get(lot.get("bin_id")) if lot.get("bin_id") else None
            if bin_row is not None:
                z = store.zones.get(bin_row["zone_id"])
                if z is not None and z.get("current_posture") == "FROZEN":
                    raise ApiError("ERR_ZONE_FROZEN", "Lot's zone is FROZEN")

            # Decrement stock atomically.
            qty = int(sh["quantity_units"])
            lot["quantity_on_hand"] = int(lot["quantity_on_hand"]) - qty
            lot["quantity_picked"] = int(lot.get("quantity_picked", 0)) + qty
            bump_version(lot)

            # Recompute bin occupied volumes/weights.
            if bin_row is not None:
                bin_row["occupied_volume"] = max(0, int(bin_row.get("occupied_volume", 0)) - qty)
                bin_row["occupied_weight_kg"] = float(
                    max(
                        Decimal(0),
                        Decimal(str(bin_row.get("occupied_weight_kg", 0)))
                        - Decimal(qty) * Decimal(str(product["unit_weight_kg"])),
                    )
                )
                if bin_row["occupied_volume"] == 0:
                    bin_row["current_lot_id"] = None
                    bin_row["status"] = "AVAILABLE"
                bump_version(bin_row)
                recompute_after_bin_change(bin_row["zone_id"])

            sh["pick_lot_id"] = lot["id"]
            sh["status"] = "PICKED"
            bump_version(sh)
        return ok(sh)

    # ------------------------------------------------------------------
    # Pack (Picker)
    # ------------------------------------------------------------------
    @app.route("/shipments/<sid>/pack", methods=["POST"])
    @require_auth("Picker")
    def pack_shipment(sid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            sh = store.shipments.get(sid)
            if not sh:
                raise ApiError("ERR_NOT_FOUND", "Shipment not found")
            if sh["status"] != "PICKED":
                raise ApiError("ERR_SHIPMENT_STATE_INVALID", "Shipment not in PICKED")
            check_occ(sh, body)
            product = store.products[sh["product_id"]]
            # Packaging match (priority 15).
            expected_pack = PACKAGING_FOR_ZONE.get(product["required_zone_type"])
            if expected_pack and sh["packaging_kind"] != expected_pack:
                raise ApiError(
                    "ERR_PACKAGING_MISMATCH",
                    f"packaging_kind must be {expected_pack} for {product['required_zone_type']}",
                )
            # Temperature pre-checks (priority 18).
            ref = _ref_zone_for_product(sh["warehouse_id"], product)
            if ref is None:
                raise ApiError(
                    "ERR_TEMP_PRECHECK_FAIL",
                    "No reference zone available for product's required_zone_type",
                )
            if not _in_range(sh["pick_temp_c"], ref["target_temp_low_c"], ref["target_temp_high_c"]):
                raise ApiError("ERR_TEMP_PRECHECK_FAIL", "pick_temp_c out of range")
            if not _in_range(
                sh["vehicle_precondition_temp_c"],
                ref["target_temp_low_c"],
                ref["target_temp_high_c"],
            ):
                raise ApiError(
                    "ERR_TEMP_PRECHECK_FAIL", "vehicle_precondition_temp_c out of range"
                )
            sh["status"] = "PACKED"
            bump_version(sh)
        return ok(sh)

    # ------------------------------------------------------------------
    # Dispatch (Picker)
    # ------------------------------------------------------------------
    @app.route("/shipments/<sid>/dispatch", methods=["POST"])
    @require_auth("Picker")
    def dispatch_shipment(sid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            sh = store.shipments.get(sid)
            if not sh:
                raise ApiError("ERR_NOT_FOUND", "Shipment not found")
            if sh["status"] != "PACKED":
                raise ApiError("ERR_SHIPMENT_STATE_INVALID", "Shipment not in PACKED")
            check_occ(sh, body)
            product = store.products[sh["product_id"]]
            warehouse = store.warehouses[sh["warehouse_id"]]
            ref = _ref_zone_for_product(sh["warehouse_id"], product)
            if ref is None or not _in_range(
                sh["pick_temp_c"], ref["target_temp_low_c"], ref["target_temp_high_c"]
            ):
                raise ApiError("ERR_TEMP_PRECHECK_FAIL", "pick_temp_c out of range at dispatch")
            if not _in_range(
                sh["vehicle_precondition_temp_c"],
                ref["target_temp_low_c"],
                ref["target_temp_high_c"],
            ):
                raise ApiError(
                    "ERR_TEMP_PRECHECK_FAIL",
                    "vehicle_precondition_temp_c out of range at dispatch",
                )
            sh["logger_armed"] = True
            sh["dispatched_at_minutes"] = int(warehouse["clock_minutes"])
            sh["status"] = "DISPATCHED"
            bump_version(sh)
            emit_sync_event(
                warehouse_id=sh["warehouse_id"],
                target_system="TMS",
                event_type="SHIPMENT_DISPATCHED",
                payload={
                    "shipment_id": sh["id"],
                    "pick_lot_id": sh.get("pick_lot_id"),
                    "customer_id": sh["customer_id"],
                },
            )
            write_audit(
                warehouse_id=sh["warehouse_id"],
                action="SHIPMENT_DISPATCH",
                target_id=sh["id"],
                at_minutes=int(warehouse["clock_minutes"]),
            )
        return ok(sh)

    # ------------------------------------------------------------------
    # QA release (QAOfficer)
    # ------------------------------------------------------------------
    @app.route("/shipments/<sid>/qa-release", methods=["POST"])
    @require_auth("QAOfficer")
    def qa_release_shipment(sid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            sh = store.shipments.get(sid)
            if not sh:
                raise ApiError("ERR_NOT_FOUND", "Shipment not found")
            if sh["status"] != "QUARANTINED":
                raise ApiError("ERR_SHIPMENT_STATE_INVALID", "Shipment not in QUARANTINED")
            check_occ(sh, body)
            # Find the linked deviation: most-recent deviation on the lot's bin's zone.
            lot = store.lots.get(sh.get("pick_lot_id")) if sh.get("pick_lot_id") else None
            linked_zone_id = None
            if lot is not None and lot.get("bin_id"):
                b = store.bins.get(lot["bin_id"])
                if b is not None:
                    linked_zone_id = b["zone_id"]

            linked_dev = None
            if linked_zone_id:
                devs = [
                    d
                    for d in store.deviations.values()
                    if d["zone_id"] == linked_zone_id
                ]
                devs.sort(key=lambda d: d["created_at"], reverse=True)
                linked_dev = devs[0] if devs else None
            if linked_dev is None or linked_dev.get("qa_decision") != "RELEASE":
                raise ApiError(
                    "ERR_SHIPMENT_STATE_INVALID",
                    "Linked deviation qa_decision is not RELEASE",
                )
            warehouse = store.warehouses[sh["warehouse_id"]]
            sh["status"] = "PACKED"
            bump_version(sh)
            write_audit(
                warehouse_id=sh["warehouse_id"],
                action="SHIPMENT_QA_RELEASE",
                target_id=sh["id"],
                at_minutes=int(warehouse["clock_minutes"]),
            )
        return ok(sh)

    # ------------------------------------------------------------------
    # Cancel (Picker)
    # ------------------------------------------------------------------
    @app.route("/shipments/<sid>/cancel", methods=["POST"])
    @require_auth("Picker")
    def cancel_shipment(sid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            sh = store.shipments.get(sid)
            if not sh:
                raise ApiError("ERR_NOT_FOUND", "Shipment not found")
            if sh["status"] not in ("PLANNED", "PICKED"):
                raise ApiError("ERR_SHIPMENT_STATE_INVALID", "Cannot cancel in current state")
            check_occ(sh, body)
            warehouse = store.warehouses[sh["warehouse_id"]]
            if sh["status"] == "PICKED":
                lot = store.lots.get(sh.get("pick_lot_id")) if sh.get("pick_lot_id") else None
                if lot is not None:
                    qty = int(sh["quantity_units"])
                    lot["quantity_on_hand"] = int(lot["quantity_on_hand"]) + qty
                    lot["quantity_picked"] = max(0, int(lot.get("quantity_picked", 0)) - qty)
                    bump_version(lot)
                    bin_row = store.bins.get(lot.get("bin_id")) if lot.get("bin_id") else None
                    if bin_row is not None:
                        product = store.products[sh["product_id"]]
                        bin_row["occupied_volume"] = int(bin_row.get("occupied_volume", 0)) + qty
                        bin_row["occupied_weight_kg"] = float(
                            Decimal(str(bin_row.get("occupied_weight_kg", 0)))
                            + Decimal(qty) * Decimal(str(product["unit_weight_kg"]))
                        )
                        bin_row["current_lot_id"] = lot["id"]
                        bin_row["status"] = "OCCUPIED"
                        bump_version(bin_row)
                        recompute_after_bin_change(bin_row["zone_id"])
            sh["status"] = "CANCELLED"
            bump_version(sh)
            write_audit(
                warehouse_id=sh["warehouse_id"],
                action="SHIPMENT_CANCEL",
                target_id=sh["id"],
                at_minutes=int(warehouse["clock_minutes"]),
            )
        return ok(sh)
