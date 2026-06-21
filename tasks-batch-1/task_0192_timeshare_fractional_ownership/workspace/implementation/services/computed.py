"""Computed-field derivations and entity serialization with computed fields merged."""
from db import db
from services.util import serialize


# ---------------------------------------------------------------------------
# PointsAccount.available_points
#   = allotment_points + banked_in_points - banked_out_points
#     - borrowed_out_points - committed_points
# ---------------------------------------------------------------------------
def available_points(acct):
    return (
        acct["allotment_points"]
        + acct["banked_in_points"]
        - acct["banked_out_points"]
        - acct["borrowed_out_points"]
        - acct["committed_points"]
    )


def serialize_points_account(acct):
    return serialize(acct, {"available_points": available_points(acct)})


# ---------------------------------------------------------------------------
# MaintenanceFeeInvoice.amount_due_cents = amount_cents + late_charge_cents - amount_paid_cents
# ---------------------------------------------------------------------------
def invoice_amount_due(inv):
    return inv["amount_cents"] + inv["late_charge_cents"] - inv["amount_paid_cents"]


def serialize_invoice(inv):
    return serialize(inv, {"amount_due_cents": invoice_amount_due(inv)})


# ---------------------------------------------------------------------------
# Owner computed fields: status + open_balance_cents
# ---------------------------------------------------------------------------
def owner_open_balance(owner_id):
    total = 0
    for inv in db.invoices.values():
        if inv["owner_id"] == owner_id and inv["status"] in ("ISSUED", "DELINQUENT"):
            total += invoice_amount_due(inv)
    return total


def owner_status(owner_id):
    # Contracts of this owner.
    contract_ids = {c["id"] for c in db.contracts.values() if c["owner_id"] == owner_id}
    # SUSPENDED if any case on this owner's contracts is in {LIEN, FORECLOSURE, TERMINATION}.
    for case in db.delinquency_cases.values():
        if case["contract_id"] in contract_ids and case["status"] in (
            "LIEN",
            "FORECLOSURE",
            "TERMINATION",
        ):
            return "SUSPENDED"
    # DELINQUENT if any of this owner's invoices is DELINQUENT.
    for inv in db.invoices.values():
        if inv["owner_id"] == owner_id and inv["status"] == "DELINQUENT":
            return "DELINQUENT"
    return "GOOD_STANDING"


def serialize_owner(owner):
    return serialize(
        owner,
        {
            "status": owner_status(owner["id"]),
            "open_balance_cents": owner_open_balance(owner["id"]),
        },
    )
