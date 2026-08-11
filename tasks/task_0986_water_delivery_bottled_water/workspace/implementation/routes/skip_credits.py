"""SkipCredit endpoints."""
from flask import Blueprint

import errors
import services
from db import db
from middleware import check_transition, require_owner, require_roles
from response import ok_object
from services import bump, ser_skip_credit

bp = Blueprint("skip_credits", __name__)

CREDIT_TERMINAL = ("APPLIED", "EXPIRED", "REVOKED")


def _get_credit(cid):
    sc = db.skip_credits.get(cid)
    if sc is None:
        raise errors.not_found("skip credit not found")
    return sc


@bp.get("/skip-credits/<cid>")
@require_roles("OpsAdmin", "BillingAdmin", "CustomerSelf")
def get_skip_credit(cid):
    sc = _get_credit(cid)
    require_owner(sc["customer_id"])
    return ok_object(ser_skip_credit(sc))


@bp.post("/skip-credits/<cid>/apply")
@require_roles("BillingAdmin")
def apply_skip_credit(cid):
    sc = _get_credit(cid)
    check_transition(sc, "credit_status", ("PENDING",), CREDIT_TERMINAL,
                     "SkipCredit")
    if services.now() >= sc["expires_at"]:
        raise errors.ApiError(errors.ERR_CREDIT_EXPIRED, 422,
                              "skip credit has expired")
    with db.lock:
        # The credit lands on the customer's next DRAFT invoice as a negative
        # line; if none exists yet, it is absorbed by the next one drafted.
        draft = None
        for inv in db.invoices.values():
            if (inv["customer_id"] == sc["customer_id"]
                    and inv["invoice_status"] == "DRAFT"):
                if draft is None or (inv["created_at"], inv["seq"]) < (
                        draft["created_at"], draft["seq"]):
                    draft = inv
        if draft is not None:
            draft["total_due_cents"] -= sc["credit_cents"]
            draft["balance_due_cents"] -= sc["credit_cents"]
            bump(draft)
            sc["pending_consumption"] = False
        else:
            sc["pending_consumption"] = True
        sc["credit_status"] = "APPLIED"
        bump(sc)
    return ok_object(ser_skip_credit(sc))


@bp.post("/skip-credits/<cid>/revoke")
@require_roles("OpsAdmin")
def revoke_skip_credit(cid):
    sc = _get_credit(cid)
    check_transition(sc, "credit_status", ("PENDING",), CREDIT_TERMINAL,
                     "SkipCredit")
    with db.lock:
        sc["credit_status"] = "REVOKED"
        bump(sc)
    return ok_object(ser_skip_credit(sc))
