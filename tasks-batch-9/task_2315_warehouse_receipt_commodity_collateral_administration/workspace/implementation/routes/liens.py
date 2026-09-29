"""Collateral liens: request valuation, perfection, revaluation, release
(§3.6).
"""

from flask import Blueprint

import calc
import model
from core import (authenticate, body, fail, new_row, now_iso, opt_str,
                  req_enum, req_int, req_str, respond_object, store, touch)
from listing import list_response

bp = Blueprint("liens", __name__)

READ_ROLES = ("StateRegulator", "WarehouseOperator", "RegistryAdministrator",
              "Depositor", "Lender")
BASES = ("MARK_TO_MARKET", "FACE_ADVANCE")
METHODS = ("POSSESSION", "ELECTRONIC_CONTROL")


@bp.post("/collateral-liens")
def create_lien():
    caller = authenticate(("Lender",))
    data = body()
    receipt_id = req_str(data, "receipt_id")
    lender_id = req_str(data, "lender_party_id")
    principal = req_int(data, "principal_cents", minimum=1)
    basis = req_enum(data, "valuation_basis", BASES)
    mark_price = req_int(data, "mark_price_cents_per_bushel", minimum=1)
    method = req_enum(data, "perfection_method", METHODS)

    receipt = model.get_receipt(receipt_id)
    if lender_id != caller.user_id:
        model.not_owner()
    lender = model.get_party(lender_id)
    if lender["party_kind"] != "LENDER":
        fail("ERR_PARTY_KIND_INVALID", 422)

    if receipt["receipt_state"] != "ISSUED":
        fail("ERR_INVALID_STATE", 409)
    if receipt["form"] != "NEGOTIABLE":
        fail("ERR_RECEIPT_NOT_NEGOTIABLE", 422)
    if receipt["encumbrance_state"] == "PLEDGED":
        fail("ERR_RECEIPT_ENCUMBERED", 409)

    row = new_row()
    row.update({
        "receipt_id": receipt_id,
        "lender_party_id": lender_id,
        "pledgor_party_id": receipt["holder_party_id"],
        "principal_cents": principal,
        "valuation_basis": basis,
        "mark_price_cents_per_bushel": mark_price,
        "perfection_method": method,
        "lien_state": "REQUESTED",
        "perfected_at": None,
        "released_at": None,
        "payoff_received_cents": None,
    })
    row.update(model.revalue_lien(row))
    store.liens[row["id"]] = row
    return respond_object(model.lien_out(row), 201)


@bp.get("/collateral-liens")
def list_liens():
    authenticate(READ_ROLES)
    return list_response(
        list(store.liens.values()),
        ("receipt_id", "lender_party_id", "pledgor_party_id", "lien_state",
         "valuation_basis", "margin_status"),
        model.lien_out)


def _require_lender(caller, lien):
    if caller.role == "Lender" and caller.user_id != lien["lender_party_id"]:
        model.not_owner()


@bp.get("/collateral-liens/<lien_id>")
def read_lien(lien_id):
    caller = authenticate(READ_ROLES)
    lien = model.get_lien(lien_id)
    _require_lender(caller, lien)
    return respond_object(model.lien_out(lien))


