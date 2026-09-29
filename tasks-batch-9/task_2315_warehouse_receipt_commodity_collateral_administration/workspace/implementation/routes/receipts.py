"""Warehouse receipts: issuance, transfer and void (§3.4)."""

from datetime import timedelta

from flask import Blueprint

import calc
import model
from core import (authenticate, body, dec, fail, new_row, now, now_iso, opt_str,
                  req_enum, req_int, req_str, respond_object, rhu, store, touch)
from listing import list_response

bp = Blueprint("receipts", __name__)

READ_ROLES = ("StateRegulator", "WarehouseOperator", "RegistryAdministrator",
              "Depositor", "Lender")
FORMS = ("NEGOTIABLE", "NON_NEGOTIABLE")
MEDIA = ("PAPER", "ELECTRONIC")
CHANNELS = ("ENDORSEMENT", "REGISTRY")
VOID_WINDOW = timedelta(hours=calc.RECEIPT_VOID_WINDOW_HOURS)


@bp.post("/receipts")
def issue_receipt():
    caller = authenticate(("WarehouseOperator",))
    data = body()
    ticket_id = req_str(data, "deposit_ticket_id")
    holder_id = req_str(data, "holder_party_id")
    receipt_number = req_str(data, "receipt_number")
    form = req_enum(data, "form", FORMS)
    medium = req_enum(data, "medium", MEDIA)
    expected = req_int(data, "expected_warehouse_version")

    ticket = model.get_ticket(ticket_id)
    agreement = model.ticket_agreement(ticket)
    warehouse_id = agreement["warehouse_id"]
    if caller.user_id != warehouse_id:
        model.not_owner()
    warehouse = store.warehouses[warehouse_id]
    model.get_party(holder_id)

    if expected != warehouse["version"]:
        fail("ERR_STALE_WAREHOUSE_VERSION", 412)

    if ticket["ticket_state"] != "ACCEPTED":
        fail("ERR_INVALID_STATE", 409)

    model.gate_licensed(warehouse)
    model.gate_solvent(warehouse)
    model.gate_not_restricted(warehouse)

    bin_row = store.bins[ticket["bin_id"]]
    model.gate_bin_condition(bin_row)

    if medium == "ELECTRONIC" and not warehouse["registry_participant"]:
        fail("ERR_REGISTRY_NOT_PARTICIPANT", 422)

    for existing in model.warehouse_receipts(warehouse_id):
        if existing["receipt_number"] == receipt_number:
            fail("ERR_RECEIPT_NUMBER_DUPLICATE", 409)

    quantity = ticket["net_bushels"]
    if (model.receipted_obligation_bushels(warehouse_id) + quantity
            > warehouse["licensed_capacity_bushels"]):
        fail("ERR_LICENSED_CAPACITY_EXCEEDED", 422)

    row = new_row()
    row.update({
        "warehouse_id": warehouse_id,
        "deposit_ticket_id": ticket_id,
        "storage_agreement_id": agreement["id"],
        "bin_id": ticket["bin_id"],
        "holder_party_id": holder_id,
        "registry_control_party_id": None,
        "receipt_number": receipt_number,
        "form": form,
        "medium": medium,
        "quantity_bushels": quantity,
        "grade": ticket["assigned_grade"],
        "moisture_pct": ticket["moisture_pct"],
        "face_price_cents_per_bushel": agreement["declared_value_cents_per_bushel"],
        "receiving_charge_cents": rhu(
            dec(quantity) * agreement["receiving_charge_cents_per_bushel"]),
        "issued_at": now_iso(),
        "_issued_at_dt": now(),
        "receipt_state": "ISSUED",
        "encumbrance_state": "UNENCUMBERED",
        "transfer_log": [],
    })
    store.receipts[row["id"]] = row

    ticket["ticket_state"] = "RECEIPTED"
    touch(ticket)
    touch(warehouse)

    return respond_object(model.receipt_out(row), 201)


@bp.get("/receipts")
def list_receipts():
    authenticate(READ_ROLES)
    return list_response(
        list(store.receipts.values()),
        ("warehouse_id", "deposit_ticket_id", "storage_agreement_id", "bin_id",
         "holder_party_id", "registry_control_party_id", "receipt_state",
         "encumbrance_state", "form", "medium"),
        model.receipt_out)


