"""Invoice state machine endpoints."""

from flask import Blueprint

from httpkit import (
    authenticate, ensure_empty_body, err_invalid_state, err_not_found,
    require_member_ownership, require_roles, respond_object,
)
from serializers import invoice_json
from services import touch
from store import db

bp = Blueprint("invoices", __name__)


def _get_invoice_or_404(invoice_id):
    inv = db.invoices.get(invoice_id)
    if inv is None:
        raise err_not_found(f"Invoice {invoice_id} does not exist")
    return inv


def _owning_member_id(invoice):
    trip = db.trips.get(invoice["trip_id"])
    if trip is None:
        return None
    card = db.cards.get(trip["card_id"])
    return card["member_id"] if card else None


@bp.post("/invoices/<invoiceId>/mark_paid")
def mark_paid(invoiceId):
    ensure_empty_body()
    authenticate()
    require_roles("Ops")
    inv = _get_invoice_or_404(invoiceId)
    if inv["invoice_status"] not in ("ISSUED", "DISPUTED"):
        raise err_invalid_state("Invoice must be ISSUED or DISPUTED to mark paid")
    inv["invoice_status"] = "PAID"
    touch(inv)
    return respond_object(invoice_json(inv))


@bp.post("/invoices/<invoiceId>/dispute")
def dispute(invoiceId):
    ensure_empty_body()
    authenticate()
    require_roles("Member")
    inv = _get_invoice_or_404(invoiceId)
    owner = _owning_member_id(inv)
    if owner is not None:
        require_member_ownership(owner)
    if inv["invoice_status"] != "ISSUED":
        raise err_invalid_state("Only an ISSUED invoice can be disputed")
    inv["invoice_status"] = "DISPUTED"
    touch(inv)
    return respond_object(invoice_json(inv))


@bp.post("/invoices/<invoiceId>/write_off")
def write_off(invoiceId):
    ensure_empty_body()
    authenticate()
    require_roles("Ops")
    inv = _get_invoice_or_404(invoiceId)
    if inv["invoice_status"] not in ("ISSUED", "DISPUTED"):
        raise err_invalid_state(
            "Invoice must be ISSUED or DISPUTED to write off")
    inv["invoice_status"] = "WRITTEN_OFF"
    touch(inv)
    return respond_object(invoice_json(inv))
