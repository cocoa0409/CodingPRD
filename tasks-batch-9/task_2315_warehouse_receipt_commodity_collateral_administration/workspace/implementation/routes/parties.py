"""Parties: registration, reads and the lender credit-line restatement (§3.2)."""

from flask import Blueprint

import model
from core import (authenticate, body, new_row, opt_int, req_enum, req_int,
                  req_str, respond_object, store, touch)
from listing import list_response

bp = Blueprint("parties", __name__)

READ_ROLES = ("StateRegulator", "WarehouseOperator", "RegistryAdministrator",
              "Depositor", "Lender")
PARTY_KINDS = ("PRODUCER_DEPOSITOR", "COMMERCIAL_DEPOSITOR", "LENDER")


@bp.post("/parties")
def create_party():
    authenticate(("StateRegulator", "RegistryAdministrator"))
    data = body()
    name = req_str(data, "name")
    party_kind = req_enum(data, "party_kind", PARTY_KINDS)
    state_code = req_str(data, "state_code")
    credit_line = opt_int(data, "credit_line_cents", minimum=0, default=0)

    row = new_row()
    row.update({
        "name": name,
        "party_kind": party_kind,
        "state_code": state_code,
        "credit_line_cents": credit_line,
    })
    store.parties[row["id"]] = row
    return respond_object(model.party_out(row), 201)


@bp.get("/parties")
def list_parties():
    authenticate(READ_ROLES)
    return list_response(list(store.parties.values()),
                         ("party_kind", "state_code"), model.party_out)


@bp.get("/parties/<party_id>")
def read_party(party_id):
    authenticate(READ_ROLES)
    party = model.get_party(party_id)
    return respond_object(model.party_out(party))


@bp.patch("/parties/<party_id>/credit-line")
def restate_credit_line(party_id):
    authenticate(("StateRegulator",))
    party = model.get_party(party_id)
    data = body()
    party["credit_line_cents"] = req_int(data, "credit_line_cents", minimum=0)
    touch(party)
    return respond_object(model.party_out(party))
