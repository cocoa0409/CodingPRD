"""Inventory singleton endpoints (PRD §2.8, §3.2, §2.12, §3.8)."""

from flask import request

from db import store, base_fields, touch, SIZE_CODES
from errors import (ERR_NOT_FOUND, ERR_VALIDATION, ERR_STALE_VERSION, raise_err)
from middleware import authenticate, require_role
from response import success_object, get_body
from serialize import inventory_json
from services.calc import forecast_report
from validate import req_size_code
from . import make_blueprint

bp = make_blueprint("inventory")

READ_ROLES = ["WarehouseManager", "BankAdmin", "FinanceManager"]


def _inventory_or_404():
    inv = store.inventory
    if inv is None or not inv["initialized"]:
        raise_err(ERR_NOT_FOUND, "Inventory has not been initialized.")
    return inv


@bp.route("/inventory/initialize", methods=["POST"])
def initialize_inventory():
    _, role = authenticate()
    require_role(role, ["WarehouseManager"])
    body = get_body()
    # The singleton exists exactly once; a second attempt is ERR_VALIDATION.
    if store.inventory is not None and store.inventory["initialized"]:
        raise_err(ERR_VALIDATION, "Inventory has already been initialized.")
    thresholds = body.get("thresholds")
    if thresholds is None:
        thresholds = {}
    if not isinstance(thresholds, dict):
        raise_err(ERR_VALIDATION, "thresholds must be an object keyed by size code.")
    for code, val in thresholds.items():
        req_size_code(code, "thresholds key")
        if not isinstance(val, int) or isinstance(val, bool) or val < 0:
            raise_err(ERR_VALIDATION,
                      "thresholds values must be non-negative integers.")
    inv = store.inventory if store.inventory is not None else base_fields()
    sizes = {}
    for code in SIZE_CODES:
        sizes[code] = {
            "on_hand_units": 0,
            "reserved_units": 0,
            "reorder_threshold_units": thresholds.get(code, 0),
        }
    inv["sizes"] = sizes
    inv["initialized"] = True
    store.inventory = inv
    return success_object(inventory_json(inv), status=201)


@bp.route("/inventory", methods=["GET"])
def get_inventory():
    _, role = authenticate()
    require_role(role, READ_ROLES)
    return success_object(inventory_json(_inventory_or_404()))


@bp.route("/inventory/adjustments", methods=["POST"])
def adjust_inventory():
    _, role = authenticate()
    require_role(role, ["WarehouseManager"])
    inv = _inventory_or_404()
    body = get_body()
    # OCC (state category): expected_inventory_version is non-optional and
    # must equal the current Inventory.version (PRD §2.12).
    expected = body.get("expected_inventory_version")
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise_err(ERR_VALIDATION,
                  "expected_inventory_version is required and must be an integer.")
    if expected != inv["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_inventory_version does not match the current "
                  "Inventory version; re-read and recompute the adjustment.")
    size = req_size_code(body.get("size_code"))
    new_on_hand = body.get("new_on_hand_units")
    if (not isinstance(new_on_hand, int) or isinstance(new_on_hand, bool)
            or new_on_hand < 0):
        raise_err(ERR_VALIDATION,
                  "new_on_hand_units must be a non-negative integer.")
    reason = body.get("reason")
    if not isinstance(reason, str) or reason == "":
        raise_err(ERR_VALIDATION, "reason is required and must be a string.")
    inv["sizes"][size]["on_hand_units"] = new_on_hand
    touch(inv)
    return success_object(inventory_json(inv))


@bp.route("/inventory/forecast", methods=["GET"])
def get_forecast():
    _, role = authenticate()
    require_role(role, ["WarehouseManager", "BankAdmin"])
    _inventory_or_404()
    variant = request.args.get("variant")
    if variant is None:
        variant = "TRAILING_ACTUAL"
    if variant not in ("TRAILING_ACTUAL", "BOOKED_PIPELINE"):
        raise_err(ERR_VALIDATION, "variant must be TRAILING_ACTUAL or BOOKED_PIPELINE.")
    return success_object(forecast_report(variant))
