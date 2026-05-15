"""Lot list/get routes."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_filter, parse_limit_offset
from ..response import paginate
from ..store import get_store
from ._helpers import list_ok, ok


_ALL_ROLES = ("Receiver", "QAOfficer", "Picker", "RecallOfficer", "WarehouseAdmin")


def register(app: Flask) -> None:
    @app.route("/warehouses/<wid>/lots", methods=["GET"])
    @require_auth(*_ALL_ROLES)
    def list_lots(wid: str):
        store = get_store()
        if wid not in store.warehouses:
            raise ApiError("ERR_NOT_FOUND", "Warehouse not found")
        limit, offset = parse_limit_offset()
        product_f = parse_filter("product_id")
        status_f = parse_filter("quality_status")
        items = [L for L in store.lots.values() if L["warehouse_id"] == wid]
        if product_f is not None:
            items = [L for L in items if L["product_id"] == product_f]
        if status_f is not None:
            items = [L for L in items if L["quality_status"] == status_f]
        items.sort(key=lambda L: L["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)

    @app.route("/lots/<lid>", methods=["GET"])
    @require_auth(*_ALL_ROLES)
    def get_lot(lid: str):
        L = get_store().lots.get(lid)
        if not L:
            raise ApiError("ERR_NOT_FOUND", "Lot not found")
        return ok(L)