@bp.get("/receipts/<receipt_id>")
def read_receipt(receipt_id):
    caller = authenticate(READ_ROLES)
    receipt = model.get_receipt(receipt_id)
    model.require_operator_warehouse(caller, receipt["warehouse_id"])
    model.require_depositor_party(caller, receipt["holder_party_id"])
    return respond_object(model.receipt_out(receipt))


@bp.post("/receipts/<receipt_id>/transfer")
def transfer_receipt(receipt_id):
    caller = authenticate(("Depositor", "Lender", "RegistryAdministrator"))
    receipt = model.get_receipt(receipt_id)
    if (caller.role in ("Depositor", "Lender")
            and caller.user_id != receipt["holder_party_id"]):
        model.not_owner()

    data = body()
    raw_channel = data.get("transfer_channel")
    if not isinstance(raw_channel, str) or not raw_channel.strip():
        fail("ERR_VALIDATION", 422, "Field 'transfer_channel' is required.")

    if raw_channel == "ENDORSEMENT":
        if (receipt["medium"] != "PAPER"
                or caller.role not in ("Depositor", "Lender")):
            fail("ERR_TRANSFER_CHANNEL_INVALID", 403)
    elif raw_channel == "REGISTRY":
        if (receipt["medium"] != "ELECTRONIC"
                or caller.role != "RegistryAdministrator"):
            fail("ERR_TRANSFER_CHANNEL_INVALID", 403)
    else:
        fail("ERR_TRANSFER_CHANNEL_INVALID", 403)

    to_party_id = req_str(data, "to_party_id")
    to_party = model.get_party(to_party_id)

    if receipt["receipt_state"] != "ISSUED":
        fail("ERR_INVALID_STATE", 409)

    if receipt["form"] != "NEGOTIABLE":
        fail("ERR_RECEIPT_NOT_NEGOTIABLE", 422)
    warehouse = store.warehouses[receipt["warehouse_id"]]
    if raw_channel == "REGISTRY" and not warehouse["registry_participant"]:
        fail("ERR_REGISTRY_NOT_PARTICIPANT", 422)

    if receipt["encumbrance_state"] == "PLEDGED":
        fail("ERR_RECEIPT_ENCUMBERED", 409)

    from_party_id = receipt["holder_party_id"]
    receipt["holder_party_id"] = to_party["id"]
    receipt["transfer_log"] = receipt["transfer_log"] + [{
        "transfer_channel": raw_channel,
        "from_party_id": from_party_id,
        "to_party_id": to_party["id"],
        "effective_at": now_iso(),
    }]
    touch(receipt)
    return respond_object(model.receipt_out(receipt))


@bp.post("/receipts/<receipt_id>/void")
def void_receipt(receipt_id):
    caller = authenticate(("WarehouseOperator",))
    receipt = model.get_receipt(receipt_id)
    model.require_operator_warehouse(caller, receipt["warehouse_id"])
    data = body()
    opt_str(data, "void_reason")

    if receipt["receipt_state"] != "ISSUED":
        fail("ERR_INVALID_STATE", 409)
    for order in model.receipt_orders(receipt_id):
        if order["delivery_state"] in ("REQUESTED", "LOADED"):
            fail("ERR_INVALID_STATE", 409)

    if receipt["encumbrance_state"] == "PLEDGED":
        fail("ERR_RECEIPT_ENCUMBERED", 409)

    if now() - receipt["_issued_at_dt"] > VOID_WINDOW:
        fail("ERR_VOID_WINDOW_EXPIRED", 422)

    receipt["receipt_state"] = "VOIDED"
    receipt["quantity_bushels"] = 0
    touch(receipt)

    ticket = store.tickets.get(receipt["deposit_ticket_id"])
    if ticket is not None and ticket["ticket_state"] == "RECEIPTED":
        ticket["ticket_state"] = "ACCEPTED"
        touch(ticket)

    return respond_object(model.receipt_out(receipt))
