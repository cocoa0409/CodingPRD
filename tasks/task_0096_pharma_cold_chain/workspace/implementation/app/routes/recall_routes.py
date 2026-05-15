"""Recall lifecycle routes."""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from flask import Flask

from ..audit import emit_sync_event, write_audit
from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..pagination import parse_filter, parse_limit_offset
from ..response import paginate
from ..services.calculations import (
    compute_report_due_minutes,
    effectiveness_pass,
    projected_effectiveness,
)
from ..services.fefo import allocate_quarantine_bin
from ..services.posture import recompute_after_bin_change
from ..services.validation import (
    check_occ,
    require_enum,
    require_int,
    require_keys,
    require_str,
)
from ..store import (
    LOCK,
    bump_version,
    common_fields_append_only,
    common_fields_create,
    get_store,
)
from ._helpers import created, get_json_body, list_ok, ok


_CLASSIFICATIONS = {"CLASS_I", "CLASS_II", "CLASS_III"}
_SCOPE_KINDS = {"ON_HAND", "SHIPPED"}


def _scope_entries_for(recall_id: str) -> list[dict[str, Any]]:
    return [
        e
        for e in get_store().recall_scope_entries.values()
        if e["recall_id"] == recall_id
    ]


def _expected_units(recall_id: str) -> int:
    return sum(
        int(e["units"]) for e in _scope_entries_for(recall_id) if e["scope_kind"] == "SHIPPED"
    )


def _distinct_shipped_customers(recall_id: str) -> int:
    store = get_store()
    custs: set[str] = set()
    for e in _scope_entries_for(recall_id):
        if e["scope_kind"] != "SHIPPED":
            continue
        ship_id = e.get("shipment_id")
        if ship_id:
            sh = store.shipments.get(ship_id)
            if sh is not None:
                custs.add(sh["customer_id"])
    return len(custs)


def _maybe_auto_advance(recall: dict[str, Any], warehouse: dict[str, Any]) -> None:
    """Trigger auto state advancements based on counters / clock."""
    if recall["status"] == "ANNOUNCED":
        if int(recall.get("notifications_sent", 0)) >= int(recall.get("notifications_required", 0)):
            recall["status"] = "RETURNS_IN_PROGRESS"
            bump_version(recall)
    if recall["status"] == "RETURNS_IN_PROGRESS":
        expected = int(recall.get("returns_expected_units", 0) or 0)
        received = int(recall.get("returns_received_units", 0) or 0)
        clock = int(warehouse["clock_minutes"])
        if (expected > 0 and received >= expected) or (
            recall.get("report_due_minutes") is not None
            and clock >= int(recall["report_due_minutes"])
        ):
            recall["status"] = "EFFECTIVENESS_CHECK"
            bump_version(recall)


