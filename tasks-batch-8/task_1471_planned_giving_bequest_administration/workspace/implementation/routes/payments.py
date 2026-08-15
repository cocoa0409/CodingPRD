"""Annuity payments: list/read (lazy sweep), PAY / DEFER / LAPSE (PRD 3.6)."""
from flask import Blueprint

import store
from domain import lookup, paginate, sweep_payments, view
from envelope import success
from errors import ApiError
from security import ALL_ROLES, require_roles
from store import iso, now, touch
from validate import get_body, parse_dt, validate_body

bp = Blueprint("payments", __name__)

ACTIONS = ("PAY", "DEFER", "LAPSE")


@bp.get("/giving/annuity-payments")
@require_roles(*ALL_ROLES)
def list_payments():
    sweep_payments()  # lazy sweep on read (PRD 2.4)
    from flask import request

    items = list(store.payments.values())
    agreement_filter = request.args.get("gift_agreement_id")
    status_filter = request.args.get("status")
    if agreement_filter is not None:
        items = [p for p in items if p["gift_agreement_id"] == agreement_filter]
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    if agreement_filter is not None:
        # deterministic: period_index ascending within an agreement (PRD 2.3)
        items.sort(key=lambda p: p["period_index"])
    else:
        items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, meta = paginate(items)
    return success([view(p) for p in page], 200, meta)


@bp.get("/giving/annuity-payments/<payment_id>")
@require_roles(*ALL_ROLES)
def get_payment(payment_id):
    payment = lookup(store.payments, payment_id, "AnnuityPayment")
    sweep_payments(target=payment)  # lazy sweep on read
    return success(view(payment), 200)


@bp.post("/giving/annuity-payments/<payment_id>/transition")
@require_roles("GiftAdministrator")
def payment_transition(payment_id):
    payment = lookup(store.payments, payment_id, "AnnuityPayment")
    body = get_body()
    validate_body(
        body,
        {"action": ("str", True, ACTIONS), "defer_until": ("datetime", False, None)},
    )
    action = body["action"]
    agreement = store.agreements.get(payment["gift_agreement_id"])

    if action == "PAY":
        if payment["status"] != "DUE":
            raise ApiError(
                "ERR_PAYMENT_NOT_DUE",
                409,
                "Payment is %s, not DUE" % payment["status"],
            )
        if agreement is not None and agreement["status"] == "SUSPENDED":
            raise ApiError(
                "ERR_AGREEMENT_SUSPENDED",
                409,
                "Parent agreement is SUSPENDED",
            )
        if agreement is None or agreement["status"] != "ACTIVE":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Parent agreement is not ACTIVE",
            )
        payment["status"] = "PAID"
        payment["paid_at"] = iso(now())
        touch(payment)
        touch(agreement)
    elif action == "DEFER":
        if payment["status"] != "DUE":
            raise ApiError(
                "ERR_PAYMENT_NOT_DUE",
                409,
                "Payment is %s, not DUE" % payment["status"],
            )
        defer_until = body.get("defer_until")
        if defer_until is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "defer_until is required")
        if parse_dt(defer_until) <= now():
            raise ApiError(
                "ERR_INVALID_REQUEST", 400, "defer_until must lie in the future"
            )
        payment["status"] = "DEFERRED"
        payment["defer_until"] = defer_until
        touch(payment)
    else:  # LAPSE
        if payment["status"] not in ("SCHEDULED", "DUE", "DEFERRED"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Cannot LAPSE from %s" % payment["status"],
            )
        payment["status"] = "LAPSED"
        payment["lapse_reason"] = "MANUAL"
        touch(payment)
        if agreement is not None:
            touch(agreement)

    return success(view(payment), 200)
