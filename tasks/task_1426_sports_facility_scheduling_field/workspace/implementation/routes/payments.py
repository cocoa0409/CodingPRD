"""Payment routes: list, read, approve refunds (PRD 3.8)."""

from flask import Blueprint, request

import errors
import util
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object
from services import core

bp = Blueprint("payments", __name__)


@bp.get("/payments")
def list_payments():
    require_roles(*ANY_ROLE)
    items = list(store.payments.values())
    for param in ("invoice_id", "organization_id", "kind", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [p for p in items if p.get(param) == val]
    return util.paginate(items)


@bp.get("/payments/<pid>")
def get_payment(pid):
    require_roles(*ANY_ROLE)
    return success_object(core.get_payment(pid))


@bp.post("/payments/<pid>/approve")
def approve_payment(pid):
    user_id, _ = require_roles("AthleticsAdmin")
    payment = core.get_payment(pid)
    # Priority 6: segregation of duties (evaluated ahead of state per the
    # validation pipeline; only the refund-approval endpoint carries it).
    if payment["kind"] == "REFUND" and user_id == payment["initiated_by"]:
        raise errors.ApiError(errors.ERR_SEGREGATION_OF_DUTIES,
                              "Approver must differ from the refund initiator", 403)
    if payment["status"] != "PENDING_APPROVAL":
        raise errors.ApiError(errors.ERR_INVALID_PAYMENT_STATE,
                              "Payment is not PENDING_APPROVAL", 409)

    payment["status"] = "CLEARED"
    payment["approved_by"] = user_id
    util.touch(payment)

    inv = core.get_invoice(payment["invoice_id"])
    inv["refunded_cents"] += payment["amount_cents"]
    core.recompute_invoice_totals(inv)
    core.maybe_settle_refunded(inv)
    util.touch(inv)
    return success_object(payment)
