"""FeeInvoice endpoints."""
from flask import Blueprint

import clock
import services
import store
from auth import authenticate, authorize
from errors import raise_err, ERR_FISCAL_BLOCK
from util import bump, success_object, get_or_404

bp = Blueprint("invoices", __name__)


@bp.get("/awards/invoices/<iid>")
def get_invoice(iid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin", "Auditor", "Entrant"])
    inv = get_or_404(store.invoices, iid, "FeeInvoice")
    if role == "Entrant":
        e = store.entries.get(inv["entry_id"])
        if e is None or e["entrant_id"] != uid:
            from auth import forbid
            forbid("Entrant may only read their own invoices")
    return success_object(services.serialize_invoice(inv), 200)


@bp.post("/awards/invoices/<iid>/pay")
def pay_invoice(iid):
    uid, role = authenticate()
    authorize(role, ["Entrant"])
    inv = get_or_404(store.invoices, iid, "FeeInvoice")
    e = store.entries.get(inv["entry_id"])
    # Non-owner payment attempt and non-payable invoice are both FISCAL_BLOCK
    # (PRD 3.3); the terminal-state guard is intentionally not applied here.
    if e is None or e["entrant_id"] != uid:
        raise_err(ERR_FISCAL_BLOCK, "only the owning entrant may pay this invoice")
    if inv["status"] != "ISSUED":
        raise_err(ERR_FISCAL_BLOCK, "invoice is not in a payable state (ISSUED)")
    now = clock.now()
    inv["status"] = "PAID"
    inv["paid_at"] = now
    bump(inv)
    e["payment_status"] = "PAID"
    if e["status"] == "SUBMITTED":
        e["status"] = "UNDER_REVIEW"
    bump(e)
    entrant = store.entrants.get(e["entrant_id"])
    if entrant is not None:
        services.recompute_standing(entrant)
    return success_object(services.serialize_invoice(inv), 200)
