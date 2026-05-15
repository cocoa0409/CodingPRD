"""Inbound receipt routes — create, inspect, accept, quarantine, release, reject."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from flask import Flask

from ..audit import emit_sync_event, write_audit
from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..pagination import parse_filter, parse_limit_offset
from ..response import paginate
from ..services.fefo import allocate_bin_fefo, allocate_quarantine_bin
from ..services.posture import recompute_after_bin_change
from ..services.validation import (
    check_occ,
    require_bool,
    require_int,
    require_keys,
    require_str,
)
from ..store import (
    LOCK,
    bump_version,
    common_fields_create,
    get_store,
    next_cert_seq,
)
from ._helpers import created, get_json_body, list_ok, ok


def _find_zone_of_type(warehouse_id: str, zone_type: str) -> dict[str, Any] | None:
    for z in get_store().zones.values():
        if z["warehouse_id"] == warehouse_id and z["zone_type"] == zone_type:
            return z
    return None


def _temp_chain_intact(receipt: dict[str, Any], product: dict[str, Any]) -> bool:
    """Every reading.temp_c lies within the permitted range of the product's required_zone_type."""
    ref_zone = _find_zone_of_type(receipt["warehouse_id"], product["required_zone_type"])
    if ref_zone is None:
        # Per PRD: "looked up against any zone of that type in the warehouse".
        # If none exists, we can't claim intactness — return False so it surfaces as TEMP_EXCURSION.
        return False
    tlo = Decimal(str(ref_zone["target_temp_low_c"]))
    thi = Decimal(str(ref_zone["target_temp_high_c"]))
    for entry in receipt["carrier_logger_readings"]:
        t = Decimal(str(entry["temp_c"]))
        if t < tlo or t > thi:
            return False
    return True


def _compute_nonconformance_reason(
    receipt: dict[str, Any],
    supplier: dict[str, Any],
    product: dict[str, Any],
    warehouse: dict[str, Any],
) -> str:
    """Priority cascade per PRD §3.2 — first matching reason wins."""
    clock = int(warehouse["clock_minutes"])
    # 1. UNQUALIFIED_SUPPLIER
    if not supplier.get("qualified", True) or int(supplier["qualification_expiry_minutes"]) <= clock:
        return "UNQUALIFIED_SUPPLIER"
    # 2. UNQUALIFIED_PRODUCT
    if not product.get("qualified", True):
        return "UNQUALIFIED_PRODUCT"
    # 3. EXPIRED_ON_ARRIVAL
    if int(receipt["expiry_minutes"]) <= clock:
        return "EXPIRED_ON_ARRIVAL"
    # 4. VISUAL_FAIL
    if not receipt.get("visual_pass", False):
        return "VISUAL_FAIL"
    # 5. TEMP_EXCURSION
    if not receipt.get("temp_chain_intact", True):
        return "TEMP_EXCURSION"
    return "NONE"


def _validate_logger_readings(readings: Any) -> list[dict[str, Any]]:
    if not isinstance(readings, list) or len(readings) == 0:
        raise ApiError("ERR_LOGGER_DATA_INVALID", "carrier_logger_readings empty or invalid")
    last_minute: int | None = None
    out: list[dict[str, Any]] = []
    for entry in readings:
        if not isinstance(entry, dict) or "minutes" not in entry or "temp_c" not in entry:
            raise ApiError("ERR_LOGGER_DATA_INVALID", "Each reading must have minutes and temp_c")
        m = entry["minutes"]
        if isinstance(m, bool) or not isinstance(m, int):
            raise ApiError("ERR_LOGGER_DATA_INVALID", "minutes must be integer")
        t = entry["temp_c"]
        if isinstance(t, bool) or not isinstance(t, (int, float)):
            raise ApiError("ERR_LOGGER_DATA_INVALID", "temp_c must be number")
        if last_minute is not None and m < last_minute:
            raise ApiError("ERR_LOGGER_DATA_INVALID", "readings not monotonic in minutes")
        last_minute = m
        out.append({"minutes": int(m), "temp_c": float(t)})
    return out


