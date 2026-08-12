"""RegistrationInvoice endpoints."""

from flask import Blueprint

import errors
import serializers
from db import store, touch
from envelope import ok
from validators import endpoint, get_or_404

bp = Blueprint("invoices", __name__)


@bp.route("/hazmat/registration-invoices/<invoiceId>/void", methods=["POST"])
@endpoint(["Regulator"])
def void_invoice(uid, role, invoiceId):
    inv = get_or_404(store.invoices, invoiceId, errors.ERR_INVOICE_NOT_FOUND,
                     "RegistrationInvoice")
    if inv["status"] != "OPEN":
        raise errors.conflict(errors.ERR_INVOICE_NOT_VOIDABLE,
                              "Void requires invoice OPEN")
    inv["status"] = "VOID"
    touch(inv)
    return ok(serializers.invoice(inv), 200)
