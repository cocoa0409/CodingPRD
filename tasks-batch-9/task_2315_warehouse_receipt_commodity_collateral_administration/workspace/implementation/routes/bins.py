"""Bins: creation, reads and the condition assessment with its three-hop
impairment cascade (§3.2, §3.5).
"""

from flask import Blueprint

import calc
import model
from core import (authenticate, body, invalid, new_row, now, now_iso, opt_enum,
                  opt_str, req_bool, req_enum, req_int, req_number, req_str,
                  respond_object, store, touch)
from listing import list_response

bp = Blueprint("bins", __name__)

READ_ROLES = ("StateRegulator", "WarehouseOperator", "Depositor", "Lender")
COMMODITIES = ("CORN", "SOYBEANS", "WHEAT")


@bp.post("/bins")
def create_bin():
    caller = authenticate(("WarehouseOperator",))
    data = body()

    raw_warehouse = data.get("warehouse_id")
    if isinstance(raw_warehouse, str) and raw_warehouse != caller.user_id:
        model.not_owner()

    warehouse_id = req_str(data, "warehouse_id")
    bin_code = req_str(data, "bin_code")
    capacity = req_int(data, "capacity_bushels", minimum=1)
    commodity = req_enum(data, "commodity", COMMODITIES)
    commingling = req_bool(data, "commingling_allowed")
    dedicated = opt_str(data, "dedicated_agreement_id")

    model.get_warehouse(warehouse_id)
    if warehouse_id != caller.user_id:
        model.not_owner()
    if dedicated is not None:
        model.get_agreement(dedicated)

    for existing in store.bins.values():
        if (existing["warehouse_id"] == warehouse_id
                and existing["bin_code"] == bin_code):
            invalid("bin_code", "is already used at this warehouse")

    row = new_row()
    row.update({
        "warehouse_id": warehouse_id,
        "bin_code": bin_code,
        "capacity_bushels": capacity,
        "commodity": commodity,
        "commingling_allowed": commingling,
        "dedicated_agreement_id": dedicated,
        "stored_bushels": 0,
        "cumulative_shrink_bushels": 0,
        "condition_state": "SOUND",
        "last_moisture_pct": None,
        "last_temperature_f": None,
        "last_treatment_action": None,
        "last_assessed_at": None,
    })
    store.bins[row["id"]] = row
    return respond_object(model.bin_out(row), 201)


@bp.get("/bins")
def list_bins():
    authenticate(READ_ROLES)
    return list_response(
        list(store.bins.values()),
        ("warehouse_id", "dedicated_agreement_id", "condition_state",
         "commodity"),
        model.bin_out)


@bp.get("/bins/<bin_id>")
def read_bin(bin_id):
    caller = authenticate(READ_ROLES)
    bin_row = model.get_bin(bin_id)
    model.require_operator_warehouse(caller, bin_row["warehouse_id"])
    return respond_object(model.bin_out(bin_row))


@bp.post("/bins/<bin_id>/condition-assessment")
def condition_assessment(bin_id):
    caller = authenticate(("WarehouseOperator",))
    bin_row = model.get_bin(bin_id)
    model.require_operator_warehouse(caller, bin_row["warehouse_id"])
    data = body()
    moisture = req_number(data, "moisture_pct", minimum=0)
    temperature = req_number(data, "temperature_f")
    action = opt_enum(data, "treatment_action", calc.TREATMENT_ACTIONS,
                      default="NONE")

    previous = bin_row["condition_state"]
    target = calc.derive_condition(moisture, temperature)

    if action == "BLEND_OUT":
        loss = calc.blend_loss(bin_row["stored_bushels"])
        bin_row["stored_bushels"] = bin_row["stored_bushels"] - loss
        bin_row["cumulative_shrink_bushels"] = (
            bin_row["cumulative_shrink_bushels"] + loss)

    bin_row["last_moisture_pct"] = moisture
    bin_row["last_temperature_f"] = temperature
    bin_row["last_treatment_action"] = action
    bin_row["last_assessed_at"] = now_iso()
    bin_row["condition_state"] = target
    touch(bin_row)

    entering = previous != "OUT_OF_CONDITION" and target == "OUT_OF_CONDITION"
    leaving = previous == "OUT_OF_CONDITION" and target != "OUT_OF_CONDITION"
    if entering or leaving:
        model.cascade_impairment(bin_row)

    return respond_object(model.bin_out(bin_row))