def _mint_lot(
    *,
    warehouse_id: str,
    receipt: dict[str, Any],
    bin_id: str,
    quality_status: str,
) -> dict[str, Any]:
    store = get_store()
    lot = common_fields_create()
    lot.update(
        {
            "warehouse_id": warehouse_id,
            "product_id": receipt["product_id"],
            "supplier_id": receipt["supplier_id"],
            "lot_number": receipt["lot_number"],
            "expiry_minutes": int(receipt["expiry_minutes"]),
            "receipt_id": receipt["id"],
            "quantity_on_hand": int(receipt["quantity_units"]),
            "quantity_picked": 0,
            "bin_id": bin_id,
            "cumulative_excursion_minutes": 0,
            "quality_status": quality_status,
        }
    )
    store.lots[lot["id"]] = lot
    return lot


def _assign_bin(bin_row: dict[str, Any], lot: dict[str, Any], product: dict[str, Any]) -> None:
    """Set bin.current_lot_id, status=OCCUPIED, raise volumes."""
    bin_row["current_lot_id"] = lot["id"]
    bin_row["occupied_volume"] = int(bin_row.get("occupied_volume", 0)) + int(lot["quantity_on_hand"])
    bin_row["occupied_weight_kg"] = float(
        Decimal(str(bin_row.get("occupied_weight_kg", 0)))
        + Decimal(str(lot["quantity_on_hand"])) * Decimal(str(product["unit_weight_kg"]))
    )
    bin_row["status"] = "OCCUPIED"
    bump_version(bin_row)


def _clear_bin(bin_row: dict[str, Any]) -> None:
    bin_row["current_lot_id"] = None
    bin_row["occupied_volume"] = 0
    bin_row["occupied_weight_kg"] = 0
    bin_row["status"] = "AVAILABLE"
    bump_version(bin_row)


def _check_zone_frozen_for_acceptance(zone: dict[str, Any]) -> None:
    if zone.get("current_posture") == "FROZEN":
        raise ApiError("ERR_ZONE_FROZEN", "Zone is FROZEN; allocation blocked")


