"""Storage agreements: opening, reads and termination (§3.2)."""

from flask import Blueprint

import calc
import model
from core import (authenticate, body, fail, new_row, num_out, req_enum,
                  req_int, req_number, req_str, respond_object, store, touch)
from listing import list_response

bp = Blueprint("agreements", __name__)

READ_ROLES = ("StateRegulator", "WarehouseOperator", "Depositor", "Lender")
COMMODITIES = ("CORN", "SOYBEANS", "WHEAT")
STORAGE_KINDS = ("COMMINGLED", "IDENTITY_PRESERVED")


@bp.post("/storage-agreements")
def create_agreement():
    caller = authenticate(("WarehouseOperator",))
    data = body()

    raw_warehouse = data.get("warehouse_id")
    if isinstance(raw_warehouse, str) and raw_warehouse != caller.user_id:
        model.not_owner()

    warehouse_id = req_str(data, "warehouse_id")
    depositor_id = req_str(data, "depositor_party_id")
    commodity = req_enum(data, "commodity", COMMODITIES)
    storage_kind = req_enum(data, "storage_kind", STORAGE_KINDS)
    min_grade = req_enum(data, "min_grade", calc.GRADES)
    max_moisture = req_number(data, "max_moisture_pct", minimum=0)
    storage_rate = req_int(data, "storage_rate_millicents_per_bushel_day",
                           minimum=0)
    receiving_charge = req_int(data, "receiving_charge_cents_per_bushel",
                              minimum=0)
    loadout_charge = req_int(data, "loadout_charge_cents_per_bushel", minimum=0)
    free_days = req_int(data, "free_storage_days", minimum=0)
    declared_value = req_int(data, "declared_value_cents_per_bushel", minimum=1)

    model.get_warehouse(warehouse_id)
    if warehouse_id != caller.user_id:
        model.not_owner()
    depositor = model.get_party(depositor_id)
    if depositor["party_kind"] not in ("PRODUCER_DEPOSITOR",
                                      "COMMERCIAL_DEPOSITOR"):
        fail("ERR_PARTY_KIND_INVALID", 422)

    row = new_row()
    row.update({
        "warehouse_id": warehouse_id,
        "depositor_party_id": depositor_id,
        "commodity": commodity,
        "storage_kind": storage_kind,
        "min_grade": min_grade,
        "max_moisture_pct": max_moisture,
        "storage_rate_millicents_per_bushel_day": storage_rate,
        "receiving_charge_cents_per_bushel": receiving_charge,
        "loadout_charge_cents_per_bushel": loadout_charge,
        "free_storage_days": free_days,
        "declared_value_cents_per_bushel": declared_value,
        "agreement_state": "ACTIVE",
        "termination_reason": None,
    })
    store.agreements[row["id"]] = row
    return respond_object(model.agreement_out(row), 201)


@bp.get("/storage-agreements")
def list_agreements():
    authenticate(READ_ROLES)
    return list_response(
        list(store.agreements.values()),
        ("warehouse_id", "depositor_party_id", "agreement_state",
         "storage_kind"),
        model.agreement_out)


@bp.get("/storage-agreements/<agreement_id>")
def read_agreement(agreement_id):
    caller = authenticate(READ_ROLES)
    agreement = model.get_agreement(agreement_id)
    model.require_operator_warehouse(caller, agreement["warehouse_id"])
    model.require_depositor_party(caller, agreement["depositor_party_id"])
    return respond_object(model.agreement_out(agreement))


@bp.post("/storage-agreements/<agreement_id>/terminate")
def terminate_agreement(agreement_id):
    caller = authenticate(("WarehouseOperator",))
    agreement = model.get_agreement(agreement_id)
    model.require_operator_warehouse(caller, agreement["warehouse_id"])
    data = body()
    reason = req_str(data, "termination_reason")

    if agreement["agreement_state"] != "ACTIVE":
        fail("ERR_INVALID_STATE", 409)
    for receipt in model.agreement_receipts(agreement_id):
        if receipt["receipt_state"] == "ISSUED":
            fail("ERR_INVALID_STATE", 409)
    for ticket in model.agreement_tickets(agreement_id):
        if ticket["ticket_state"] in ("WEIGHED", "ACCEPTED"):
            fail("ERR_INVALID_STATE", 409)

    agreement["agreement_state"] = "TERMINATED"
    agreement["termination_reason"] = reason
    touch(agreement)
    for bin_row in store.bins.values():
        if bin_row["dedicated_agreement_id"] == agreement_id:
            bin_row["dedicated_agreement_id"] = None
            touch(bin_row)
    return respond_object(model.agreement_out(agreement))
