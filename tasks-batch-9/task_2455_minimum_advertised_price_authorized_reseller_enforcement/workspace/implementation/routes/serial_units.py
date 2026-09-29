"""Serialized unit registration and downstream custody (PRD §3.8)."""

from flask import Blueprint

import lookup
from auth import (
    ROLE_BRAND_CHANNEL_MANAGER, ROLE_DISTRIBUTOR, STAFF_AND_DISTRIBUTOR,
    authenticate, require_owner,
)
from envelope import created, ok, ok_list
from errors import fail
from store import new_row, now_iso, serialize, store, touch
from validate import body, req_str

bp = Blueprint("serial_units", __name__)


@bp.post("/serial-units")
def register_unit():
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    b = body()
    serial_number = req_str(b, "serial_number", 1, 40)
    product_id = req_str(b, "product_id")
    lot_code = req_str(b, "lot_code", 1, 40)
    shipped_distributor_id = req_str(b, "shipped_distributor_id")

    product = lookup.product(product_id)
    distributor = lookup.distributor(shipped_distributor_id)
    if not product.get("serialization_enabled"):
        fail("ERR_PRODUCT_NOT_SERIALIZED",
             "Units may only be registered against a serialized product.")
    for existing in store.serial_units.values():
        if existing["serial_number"] == serial_number:
            fail("ERR_DUPLICATE_SERIAL", "serial_number must be unique across every unit.")

    row = new_row({
        "serial_number": serial_number,
        "product_id": product_id,
        "lot_code": lot_code,
        "shipped_distributor_id": shipped_distributor_id,
        "downstream_reseller_id": None,
        "status": "SHIPPED_TO_DISTRIBUTOR",
        "shipped_downstream_at": None,
        "traced_at": None,
    })
    store.serial_units[row["id"]] = row
    distributor["shipped_units_total"] = distributor["shipped_units_total"] + 1
    touch(distributor)
    return created(serialize(row))


@bp.post("/serial-units/<serial_unit_id>/ship-downstream")
def ship_downstream(serial_unit_id):
    ctx = authenticate([ROLE_DISTRIBUTOR])
    b = body()
    downstream_reseller_id = req_str(b, "downstream_reseller_id")
    unit = lookup.serial_unit(serial_unit_id)
    reseller = lookup.reseller(downstream_reseller_id)
    require_owner(ctx, unit, distributor_field="shipped_distributor_id")
    if unit["status"] != "SHIPPED_TO_DISTRIBUTOR":
        fail("ERR_INVALID_STATE", "Only a unit held by the distributor may be shipped downstream.")
    if reseller["supply_status"] != "OPEN":
        fail("ERR_INVALID_STATE", "Supply to the target reseller is not open.")

    unit["status"] = "SHIPPED_TO_RESELLER"
    unit["downstream_reseller_id"] = downstream_reseller_id
    unit["shipped_downstream_at"] = now_iso()
    touch(unit)
    return ok(serialize(unit))


@bp.get("/serial-units/<serial_unit_id>")
def read_unit(serial_unit_id):
    ctx = authenticate(STAFF_AND_DISTRIBUTOR)
    row = lookup.serial_unit(serial_unit_id)
    require_owner(ctx, row, distributor_field="shipped_distributor_id")
    return ok(serialize(row))


@bp.get("/serial-units")
def list_units():
    authenticate(STAFF_AND_DISTRIBUTOR)
    rows = lookup.filtered("serial_units", {
        "product_id": "product_id",
        "shipped_distributor_id": "shipped_distributor_id",
        "downstream_reseller_id": "downstream_reseller_id",
        "lot_code": "lot_code",
        "status": "status",
    })
    return ok_list(rows)