def _accept_core(
    receipt: dict[str, Any],
    *,
    is_release_from_quarantine: bool,
    previous_quarantine_bin_id: str | None,
) -> None:
    """Shared logic for direct accept and release-from-quarantine."""
    store = get_store()
    warehouse = store.warehouses[receipt["warehouse_id"]]
    product = store.products[receipt["product_id"]]
    supplier = store.suppliers[receipt["supplier_id"]]

    clock = int(warehouse["clock_minutes"])
    # PRD §3.2 — acceptance-time safety checks (priority 12-14)
    if not supplier.get("qualified", True) or int(supplier["qualification_expiry_minutes"]) <= clock:
        raise ApiError("ERR_UNQUALIFIED_SUPPLIER", "Supplier not qualified at accept time")
    if not product.get("qualified", True):
        raise ApiError("ERR_UNQUALIFIED_PRODUCT", "Product not qualified at accept time")
    if int(receipt["expiry_minutes"]) <= clock + 1:
        raise ApiError("ERR_EXPIRED_LOT", "Lot expiry within one minute of clock")

    # PRD §2.12 priority pinning: zone-frozen (priority 11) must be
    # evaluated BEFORE bin-allocation business constraints. When all
    # bins of the matching zone_type sit in zones with FROZEN posture
    # (so they are LOCKED), an attempt to accept "against those bins"
    # is rejected with ERR_ZONE_FROZEN — even though the FEFO filter
    # would otherwise see an empty candidate set and report
    # ERR_NO_ELIGIBLE_BIN. PRD §2.10 wording: "any attempt to accept,
    # release-from-quarantine, or pick against those bins is rejected
    # with `ERR_ZONE_FROZEN`".
    required_zone_type = product["required_zone_type"]
    frozen_zone_present = False
    open_zone_present = False
    for _z in store.zones.values():
        if _z.get("warehouse_id") != receipt["warehouse_id"]:
            continue
        if _z.get("zone_type") != required_zone_type:
            continue
        if _z.get("current_posture") == "FROZEN":
            frozen_zone_present = True
        elif _z.get("current_posture") == "OPEN":
            open_zone_present = True
    if frozen_zone_present and not open_zone_present:
        raise ApiError(
            "ERR_ZONE_FROZEN",
            "Target zone is FROZEN; allocation blocked",
        )

    # Allocate destination bin
    new_bin = allocate_bin_fefo(
        warehouse_id=receipt["warehouse_id"],
        product=product,
        quantity_units=int(receipt["quantity_units"]),
    )
    _check_zone_frozen_for_acceptance(store.zones[new_bin["zone_id"]])

    if is_release_from_quarantine:
        # Lot already exists; update it.
        # Find the existing lot via receipt_id.
        lot = next(
            (L for L in store.lots.values() if L.get("receipt_id") == receipt["id"]),
            None,
        )
        if lot is None:
            # Defensive: should never happen.
            raise ApiError("ERR_VALIDATION_FAILED", "Quarantined lot not found")
        # Clear old quarantine bin.
        if previous_quarantine_bin_id:
            qb = store.bins.get(previous_quarantine_bin_id)
            if qb is not None:
                old_zone_id = qb["zone_id"]
                _clear_bin(qb)
                recompute_after_bin_change(old_zone_id)
        lot["quality_status"] = "RELEASED"
        lot["bin_id"] = new_bin["id"]
        bump_version(lot)
    else:
        lot = _mint_lot(
            warehouse_id=receipt["warehouse_id"],
            receipt=receipt,
            bin_id=new_bin["id"],
            quality_status="RELEASED",
        )

    _assign_bin(new_bin, lot, product)

    seq = next_cert_seq(receipt["warehouse_id"])
    receipt["assigned_bin_id"] = new_bin["id"]
    receipt["acceptance_certificate_no"] = f"CERT-{warehouse['code']}-{seq:06d}"
    receipt["status"] = "ACCEPTED"
    bump_version(receipt)

    # Recompute zone utilisation for the new bin's parent zone.
    recompute_after_bin_change(new_bin["zone_id"])

    if is_release_from_quarantine:
        write_audit(
            warehouse_id=receipt["warehouse_id"],
            action="RECEIPT_RELEASE_FROM_QUARANTINE",
            target_id=receipt["id"],
            at_minutes=clock,
        )
    else:
        # External-sync events: REGULATORY_AUTHORITY + GSP_REPORT, both INBOUND_ACCEPTED.
        emit_sync_event(
            warehouse_id=receipt["warehouse_id"],
            target_system="REGULATORY_AUTHORITY",
            event_type="INBOUND_ACCEPTED",
            payload={"receipt_id": receipt["id"], "lot_id": lot["id"]},
        )
        emit_sync_event(
            warehouse_id=receipt["warehouse_id"],
            target_system="GSP_REPORT",
            event_type="INBOUND_ACCEPTED",
            payload={"receipt_id": receipt["id"], "lot_id": lot["id"]},
        )
        write_audit(
            warehouse_id=receipt["warehouse_id"],
            action="RECEIPT_ACCEPT",
            target_id=receipt["id"],
            at_minutes=clock,
        )