def register(app: Flask) -> None:
    # ------------------------------------------------------------------
    # Create recall
    # ------------------------------------------------------------------
    @app.route("/warehouses/<wid>/recalls", methods=["POST"])
    @require_auth("RecallOfficer")
    def create_recall(wid: str):
        body = get_json_body()
        store = get_store()
        if wid not in store.warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        require_keys(body, ["classification", "reason"])
        classification = require_enum(body["classification"], "classification", _CLASSIFICATIONS)
        reason = require_str(body["reason"], "reason")
        with LOCK:
            r = common_fields_create()
            r.update(
                {
                    "warehouse_id": wid,
                    "classification": classification,
                    "reason": reason,
                    "initiated_at_minutes": None,
                    "report_due_minutes": None,
                    "notifications_required": None,
                    "notifications_sent": 0,
                    "returns_expected_units": None,
                    "returns_received_units": 0,
                    "effectiveness_pass": None,
                    "status": "DRAFT",
                }
            )
            store.recalls[r["id"]] = r
        return created(r)

    @app.route("/warehouses/<wid>/recalls", methods=["GET"])
    @require_auth("RecallOfficer", "QAOfficer", "WarehouseAdmin")
    def list_recalls(wid: str):
        store = get_store()
        if wid not in store.warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        limit, offset = parse_limit_offset()
        status_f = parse_filter("status")
        cls_f = parse_filter("classification")
        items = [r for r in store.recalls.values() if r["warehouse_id"] == wid]
        if status_f is not None:
            items = [r for r in items if r["status"] == status_f]
        if cls_f is not None:
            items = [r for r in items if r["classification"] == cls_f]
        items.sort(key=lambda r: r["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)

    @app.route("/recalls/<rid>", methods=["GET"])
    @require_auth("RecallOfficer", "QAOfficer", "WarehouseAdmin")
    def get_recall(rid: str):
        r = get_store().recalls.get(rid)
        if not r:
            raise ApiError("ERR_NOT_FOUND", "Recall not found")
        return ok(r)

    # ------------------------------------------------------------------
    # Add scope entry
    # ------------------------------------------------------------------
    @app.route("/recalls/<rid>/scope", methods=["POST"])
    @require_auth("RecallOfficer")
    def add_scope(rid: str):
        body = get_json_body()
        store = get_store()
        recall = store.recalls.get(rid)
        if not recall:
            raise ApiError("ERR_NOT_FOUND", "Recall not found")
        if recall["status"] != "DRAFT":
            raise ApiError("ERR_RECALL_STATE_INVALID", "Scope entries can only be added in DRAFT")
        require_keys(body, ["lot_id", "units", "scope_kind"])
        lot = store.lots.get(body["lot_id"])
        if not lot:
            raise ApiError("ERR_NOT_FOUND", "Lot not found")
        scope_kind = require_enum(body["scope_kind"], "scope_kind", _SCOPE_KINDS)
        units = require_int(body["units"], "units", allow_zero=False)
        shipment_id = body.get("shipment_id")
        if shipment_id is not None:
            sh = store.shipments.get(shipment_id)
            if not sh:
                raise ApiError("ERR_NOT_FOUND", "Shipment not found")
        with LOCK:
            entry = common_fields_append_only()
            entry.update(
                {
                    "recall_id": rid,
                    "lot_id": lot["id"],
                    "shipment_id": shipment_id,
                    "scope_kind": scope_kind,
                    "units": units,
                }
            )
            store.recall_scope_entries[entry["id"]] = entry
        return created(entry)

    # ------------------------------------------------------------------
    # Announce
    # ------------------------------------------------------------------
    @app.route("/recalls/<rid>/announce", methods=["POST"])
    @require_auth("RecallOfficer")
    def announce_recall(rid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            recall = store.recalls.get(rid)
            if not recall:
                raise ApiError("ERR_NOT_FOUND", "Recall not found")
            if recall["status"] != "DRAFT":
                raise ApiError("ERR_RECALL_NOT_DRAFT", "Recall not in DRAFT")
            check_occ(recall, body)
            scope = _scope_entries_for(rid)
            if not scope:
                raise ApiError("ERR_RECALL_SCOPE_EMPTY", "Recall has no scope entries")

            # SOD: actor must not be the QAOfficer who most-recently assessed a deviation
            # on any in-scope lot's zone.
            actor_user_id, _ = current_actor()
            in_scope_lot_ids = {e["lot_id"] for e in scope}
            in_scope_zone_ids: set[str] = set()
            for lid in in_scope_lot_ids:
                L = store.lots.get(lid)
                if not L:
                    continue
                bin_id = L.get("bin_id")
                if not bin_id:
                    continue
                b = store.bins.get(bin_id)
                if b:
                    in_scope_zone_ids.add(b["zone_id"])
            for d in store.deviations.values():
                if d["zone_id"] in in_scope_zone_ids:
                    assessor = store.deviation_assessed_by.get(d["id"])
                    if assessor and assessor == actor_user_id:
                        raise ApiError(
                            "ERR_SOD_VIOLATION",
                            "Recall officer cannot be the same user as the deviation assessor",
                        )

            warehouse = store.warehouses[recall["warehouse_id"]]
            clock = int(warehouse["clock_minutes"])
            recall["initiated_at_minutes"] = clock
            recall["report_due_minutes"] = compute_report_due_minutes(
                clock, recall["classification"]
            )
            if recall["report_due_minutes"] <= recall["initiated_at_minutes"]:
                raise ApiError(
                    "ERR_RECALL_DEADLINE_INVALID",
                    "report_due_minutes must be strictly greater than initiated_at_minutes",
                )

            # Mark in-scope lots as RECALLED.
            for lid in in_scope_lot_ids:
                L = store.lots.get(lid)
                if L is not None:
                    L["quality_status"] = "RECALLED"
                    bump_version(L)

            # notifications_required = distinct customer_ids among SHIPPED scope.
            recall["notifications_required"] = _distinct_shipped_customers(rid)
            recall["returns_expected_units"] = _expected_units(rid)
            recall["status"] = "ANNOUNCED"
            bump_version(recall)
            _maybe_auto_advance(recall, warehouse)

            emit_sync_event(
                warehouse_id=recall["warehouse_id"],
                target_system="REGULATORY_AUTHORITY",
                event_type="RECALL_ANNOUNCED",
                payload={"recall_id": recall["id"], "classification": recall["classification"]},
            )
            emit_sync_event(
                warehouse_id=recall["warehouse_id"],
                target_system="PHARMACOVIGILANCE",
                event_type="RECALL_ANNOUNCED",
                payload={"recall_id": recall["id"], "classification": recall["classification"]},
            )
            write_audit(
                warehouse_id=recall["warehouse_id"],
                action="RECALL_ANNOUNCE",
                target_id=recall["id"],
                at_minutes=clock,
            )
        return ok(recall)

    # ------------------------------------------------------------------
    # Notify next customer
    # ------------------------------------------------------------------
    @app.route("/recalls/<rid>/notify-next-customer", methods=["POST"])
    @require_auth("RecallOfficer")
    def notify_next(rid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            recall = store.recalls.get(rid)
            if not recall:
                raise ApiError("ERR_NOT_FOUND", "Recall not found")
            if recall["status"] not in ("ANNOUNCED",):
                raise ApiError("ERR_RECALL_STATE_INVALID", "Recall not in ANNOUNCED")
            check_occ(recall, body)
            sent = int(recall.get("notifications_sent", 0))
            required = int(recall.get("notifications_required", 0) or 0)
            if sent >= required:
                raise ApiError(
                    "ERR_RECALL_STATE_INVALID",
                    "All required notifications already sent",
                )
            recall["notifications_sent"] = sent + 1
            bump_version(recall)
            warehouse = store.warehouses[recall["warehouse_id"]]
            _maybe_auto_advance(recall, warehouse)
            write_audit(
                warehouse_id=recall["warehouse_id"],
                action="RECALL_NOTIFY",
                target_id=recall["id"],
                at_minutes=int(warehouse["clock_minutes"]),
            )
        return ok(recall)

    # ------------------------------------------------------------------
    # Record return
    # ------------------------------------------------------------------
    @app.route("/recalls/<rid>/record-return", methods=["POST"])
    @require_auth("RecallOfficer")
    def record_return(rid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            recall = store.recalls.get(rid)
            if not recall:
                raise ApiError("ERR_NOT_FOUND", "Recall not found")
            if recall["status"] not in ("RETURNS_IN_PROGRESS",):
                raise ApiError("ERR_RECALL_STATE_INVALID", "Recall not in RETURNS_IN_PROGRESS")
            require_keys(body, ["scope_entry_id", "units"])
            entry = store.recall_scope_entries.get(body["scope_entry_id"])
            if not entry or entry["recall_id"] != rid:
                raise ApiError("ERR_RETURN_SCOPE_INVALID", "Scope entry not found in this recall")
            if entry["scope_kind"] != "SHIPPED":
                raise ApiError("ERR_RETURN_SCOPE_INVALID", "Scope entry is not SHIPPED")
            units = require_int(body["units"], "units", allow_zero=False)

            # Move into a QUARANTINE-zone bin.
            qbin = allocate_quarantine_bin(recall["warehouse_id"])
            if qbin is not None:
                qbin["occupied_volume"] = int(qbin.get("occupied_volume", 0)) + units
                # No product mass association — recall returns don't carry unit_weight here.
                qbin["status"] = "OCCUPIED"
                if not qbin.get("current_lot_id"):
                    qbin["current_lot_id"] = entry["lot_id"]
                bump_version(qbin)
                recompute_after_bin_change(qbin["zone_id"])

            recall["returns_received_units"] = int(recall.get("returns_received_units", 0)) + units
            bump_version(recall)
            # Record this return for downstream distinct-customer
            # accounting in the preview-projection endpoint (PRD §3.7).
            store.recall_returns.setdefault(rid, []).append(
                {"scope_entry_id": entry["id"], "units": units}
            )
            warehouse = store.warehouses[recall["warehouse_id"]]
            _maybe_auto_advance(recall, warehouse)
            write_audit(
                warehouse_id=recall["warehouse_id"],
                action="RECALL_RECORD_RETURN",
                target_id=recall["id"],
                at_minutes=int(warehouse["clock_minutes"]),
            )
        return ok(recall)

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------
    @app.route("/recalls/<rid>/close", methods=["POST"])
    @require_auth("RecallOfficer")
    def close_recall(rid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            recall = store.recalls.get(rid)
            if not recall:
                raise ApiError("ERR_NOT_FOUND", "Recall not found")
            if recall["status"] != "EFFECTIVENESS_CHECK":
                raise ApiError("ERR_RECALL_STATE_INVALID", "Recall not in EFFECTIVENESS_CHECK")
            check_occ(recall, body)
            warehouse = store.warehouses[recall["warehouse_id"]]
            clock = int(warehouse["clock_minutes"])
            received = int(recall.get("returns_received_units", 0) or 0)
            expected = int(recall.get("returns_expected_units", 0) or 0)
            ok_flag, _ratio = effectiveness_pass(received, expected)
            recall["effectiveness_pass"] = ok_flag
            recall["status"] = "CLOSED"
            bump_version(recall)
            if not ok_flag:
                capa = common_fields_create()
                capa.update(
                    {
                        "warehouse_id": recall["warehouse_id"],
                        "deviation_id": None,
                        "recall_id": recall["id"],
                        "due_minutes": clock + 4320,
                        "status": "OPEN",
                    }
                )
                store.capas[capa["id"]] = capa
            emit_sync_event(
                warehouse_id=recall["warehouse_id"],
                target_system="REGULATORY_AUTHORITY",
                event_type="RECALL_CLOSED",
                payload={
                    "recall_id": recall["id"],
                    "effectiveness_pass": ok_flag,
                    "returns_received_units": received,
                    "returns_expected_units": expected,
                },
            )
            write_audit(
                warehouse_id=recall["warehouse_id"],
                action="RECALL_CLOSE",
                target_id=recall["id"],
                at_minutes=clock,
            )
        return ok(recall)

    # ------------------------------------------------------------------
    # Preview projection (read-only)
    # ------------------------------------------------------------------
    @app.route("/recalls/<rid>/preview", methods=["GET"])
    @require_auth("RecallOfficer", "QAOfficer")
    def preview_recall(rid: str):
        store = get_store()
        recall = store.recalls.get(rid)
        if not recall:
            raise ApiError("ERR_NOT_FOUND", "Recall not found")
        received = int(recall.get("returns_received_units", 0) or 0)
        expected = int(recall.get("returns_expected_units", 0) or 0)
        notifications_sent = int(recall.get("notifications_sent", 0) or 0)
        # PRD §3.7: "credit equal to the count of notified-but-not-yet-
        # returned customers (with a per-notification credit of 1.0
        # unit)". Compute the count of distinct customers who have
        # actually had returns recorded; the remainder of the notified
        # cohort is the notified-but-not-yet-returned count.
        returned_customer_ids: set[str] = set()
        for ret in store.recall_returns.get(rid, []):
            entry = store.recall_scope_entries.get(ret["scope_entry_id"])
            if not entry:
                continue
            ship_id = entry.get("shipment_id")
            if not ship_id:
                continue
            sh = store.shipments.get(ship_id)
            if sh is not None and sh.get("customer_id"):
                returned_customer_ids.add(sh["customer_id"])
        returned_customers = len(returned_customer_ids)
        ok_flag, ratio = projected_effectiveness(
            received, expected, notifications_sent, returned_customers
        )
        return ok(
            {
                "recall_id": recall["id"],
                "projected_received": received + max(0, notifications_sent - returned_customers),
                "returns_expected_units": expected,
                "projected_ratio": str(ratio),
                "projected_pass": ok_flag,
            }
        )
