"""CAPA routes — list/get/complete."""
from __future__ import annotations

from flask import Flask

from ..audit import write_audit
from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_filter, parse_limit_offset
from ..response import paginate
from ..services.validation import check_occ
from ..store import LOCK, bump_version, get_store
from ._helpers import get_json_body, list_ok, ok


def register(app: Flask) -> None:
    @app.route("/warehouses/<wid>/capas", methods=["GET"])
    @require_auth("QAOfficer", "RecallOfficer", "WarehouseAdmin")
    def list_capas(wid: str):
        store = get_store()
        if wid not in store.warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        limit, offset = parse_limit_offset()
        status_f = parse_filter("status")
        items = [c for c in store.capas.values() if c["warehouse_id"] == wid]
        if status_f is not None:
            items = [c for c in items if c["status"] == status_f]
        items.sort(key=lambda c: c["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)

    @app.route("/capas/<cid>", methods=["GET"])
    @require_auth("QAOfficer", "RecallOfficer", "WarehouseAdmin")
    def get_capa(cid: str):
        c = get_store().capas.get(cid)
        if not c:
            raise ApiError("ERR_NOT_FOUND", "CAPA not found")
        return ok(c)

    @app.route("/capas/<cid>/complete", methods=["POST"])
    @require_auth("QAOfficer")
    def complete_capa(cid: str):
        body = get_json_body()
        store = get_store()
        with LOCK:
            c = store.capas.get(cid)
            if not c:
                raise ApiError("ERR_NOT_FOUND", "CAPA not found")
            if c["status"] not in ("OPEN", "IN_PROGRESS"):
                raise ApiError("ERR_CAPA_STATE_INVALID", "CAPA not in OPEN/IN_PROGRESS")
            check_occ(c, body)
            warehouse = store.warehouses[c["warehouse_id"]]
            c["status"] = "COMPLETED"
            bump_version(c)
            write_audit(
                warehouse_id=c["warehouse_id"],
                action="CAPA_COMPLETE",
                target_id=c["id"],
                at_minutes=int(warehouse["clock_minutes"]),
            )
        return ok(c)
