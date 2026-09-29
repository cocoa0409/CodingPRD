"""Deposit tickets: weigh-in, acceptance and rejection (§3.3)."""

from datetime import timedelta

from flask import Blueprint

import calc
import model
from core import (authenticate, body, fail, invalid, new_row, now, now_iso,
                  opt_str, req_datetime, req_int, req_number, req_str,
                  respond_object, store, touch)
from listing import list_response

bp = Blueprint("tickets", __name__)

READ_ROLES = ("StateRegulator", "WarehouseOperator", "Depositor", "Lender")
BUFFER = timedelta(minutes=calc.BIN_REST_BUFFER_MINUTES)


@bp.post("/deposit-tickets")
def create_ticket():
    caller = authenticate(("WarehouseOperator",))
    data = body()
    agreement_id = req_str(data, "storage_agreement_id")
    bin_id = req_str(data, "bin_id")
    gross = req_int(data, "gross_bushels", minimum=1)
    test_weight = req_number(data, "test_weight_lbs", minimum=0)
    moisture = req_number(data, "moisture_pct", minimum=0)
    damage = req_number(data, "damage_pct", minimum=0)
    foreign = req_number(data, "foreign_material_pct", minimum=0)
    dockage = req_number(data, "dockage_pct", minimum=0)
    fill_start = req_datetime(data, "fill_start_at")
    fill_end = req_datetime(data, "fill_end_at")
    if fill_end <= fill_start:
        invalid("fill_end_at", "must be strictly after fill_start_at")

    bin_row = model.get_bin(bin_id)
    agreement = model.get_agreement(agreement_id)
    warehouse_id = agreement["warehouse_id"]
    if caller.user_id != warehouse_id:
        model.not_owner()
    warehouse = model.get_warehouse(warehouse_id)

    if bin_row["warehouse_id"] != warehouse_id:
        fail("ERR_PARTY_KIND_INVALID", 422)
    if bin_row["commodity"] != agreement["commodity"]:
        fail("ERR_COMMODITY_MISMATCH", 422)

    if agreement["agreement_state"] != "ACTIVE":
        fail("ERR_INVALID_STATE", 409)

    model.gate_licensed(warehouse)
    model.gate_solvent(warehouse)
    model.gate_bin_condition(bin_row)

    if agreement["storage_kind"] == "IDENTITY_PRESERVED":
        if bin_row["commingling_allowed"]:
            fail("ERR_COMMINGLING_NOT_PERMITTED", 422)
        dedicated = bin_row["dedicated_agreement_id"]
        if dedicated is not None and dedicated != agreement_id:
            fail("ERR_COMMINGLING_NOT_PERMITTED", 422)
    else:
        if not bin_row["commingling_allowed"]:
            fail("ERR_COMMINGLING_NOT_PERMITTED", 422)
        dedicated = bin_row["dedicated_agreement_id"]
        if dedicated is not None and dedicated != agreement_id:
            fail("ERR_COMMINGLING_NOT_PERMITTED", 422)

    for other in model.bin_tickets(bin_id):
        if other["ticket_state"] not in ("WEIGHED", "ACCEPTED"):
            continue
        if (fill_start <= other["_fill_end_dt"] + BUFFER
                and other["_fill_start_dt"] <= fill_end + BUFFER):
            fail("ERR_BIN_WINDOW_CONFLICT", 409)

    quantities = calc.deposit_quantities(
        gross, dockage, moisture, agreement["max_moisture_pct"],
        agreement["storage_kind"])

    if model.bin_headroom(bin_row) < quantities["net_bushels"]:
        fail("ERR_BIN_CAPACITY_EXCEEDED", 422)

    row = new_row()
    row.update({
        "storage_agreement_id": agreement_id,
        "bin_id": bin_id,
        "gross_bushels": gross,
        "test_weight_lbs": test_weight,
        "moisture_pct": moisture,
        "damage_pct": damage,
        "foreign_material_pct": foreign,
        "dockage_pct": dockage,
        "fill_start_at": data["fill_start_at"],
        "fill_end_at": data["fill_end_at"],
        "_fill_start_dt": fill_start,
        "_fill_end_dt": fill_end,
        "assigned_grade": calc.assign_grade(test_weight, damage, foreign),
        "settlement_variant": agreement["storage_kind"],
        "ticket_state": "WEIGHED",
        "rejection_reason": None,
        "accepted_at": None,
    })
    row.update(quantities)
    store.tickets[row["id"]] = row
    return respond_object(model.ticket_out(row), 201)