@bp.post("/collateral-liens/<lien_id>/perfect")
def perfect_lien(lien_id):
    caller = authenticate(("Lender",))
    lien = model.get_lien(lien_id)
    _require_lender(caller, lien)
    data = body()
    opt_str(data, "attestation_note")

    receipt = model.lien_receipt(lien)
    warehouse = store.warehouses[receipt["warehouse_id"]]

    if lien["lien_state"] != "REQUESTED":
        fail("ERR_INVALID_STATE", 409)
    if receipt["receipt_state"] != "ISSUED":
        fail("ERR_INVALID_STATE", 409)

    model.gate_licensed(warehouse)
    model.gate_solvent(warehouse)
    model.gate_not_restricted(warehouse)

    if receipt["form"] != "NEGOTIABLE":
        fail("ERR_RECEIPT_NOT_NEGOTIABLE", 422)
    if (lien["perfection_method"] == "ELECTRONIC_CONTROL"
            and receipt["medium"] == "ELECTRONIC"
            and not warehouse["registry_participant"]):
        fail("ERR_REGISTRY_NOT_PARTICIPANT", 422)
    if lien["perfection_method"] == "POSSESSION" and receipt["medium"] != "PAPER":
        fail("ERR_PERFECTION_METHOD_MISMATCH", 422)
    if (lien["perfection_method"] == "ELECTRONIC_CONTROL"
            and receipt["medium"] != "ELECTRONIC"):
        fail("ERR_PERFECTION_METHOD_MISMATCH", 422)

    if receipt["encumbrance_state"] == "PLEDGED":
        fail("ERR_RECEIPT_ENCUMBERED", 409)
    for other in model.receipt_liens(receipt["id"]):
        if other["id"] != lien_id and other["lien_state"] == "PERFECTED":
            fail("ERR_RECEIPT_ENCUMBERED", 409)

    lender = store.parties[lien["lender_party_id"]]
    valuation = model.revalue_lien(lien)
    if model.available_credit_cents(lender) < valuation["advance_limit_cents"]:
        fail("ERR_CREDIT_LINE_EXCEEDED", 422)

    lien["lien_state"] = "PERFECTED"
    lien["perfected_at"] = now_iso()
    touch(lien)

    receipt["encumbrance_state"] = "PLEDGED"
    if lien["perfection_method"] == "POSSESSION":
        receipt["holder_party_id"] = lien["lender_party_id"]
        receipt["registry_control_party_id"] = None
    else:
        receipt["registry_control_party_id"] = lien["lender_party_id"]
    touch(receipt)
    touch(lender)

    return respond_object(model.lien_out(lien))


@bp.post("/collateral-liens/<lien_id>/release")
def release_lien(lien_id):
    caller = authenticate(("Lender",))
    lien = model.get_lien(lien_id)
    _require_lender(caller, lien)
    data = body()
    payoff = req_int(data, "payoff_received_cents", minimum=0)

    state = lien["lien_state"]
    if state not in ("REQUESTED", "PERFECTED"):
        fail("ERR_INVALID_STATE", 409)

    lender = store.parties.get(lien["lender_party_id"])
    if state == "REQUESTED":
        lien["payoff_received_cents"] = 0
        lien["lien_state"] = "RELEASED"
        lien["released_at"] = now_iso()
        touch(lien)
        return respond_object(model.lien_out(lien))

    lien["payoff_received_cents"] = payoff
    lien["lien_state"] = "RELEASED"
    lien["released_at"] = now_iso()
    touch(lien)

    receipt = model.lien_receipt(lien)
    receipt["encumbrance_state"] = "RELEASED"
    receipt["holder_party_id"] = lien["pledgor_party_id"]
    receipt["registry_control_party_id"] = None
    touch(receipt)
    if lender is not None:
        touch(lender)

    return respond_object(model.lien_out(lien))


@bp.post("/collateral-liens/<lien_id>/revalue")
def revalue(lien_id):
    caller = authenticate(("Lender",))
    lien = model.get_lien(lien_id)
    _require_lender(caller, lien)
    data = body()
    mark_price = req_int(data, "mark_price_cents_per_bushel", minimum=1)

    if lien["lien_state"] not in ("REQUESTED", "PERFECTED"):
        fail("ERR_INVALID_STATE", 409)

    lien["mark_price_cents_per_bushel"] = mark_price
    model.revalue_lien(lien)
    touch(lien)
    if lien["lien_state"] == "PERFECTED":
        lender = store.parties.get(lien["lender_party_id"])
        if lender is not None:
            touch(lender)
    return respond_object(model.lien_out(lien))
