"""Suppliers and products master-data routes."""
from __future__ import annotations

from flask import Flask

from ..auth import require_auth
from ..errors import ApiError
from ..services.validation import (
    require_bool,
    require_enum,
    require_int,
    require_keys,
    require_number,
    require_str,
)
from ..store import LOCK, common_fields_create, get_store
from ._helpers import created, get_json_body, ok


_PRODUCT_ZONE_TYPES = {"FROZEN", "REFRIGERATED", "COOL", "ROOM_TEMP", "CONTROLLED_TEMP"}
_TAGS = {"NONE", "NARCOTIC", "PSYCHOTROPIC", "BIOLOGICAL", "VACCINE"}


def register(app: Flask) -> None:
    # Suppliers ----------------------------------------------------------
    @app.route("/suppliers", methods=["POST"])
    @require_auth("WarehouseAdmin")
    def create_supplier():
        body = get_json_body()
        require_keys(body, ["name", "qualification_expiry_minutes"])
        qualified = body.get("qualified", True)
        if not isinstance(qualified, bool):
            raise ApiError("ERR_VALIDATION_FAILED", "qualified must be boolean")
        with LOCK:
            s = common_fields_create()
            s.update(
                {
                    "name": require_str(body["name"], "name"),
                    "qualified": qualified,
                    "qualification_expiry_minutes": require_int(
                        body["qualification_expiry_minutes"],
                        "qualification_expiry_minutes",
                        allow_zero=True,
                    ),
                }
            )
            get_store().suppliers[s["id"]] = s
        return created(s)

    @app.route("/suppliers/<sid>", methods=["GET"])
    @require_auth("WarehouseAdmin", "Receiver", "QAOfficer")
    def get_supplier(sid: str):
        s = get_store().suppliers.get(sid)
        if not s:
            raise ApiError("ERR_NOT_FOUND", "Supplier not found")
        return ok(s)

    # Products -----------------------------------------------------------
    @app.route("/products", methods=["POST"])
    @require_auth("WarehouseAdmin")
    def create_product():
        body = get_json_body()
        require_keys(
            body,
            [
                "sku",
                "name",
                "required_zone_type",
                "unit_weight_kg",
                "stability_budget_minutes",
            ],
        )
        tag = body.get("special_storage_tag", "NONE") or "NONE"
        tag = require_enum(tag, "special_storage_tag", _TAGS)
        qualified = body.get("qualified", True)
        if not isinstance(qualified, bool):
            raise ApiError("ERR_VALIDATION_FAILED", "qualified must be boolean")
        with LOCK:
            p = common_fields_create()
            p.update(
                {
                    "sku": require_str(body["sku"], "sku"),
                    "name": require_str(body["name"], "name"),
                    "required_zone_type": require_enum(
                        body["required_zone_type"],
                        "required_zone_type",
                        _PRODUCT_ZONE_TYPES,
                    ),
                    "special_storage_tag": tag,
                    "qualified": qualified,
                    "unit_weight_kg": require_number(body["unit_weight_kg"], "unit_weight_kg"),
                    "stability_budget_minutes": require_int(
                        body["stability_budget_minutes"],
                        "stability_budget_minutes",
                        allow_zero=True,
                    ),
                }
            )
            get_store().products[p["id"]] = p
        return created(p)

    @app.route("/products/<pid>", methods=["GET"])
    @require_auth("WarehouseAdmin", "Receiver", "QAOfficer", "Picker")
    def get_product(pid: str):
        p = get_store().products.get(pid)
        if not p:
            raise ApiError("ERR_NOT_FOUND", "Product not found")
        return ok(p)