@bp.get("/deposit-tickets")
def list_tickets():
    authenticate(READ_ROLES)
    return list_response(list(store.tickets.values()),
                         ("storage_agreement_id", "bin_id", "ticket_state"),
                         model.ticket_out)


@bp.get("/deposit-tickets/<ticket_id>")
def read_ticket(ticket_id):
    caller = authenticate(READ_ROLES)
    ticket = model.get_ticket(ticket_id)
    model.require_operator_warehouse(caller, model.ticket_warehouse_id(ticket))
    return respond_object(model.ticket_out(ticket))


@bp.post("/deposit-tickets/<ticket_id>/accept")
def accept_ticket(ticket_id):
    caller = authenticate(("WarehouseOperator",))
    ticket = model.get_ticket(ticket_id)
    agreement = model.ticket_agreement(ticket)
    warehouse_id = agreement["warehouse_id"]
    if caller.user_id != warehouse_id:
        model.not_owner()
    data = body()
    expected = req_int(data, "expected_bin_version")

    warehouse = store.warehouses[warehouse_id]
    bin_row = store.bins[ticket["bin_id"]]

    if expected != bin_row["version"]:
        fail("ERR_STALE_BIN_VERSION", 412)
    if ticket["ticket_state"] != "WEIGHED":
        fail("ERR_INVALID_STATE", 409)

    model.gate_licensed(warehouse)
    model.gate_solvent(warehouse)
    model.gate_not_restricted(warehouse)
    model.gate_bin_condition(bin_row)

    if (calc.GRADE_RANK[ticket["assigned_grade"]]
            > calc.GRADE_RANK[agreement["min_grade"]]):
        fail("ERR_GRADE_BELOW_MINIMUM", 422)

    if model.bin_headroom(bin_row, exclude_ticket_id=ticket_id) < ticket["net_bushels"]:
        fail("ERR_BIN_CAPACITY_EXCEEDED", 422)

    ticket["ticket_state"] = "ACCEPTED"
    ticket["accepted_at"] = now_iso()
    touch(ticket)

    bin_row["stored_bushels"] = bin_row["stored_bushels"] + ticket["net_bushels"]
    bin_row["cumulative_shrink_bushels"] = (
        bin_row["cumulative_shrink_bushels"] + ticket["shrink_bushels"])
    if (agreement["storage_kind"] == "IDENTITY_PRESERVED"
            and bin_row["dedicated_agreement_id"] is None):
        bin_row["dedicated_agreement_id"] = agreement["id"]
    touch(bin_row)

    return respond_object(model.ticket_out(ticket))


@bp.post("/deposit-tickets/<ticket_id>/reject")
def reject_ticket(ticket_id):
    caller = authenticate(("WarehouseOperator",))
    ticket = model.get_ticket(ticket_id)
    model.require_operator_warehouse(caller, model.ticket_warehouse_id(ticket))
    data = body()
    reason = opt_str(data, "rejection_reason", default="OPERATOR_REJECTED")

    if ticket["ticket_state"] != "WEIGHED":
        fail("ERR_INVALID_STATE", 409)

    ticket["ticket_state"] = "REJECTED"
    ticket["rejection_reason"] = reason
    touch(ticket)
    return respond_object(model.ticket_out(ticket))
