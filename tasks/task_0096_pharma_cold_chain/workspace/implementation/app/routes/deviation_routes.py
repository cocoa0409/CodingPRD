"""Deviation routes — list/get/assess."""
from __future__ import annotations

from typing import Any

from flask import Flask

from ..audit import write_audit
from ..auth import current_actor, require_auth
from ..errors import ApiError
from ..pagination import parse_filter, parse_limit_offset
from ..response import paginate
from ..services.posture import recompute_zone_posture
from ..services.validation import (
    check_occ,
    require_enum,
    require_keys,
    require_str,
)
from ..store import LOCK, bump_version, common_fields_create, get_store
from ._helpers import get_json_body, list_ok, ok


_QA_DECISIONS = {"RELEASE", "QUARANTINE", "REJECT"}


def register(app: Flask) -> None:
    @app.route("/warehouses/<wid>/deviations", methods=["GET"])
    @require_auth("QAOfficer", "RecallOfficer", "WarehouseAdmin")
    def list_deviations(wid: str):
        store = get_store()
        if wid not in store.warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        limit, offset = parse_limit_offset()
        status_f = parse_filter("status")
        cls_f = parse_filter("classification")
        items = [d for d in store.deviations.values() if d["warehouse_id"] == wid]
        if status_f is not None:
            items = [d for d in items if d["status"] == status_f]
        if cls_f is not None:
            items = [d for d in items if d.get("classification") == cls_f]
        items.sort(key=lambda d: d["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)

    @app.route("/deviations/<did>", methods=["GET"])
    @require_auth("QAOfficer", "RecallOfficer", "WarehouseAdmin")
    def get_deviation(did: str):
        d = get_store().deviations.get(did)
        if not d:
            raise ApiError("ERR_NOT_FOUND", "Deviation not found")
        return ok(d)

    @app.route("/deviations/<did>/assess", methods=["POST"])
    @require_auth("QAOfficer")
    def assess_deviation(did: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            dev = store.deviations.get(did)
            if not dev:
                raise ApiError("ERR_NOT_FOUND", "Deviation not found")
            if dev["status"] != "CLOSED_PENDING_QA":
                raise ApiError("ERR_DEVIATION_STATE_INVALID", "Deviation not in CLOSED_PENDING_QA")
            check_occ(dev, body)
            require_keys(body, ["qa_decision"])
            decision = require_enum(body["qa_decision"], "qa_decision", _QA_DECISIONS)
            classification = dev.get("classification")
            capa_id = body.get("capa_id")
            if classification in ("MAJOR", "CRITICAL") and decision == "RELEASE":
                # Must reference an OPEN CAPA.
                if not capa_id:
                    raise ApiError(
                        "ERR_VALIDATION_FAILED",
                        "capa_id required for MAJOR/CRITICAL RELEASE assessment",
                    )
                capa = store.capas.get(capa_id)
                if not capa or capa.get("status") != "OPEN":
                    raise ApiError("ERR_NOT_FOUND", "Referenced CAPA not OPEN")

            warehouse = store.warehouses[dev["warehouse_id"]]
            clock = int(warehouse["clock_minutes"])

            # Update affected lots: every lot whose bin lies in this zone gets
            # its quality_status set per qa_decision.
            zone_id = dev["zone_id"]
            target_status_map = {
                "RELEASE": "RELEASED",
                "QUARANTINE": "QUARANTINED",
                "REJECT": "REJECTED",
            }
            target_status = target_status_map[decision]
            for L in store.lots.values():
                bin_id = L.get("bin_id")
                if not bin_id:
                    continue
                b = store.bins.get(bin_id)
                if not b or b.get("zone_id") != zone_id:
                    continue
                if L.get("quality_status") != target_status:
                    L["quality_status"] = target_status
                    bump_version(L)

            dev["qa_decision"] = decision
            dev["status"] = "CLOSED_ASSESSED"
            # If MAJOR/CRITICAL: open a CAPA (unless one was already provided).
            if classification in ("MAJOR", "CRITICAL"):
                if capa_id is None:
                    # Auto-open a new OPEN CAPA.
                    due_offset = 720 if classification == "CRITICAL" else 4320
                    capa = common_fields_create()
                    capa.update(
                        {
                            "warehouse_id": dev["warehouse_id"],
                            "deviation_id": dev["id"],
                            "recall_id": None,
                            "due_minutes": clock + due_offset,
                            "status": "OPEN",
                        }
                    )
                    store.capas[capa["id"]] = capa
                    dev["capa_id"] = capa["id"]
                else:
                    dev["capa_id"] = capa_id
            bump_version(dev)

            actor_user_id, _ = current_actor()
            store.deviation_assessed_by[dev["id"]] = actor_user_id

            write_audit(
                warehouse_id=dev["warehouse_id"],
                action="DEVIATION_ASSESS",
                target_id=dev["id"],
                at_minutes=clock,
            )
            # Recompute zone posture (now that this deviation is closed_assessed).
            recompute_zone_posture(zone_id)
        return ok(dev)
