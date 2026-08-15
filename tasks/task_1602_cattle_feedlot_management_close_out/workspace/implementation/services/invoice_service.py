"""Invoice business logic: generation, payment, void."""
import store
from util import new_record, bump
from errors import raise_err, ERR_INVOICE_NOT_OPEN, ERR_INVALID_REQUEST, \
    ERR_OVERPAYMENT, ERR_OWNER_NOT_FOUND
from . import calculations
from . import lot_service


def create_invoice_for_lot(lot):
    """Generate an OPEN invoice for a lot at close-out confirm."""
    owner = store.owners.get(lot["owner_id"])
    if owner is None:
        raise_err(ERR_OWNER_NOT_FOUND, "Owner not found: %s" % lot["owner_id"])

    # Compute invoice lines
    lines = calculations.compute_invoice_total(lot)

    rec = new_record()
    rec.update({
        "lot_id": lot["id"],
        "owner_id": lot["owner_id"],
        "feed_cents": lines["feed_cents"],
        "yardage_cents": lines["yardage_cents"],
        "yardage_head_days": lines["yardage_head_days"],
        "health_cents": lines["health_cents"],
        "death_loss_cents": lines["death_loss_cents"],
        "insurance_credit_cents": lines["insurance_credit_cents"],
        "total_cents": lines["total_cents"],
        "amount_paid_cents": 0,
        "status": "OPEN",
        "void_reason": None,
    })
    store.invoices[rec["id"]] = rec

    # Update owner balance
    owner["outstanding_balance_cents"] += lines["total_cents"]
    bump(owner)

    return rec


def apply_payment(invoice, amount_cents, payment_date):
    """Apply a payment to an OPEN invoice."""
    if invoice["status"] != "OPEN":
        raise_err(ERR_INVOICE_NOT_OPEN,
                  "Invoice %s is not OPEN (status=%s)" % (invoice["id"], invoice["status"]))

    if amount_cents <= 0:
        raise_err(ERR_INVALID_REQUEST, "amount_cents must be > 0")

    if invoice["amount_paid_cents"] + amount_cents > invoice["total_cents"]:
        raise_err(ERR_OVERPAYMENT,
                  "Payment would exceed invoice total (%d + %d > %d)"
                  % (invoice["amount_paid_cents"], amount_cents, invoice["total_cents"]))

    owner = store.owners.get(invoice["owner_id"])
    if owner is None:
        raise_err(ERR_OWNER_NOT_FOUND, "Owner not found: %s" % invoice["owner_id"])

    invoice["amount_paid_cents"] += amount_cents
    owner["outstanding_balance_cents"] -= amount_cents

    # Check if fully paid
    if invoice["amount_paid_cents"] == invoice["total_cents"]:
        invoice["status"] = "PAID"
        bump(invoice)
        # Bubble up: lot -> SETTLED
        lot = store.lots.get(invoice["lot_id"])
        if lot and lot["status"] == "CLOSED_OUT":
            lot_service.settle_lot(lot)
    else:
        bump(invoice)

    bump(owner)
    return invoice


def void_invoice(invoice, reason=None):
    """Void an OPEN invoice (compensating action)."""
    if invoice["status"] != "OPEN":
        raise_err(ERR_INVOICE_NOT_OPEN,
                  "Invoice %s is not OPEN (status=%s); a PAID invoice can never be voided"
                  % (invoice["id"], invoice["status"]))

    owner = store.owners.get(invoice["owner_id"])
    if owner is None:
        raise_err(ERR_OWNER_NOT_FOUND, "Owner not found: %s" % invoice["owner_id"])

    # Compensate owner by unpaid remainder
    remainder = invoice["total_cents"] - invoice["amount_paid_cents"]
    owner["outstanding_balance_cents"] -= remainder

    invoice["status"] = "VOID"
    invoice["void_reason"] = reason
    bump(invoice)
    bump(owner)

    return invoice


def void_invoice_system(invoice):
    """System-initiated void (e.g., when close-out is superseded)."""
    if invoice["status"] != "OPEN":
        return  # Only void OPEN invoices

    owner = store.owners.get(invoice["owner_id"])
    if owner:
        remainder = invoice["total_cents"] - invoice["amount_paid_cents"]
        owner["outstanding_balance_cents"] -= remainder
        bump(owner)

    invoice["status"] = "VOID"
    invoice["void_reason"] = "superseded"
    bump(invoice)