def register(app: Flask) -> None:
    # ------------------------------------------------------------------
    # Create receipt
    # ------------------------------------------------------------------
    @app.route("/warehouses/<wid>/receipts", methods=["POST"])
    @require_auth("Receiver")
    def create_receipt(wid: str):
        body = get_json_body()
        store = get_store()
        wh = store.warehouses.get(wid)
        if not wh:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        require_keys(
            body,
            [
                "supplier_id",
                "product_id",
                "lot_number",
                "expiry_minutes",
                "quantity_units",
                "carrier_logger_readings",
                "visual_pass",
            ],
        )
        supplier = store.suppliers.get(body["supplier_id"])
        if not supplier:
            raise ApiError("ERR_NOT_FOUND", "Supplier not found")
        product = store.products.get(body["product_id"])
        if not product:
            raise ApiError("ERR_NOT_FOUND", "Product not found")

        # NOTE: readings array on create is captured as-is; monotonicity is
        # only enforced at inspect time (PRD §3.2 — Logger data validity is
        # priority 23, evaluated on inspect).
        readings = body["carrier_logger_readings"]
        if not isinstance(readings, list):
            raise ApiError("ERR_VALIDATION_FAILED", "carrier_logger_readings must be array")

        visual_pass = body["visual_pass"]
        if not isinstance(visual_pass, bool):
            raise ApiError("ERR_VALIDATION_FAILED", "visual_pass must be boolean")

        with LOCK:
            r = common_fields_create()
            r.update(
                {
                    "warehouse_id": wid,
                    "supplier_id": body["supplier_id"],
                    "product_id": body["product_id"],
                    "lot_number": require_str(body["lot_number"], "lot_number"),
                    "expiry_minutes": require_int(
                        body["expiry_minutes"], "expiry_minutes", allow_zero=True
                    ),
                    "quantity_units": require_int(
                        body["quantity_units"], "quantity_units", allow_zero=False
                    ),
                    "carrier_logger_readings": list(readings),
                    "visual_pass": visual_pass,
                    "temp_chain_intact": None,
                    "nonconformance_reason": None,
                    "assigned_bin_id": None,
                    "acceptance_certificate_no": None,
                    "status": "PENDING_INSPECTION",
                }
            )
            store.receipts[r["id"]] = r
        return created(r)

    # ------------------------------------------------------------------
    # List/get receipts
    # ------------------------------------------------------------------
    @app.route("/warehouses/<wid>/receipts", methods=["GET"])
    @require_auth("Receiver", "QAOfficer", "WarehouseAdmin")
    def list_receipts(wid: str):
        store = get_store()
        if wid not in store.warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        limit, offset = parse_limit_offset()
        status_f = parse_filter("status")
        items = [r for r in store.receipts.values() if r["warehouse_id"] == wid]
        if status_f is not None:
            items = [r for r in items if r["status"] == status_f]
        items.sort(key=lambda r: r["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)

    @app.route("/receipts/<rid>", methods=["GET"])
    @require_auth("Receiver", "QAOfficer", "WarehouseAdmin")
    def get_receipt(rid: str):
        r = get_store().receipts.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND", "Receipt not found")
        return ok(r)

    # ------------------------------------------------------------------
    # Inspect
    # ------------------------------------------------------------------
    @app.route("/receipts/<rid>/inspect", methods=["POST"])
    @require_auth("Receiver")
    def inspect_receipt(rid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            r = store.receipts.get(rid)
            if not r:
                raise ApiError("ERR_NOT_FOUND", "Receipt not found")
            if r["status"] != "PENDING_INSPECTION":
                raise ApiError("ERR_RECEIPT_NOT_PENDING", "Receipt not in PENDING_INSPECTION")
            check_occ(r, body)
            # Validate readings: non-empty, monotonic.
            cleaned = _validate_logger_readings(r["carrier_logger_readings"])
            r["carrier_logger_readings"] = cleaned
            if r.get("visual_pass") is None:
                raise ApiError("ERR_LOGGER_DATA_INVALID", "visual_pass not provided")

            warehouse = store.warehouses[r["warehouse_id"]]
            product = store.products[r["product_id"]]
            supplier = store.suppliers[r["supplier_id"]]

            r["temp_chain_intact"] = _temp_chain_intact(r, product)
            r["nonconformance_reason"] = _compute_nonconformance_reason(
                r, supplier, product, warehouse
            )
            r["status"] = "INSPECTED"
            bump_version(r)
            # Remember who inspected this receipt (for SOD on accept).
            user_id, _role = current_actor()
            store.receipt_inspected_by[r["id"]] = user_id
            write_audit(
                warehouse_id=r["warehouse_id"],
                action="RECEIPT_INSPECT",
                target_id=r["id"],
                at_minutes=int(warehouse["clock_minutes"]),
            )
        return ok(r)

    # ------------------------------------------------------------------
    # Accept (QA)
    # ------------------------------------------------------------------
    @app.route("/receipts/<rid>/accept", methods=["POST"])
    @require_auth("QAOfficer")
    def accept_receipt(rid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            r = store.receipts.get(rid)
            if not r:
                raise ApiError("ERR_NOT_FOUND", "Receipt not found")
            if r["status"] != "INSPECTED":
                raise ApiError("ERR_RECEIPT_NOT_INSPECTED", "Receipt not in INSPECTED")
            check_occ(r, body)
            if r.get("nonconformance_reason") != "NONE":
                # PRD: acceptance is available only when nonconformance_reason == NONE.
                # Use the matching category-specific code for visibility into why.
                reason = r.get("nonconformance_reason")
                if reason == "UNQUALIFIED_SUPPLIER":
                    raise ApiError("ERR_UNQUALIFIED_SUPPLIER", "Supplier not qualified")
                if reason == "UNQUALIFIED_PRODUCT":
                    raise ApiError("ERR_UNQUALIFIED_PRODUCT", "Product not qualified")
                if reason == "EXPIRED_ON_ARRIVAL":
                    raise ApiError("ERR_EXPIRED_LOT", "Lot expired on arrival")
                # VISUAL_FAIL / TEMP_EXCURSION → general "must go to quarantine"
                raise ApiError(
                    "ERR_RECEIPT_NOT_INSPECTED",
                    "Receipt has nonconformance; must be quarantined or rejected first",
                )

            # SOD: inspector cannot be the same user as accepter.
            inspector = store.receipt_inspected_by.get(r["id"])
            actor_user_id, _ = current_actor()
            if inspector and inspector == actor_user_id:
                raise ApiError("ERR_SOD_VIOLATION", "Inspector cannot accept the same receipt")

            _accept_core(r, is_release_from_quarantine=False, previous_quarantine_bin_id=None)
        return ok(r)

    # ------------------------------------------------------------------
    # Quarantine (QA)
    # ------------------------------------------------------------------
    @app.route("/receipts/<rid>/quarantine", methods=["POST"])
    @require_auth("QAOfficer")
    def quarantine_receipt(rid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            r = store.receipts.get(rid)
            if not r:
                raise ApiError("ERR_NOT_FOUND", "Receipt not found")
            if r["status"] != "INSPECTED":
                raise ApiError("ERR_RECEIPT_NOT_INSPECTED", "Receipt not in INSPECTED")
            check_occ(r, body)
            if r.get("nonconformance_reason") in (None, "NONE"):
                raise ApiError(
                    "ERR_RECEIPT_NOT_INSPECTED",
                    "Receipt has no nonconformance; should be accepted instead",
                )

            warehouse = store.warehouses[r["warehouse_id"]]
            qbin = allocate_quarantine_bin(r["warehouse_id"])
            bin_id_for_lot = None
            if qbin is not None:
                if qbin.get("current_lot_id") is None:
                    qbin["current_lot_id"] = "__pending__"  # placeholder; updated below
                bin_id_for_lot = qbin["id"]

            lot = _mint_lot(
                warehouse_id=r["warehouse_id"],
                receipt=r,
                bin_id=bin_id_for_lot,
                quality_status="QUARANTINED",
            )
            if qbin is not None:
                qbin["current_lot_id"] = lot["id"]
                qbin["occupied_volume"] = int(qbin.get("occupied_volume", 0)) + int(r["quantity_units"])
                product = store.products[r["product_id"]]
                qbin["occupied_weight_kg"] = float(
                    Decimal(str(qbin.get("occupied_weight_kg", 0)))
                    + Decimal(str(r["quantity_units"])) * Decimal(str(product["unit_weight_kg"]))
                )
                qbin["status"] = "OCCUPIED"
                bump_version(qbin)
                recompute_after_bin_change(qbin["zone_id"])

            r["status"] = "QUARANTINED"
            r["assigned_bin_id"] = bin_id_for_lot
            bump_version(r)

            actor_user_id, _ = current_actor()
            store.receipt_quarantined_by[r["id"]] = actor_user_id

            emit_sync_event(
                warehouse_id=r["warehouse_id"],
                target_system="REGULATORY_AUTHORITY",
                event_type="INBOUND_QUARANTINED",
                payload={"receipt_id": r["id"], "lot_id": lot["id"]},
            )
            write_audit(
                warehouse_id=r["warehouse_id"],
                action="RECEIPT_QUARANTINE",
                target_id=r["id"],
                at_minutes=int(warehouse["clock_minutes"]),
            )
        return ok(r)

    # ------------------------------------------------------------------
    # Release from quarantine (QA)
    # ------------------------------------------------------------------
    @app.route("/receipts/<rid>/release-from-quarantine", methods=["POST"])
    @require_auth("QAOfficer")
    def release_receipt(rid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            r = store.receipts.get(rid)
            if not r:
                raise ApiError("ERR_NOT_FOUND", "Receipt not found")
            if r["status"] != "QUARANTINED":
                raise ApiError("ERR_RECEIPT_NOT_QUARANTINED", "Receipt not in QUARANTINED")
            check_occ(r, body)
            reason = r.get("nonconformance_reason")
            if reason not in ("VISUAL_FAIL", "TEMP_EXCURSION"):
                raise ApiError(
                    "ERR_RECEIPT_NOT_QUARANTINED",
                    f"Cannot release from quarantine with reason {reason!r}",
                )

            actor_user_id, _ = current_actor()
            prev = store.receipt_quarantined_by.get(r["id"])
            if prev and prev == actor_user_id:
                raise ApiError(
                    "ERR_SOD_VIOLATION", "Same QAOfficer cannot release a receipt they quarantined"
                )

            previous_bin_id = r.get("assigned_bin_id")
            _accept_core(
                r,
                is_release_from_quarantine=True,
                previous_quarantine_bin_id=previous_bin_id,
            )
        return ok(r)

    # ------------------------------------------------------------------
    # Reject (QA)
    # ------------------------------------------------------------------
    @app.route("/receipts/<rid>/reject", methods=["POST"])
    @require_auth("QAOfficer")
    def reject_receipt(rid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            r = store.receipts.get(rid)
            if not r:
                raise ApiError("ERR_NOT_FOUND", "Receipt not found")
            check_occ(r, body)
            if r["status"] == "INSPECTED":
                # Only certain nonconformance reasons allow direct reject from INSPECTED.
                if r.get("nonconformance_reason") not in (
                    "UNQUALIFIED_SUPPLIER",
                    "UNQUALIFIED_PRODUCT",
                    "EXPIRED_ON_ARRIVAL",
                ):
                    raise ApiError(
                        "ERR_RECEIPT_NOT_INSPECTED",
                        "Receipt with this nonconformance must be quarantined first",
                    )
            elif r["status"] != "QUARANTINED":
                raise ApiError("ERR_RECEIPT_NOT_QUARANTINED", "Receipt not in INSPECTED or QUARANTINED")

            warehouse = store.warehouses[r["warehouse_id"]]
            # Clear quarantine bin if any.
            for L in store.lots.values():
                if L.get("receipt_id") == r["id"]:
                    L["quality_status"] = "REJECTED"
                    bin_id = L.get("bin_id")
                    if bin_id:
                        b = store.bins.get(bin_id)
                        if b is not None:
                            old_zone_id = b["zone_id"]
                            _clear_bin(b)
                            recompute_after_bin_change(old_zone_id)
                    L["bin_id"] = None
                    bump_version(L)

            r["status"] = "REJECTED"
            bump_version(r)
            write_audit(
                warehouse_id=r["warehouse_id"],
                action="RECEIPT_REJECT",
                target_id=r["id"],
                at_minutes=int(warehouse["clock_minutes"]),
            )
        return ok(r)
