"""Indemnity claims: filing and adjudication (§3.9)."""

from flask import Blueprint

import model
from core import (authenticate, body, fail, new_row, opt_str, req_enum, req_int,
                  req_str, respond_object, store, touch)
from listing import list_response

bp = Blueprint("claims", __name__)

READ_ROLES = ("StateRegulator", "WarehouseOperator", "Depositor", "Lender")
DECISIONS = ("ALLOW", "DISALLOW")
LIVE_CLAIM_STATES = ("FILED", "ALLOWED", "SETTLED")


@bp.post("/indemnity-claims")
def file_claim():
    caller = authenticate(("Depositor", "Lender"))
    data = body()

    raw_claimant = data.get("claimant_party_id")
    if isinstance(raw_claimant, str) and raw_claimant != caller.user_id:
        model.not_owner()

    warehouse_id = req_str(data, "warehouse_id")
    receipt_id = req_str(data, "receipt_id")
    claimant_id = req_str(data, "claimant_party_id")
    claimed = req_int(data, "claimed_cents")

    warehouse = model.get_warehouse(warehouse_id)
    receipt = model.get_receipt(receipt_id)
    claimant = model.get_party(claimant_id)

    if claimant_id != caller.user_id:
        model.not_owner()
    if caller.user_id not in (receipt["holder_party_id"],
                              receipt["registry_control_party_id"]):
        model.not_owner()

    if warehouse["insolvency_state"] != "CLAIMS_OPEN":
        fail("ERR_INVALID_STATE", 409)

    for other in store.claims.values():
        if (other["receipt_id"] == receipt_id
                and other["claimant_party_id"] == claimant_id
                and other["claim_state"] in LIVE_CLAIM_STATES):
            fail("ERR_CLAIM_DUPLICATE", 409)

    if claimed < 1 or receipt["receipt_state"] != "ISSUED":
        fail("ERR_CLAIM_NOT_ELIGIBLE", 422)

    row = new_row()
    row.update({
        "warehouse_id": warehouse_id,
        "receipt_id": receipt_id,
        "claimant_party_id": claimant_id,
        "claimed_cents": claimed,
        "entitlement_cents": 0,
        "allowed_cents": 0,
        "fund_eligible": claimant["party_kind"] == "PRODUCER_DEPOSITOR",
        "bond_share_cents": 0,
        "fund_share_cents": 0,
        "unpaid_cents": 0,
        "claim_state": "FILED",
        "adjudicated_by_user_id": None,
        "adjudication_note": None,
    })
    store.claims[row["id"]] = row
    return respond_object(model.claim_out(row), 201)


@bp.get("/indemnity-claims")
def list_claims():
    authenticate(READ_ROLES)
    return list_response(
        list(store.claims.values()),
        ("warehouse_id", "receipt_id", "claimant_party_id", "claim_state"),
        model.claim_out)


@bp.get("/indemnity-claims/<claim_id>")
def read_claim(claim_id):
    authenticate(READ_ROLES)
    claim = model.get_claim(claim_id)
    return respond_object(model.claim_out(claim))


@bp.post("/indemnity-claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    caller = authenticate(("StateRegulator",))
    claim = model.get_claim(claim_id)
    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    note = opt_str(data, "adjudication_note")

    warehouse = store.warehouses[claim["warehouse_id"]]

    if claim["claim_state"] != "FILED":
        fail("ERR_INVALID_STATE", 409)
    if warehouse["insolvency_state"] != "CLAIMS_OPEN":
        fail("ERR_INVALID_STATE", 409)

    receipt = store.receipts[claim["receipt_id"]]
    claimant = store.parties[claim["claimant_party_id"]]

    if decision == "ALLOW":
        declared = warehouse["_insolvency_declared_dt"]
        as_of = declared.date() if declared is not None else None
        lien = (model.provisional_storage_charge_cents(receipt, as_of)
                + receipt["receiving_charge_cents"])
        price = warehouse["insolvency_price_cents_per_bushel"] or 0
        entitlement = receipt["quantity_bushels"] * price - lien
        if entitlement < 0:
            entitlement = 0
        claim["entitlement_cents"] = entitlement
        claim["allowed_cents"] = min(claim["claimed_cents"], entitlement)
        claim["fund_eligible"] = claimant["party_kind"] == "PRODUCER_DEPOSITOR"
        claim["claim_state"] = "ALLOWED"
    else:
        claim["entitlement_cents"] = 0
        claim["allowed_cents"] = 0
        claim["claim_state"] = "DISALLOWED"

    claim["adjudicated_by_user_id"] = caller.user_id
    claim["adjudication_note"] = note
    touch(claim)
    return respond_object(model.claim_out(claim))
