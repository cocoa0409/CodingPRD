"""ConsumableSku routes."""
from __future__ import annotations

import re

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..pagination import parse_limit_offset, parse_optional_str
from ..response import paginate
from ..services.validation import require_keys, require_str
from ..store import LOCK, common_fields_create, get_store
from ._helpers import created, get_json_body, list_ok


_SKU_CODE_RE = re.compile(r"^[A-Z0-9-]{3,32}$")
_KINDS = {"CONSUMABLE", "DRUG"}


def register(app: Flask) -> None:
    @app.route("/aesthetics/consumable-skus", methods=["POST"])
    @require_auth("MedicalDirector")
    def create_sku():
        body = get_json_body()
        require_keys(body, ["sku_code", "name", "kind"])
        code = require_str(body["sku_code"], "sku_code")
        if not _SKU_CODE_RE.match(code):
            raise ApiError("ERR_INVALID_INPUT", "sku_code must match [A-Z0-9-]{3,32}")
        for s in get_store().consumable_skus.values():
            if s["sku_code"] == code:
                raise ApiError("ERR_INVALID_INPUT", f"sku_code already exists: {code}")
        kind = body["kind"]
        if kind not in _KINDS:
            raise ApiError("ERR_INVALID_INPUT", "kind must be CONSUMABLE or DRUG")
        rlt = body.get("requires_lot_tracking", True)
        if not isinstance(rlt, bool):
            raise ApiError("ERR_INVALID_INPUT", "requires_lot_tracking must be boolean")
        with LOCK:
            sku = common_fields_create()
            sku.update({
                "sku_code": code,
                "name": require_str(body["name"], "name"),
                "kind": kind,
                "requires_lot_tracking": rlt,
            })
            get_store().consumable_skus[sku["id"]] = sku
        return created(sku)

    @app.route("/aesthetics/consumable-skus", methods=["GET"])
    @require_auth("MedicalDirector", "Consultant", "AttendingPhysician", "Nurse")
    def list_skus():
        limit, offset = parse_limit_offset()
        kind = parse_optional_str("kind")
        items = list(get_store().consumable_skus.values())
        if kind:
            items = [s for s in items if s["kind"] == kind]
        items.sort(key=lambda x: x["created_at"])
        sliced, page = paginate(items, limit, offset)
        return list_ok(sliced, page)
