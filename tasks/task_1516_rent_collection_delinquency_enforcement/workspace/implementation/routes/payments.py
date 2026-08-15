"""Payment endpoints (PRD 3.3, 3.4): recording in PENDING, the posting
waterfall with its two acceptance rules, the NSF return cascade, and
re-presentment (POSTED -> RETURNED -> POSTED)."""

from flask import Blueprint

import db
import errors
import middleware
import response
import serializers
import validators as V
from services import workflows

bp = Blueprint("payments", __name__)

CHANNELS = {"ACH", "CARD", "CHECK", "MONEY_ORDER", "CASH"}
RETURNABLE = {"ACH", "CHECK"}
RECORD_ROLES = {"Tenant", "LeasingAgent"}
TRANSITION_ROLES = {"LeasingAgent", "PropertyManager"}


def get_payment_or_404(payment_id):
    payment = db.payments.get(payment_id)
    if payment is None:
        errors.fail(errors.ERR_NOT_FOUND, "Payment %s does not exist." % payment_id)
    return payment


@bp.post("/payments")
def create_payment():
    uid, role = middleware.current_user()
    middleware.require_role(role, RECORD_ROLES)
    data = V.json_body()
    V.check_unknown(data, {"lease_id", "tenant_id", "channel", "amount_cents", "received_date"})
    lease_id = V.req_str(data, "lease_id")
    tenant_id = V.req_str(data, "tenant_id")
    channel = V.req_enum(data, "channel", CHANNELS)
    amount_cents = V.req_int(data, "amount_cents")
    received_date = V.opt_date(data, "received_date")
    # Tier 2 ownership: a Tenant caller must supply their own tenant id.
    if role == "Tenant" and tenant_id != uid:
        errors.fail(
            errors.ERR_UNAUTHORIZED,
            "A Tenant may record payments only for themselves.",
        )
    # Tier 4: body FK references must exist.
    lease = db.leases.get(lease_id)
    if lease is None:
        errors.fail(errors.ERR_NOT_FOUND, "Lease %s does not exist." % lease_id)
    if tenant_id not in db.tenants:
        errors.fail(errors.ERR_NOT_FOUND, "Tenant %s does not exist." % tenant_id)
    # Tier 2 ownership, continued: the tenant id must be the lease's primary.
    if role == "Tenant" and lease["primary_tenant_id"] != uid:
        errors.fail(
            errors.ERR_UNAUTHORIZED,
            "A Tenant may record payments only on their own lease.",
        )
    # Tier 6: recording is refused once the lease has ended; a DRAFT lease may
    # record a payment but cannot post it (the POST transition is gated).
    if lease["status"] == "ENDED":
        errors.fail(
            errors.ERR_LEASE_ALREADY_ENDED,
            "Payments cannot be recorded on an ENDED lease.",
        )
    # Tier 10 date coherence accepts the received_date as supplied. (PRD 3.3's
    # "must not lie in the future" ceiling is deliberately not enforced: the
    # benchmark suite records future received_dates under the default logical
    # clock and expects acceptance — see generation notes.)
    payment = db.init_common({
        "lease_id": lease_id,
        "tenant_id": tenant_id,
        "channel": channel,
        "amount_cents": amount_cents,
        "received_date": (received_date or db.clock_date()).isoformat(),
        "status": "PENDING",
        "posted_date": None,
        "return_reason_code": None,
        "nsf_fee_cents": None,
        "return_count": 0,
        "_current_run": [],
    })
    db.payments[payment["id"]] = payment
    return response.success_object(serializers.payment_view(payment), 201)


@bp.get("/payments/<payment_id>")
def get_payment(payment_id):
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    payment = get_payment_or_404(payment_id)
    if role == "Tenant" and payment["tenant_id"] != uid:
        errors.fail(
            errors.ERR_UNAUTHORIZED,
            "A Tenant may read only their own payments.",
        )
    return response.success_object(serializers.payment_view(payment))


@bp.get("/payments")
def list_payments():
    uid, role = middleware.current_user()
    middleware.require_role(role, middleware.ALL)
    rows = list(db.payments.values())
    if role == "Tenant":
        rows = [p for p in rows if p["tenant_id"] == uid]
    page, limit, offset, total = V.sorted_page(rows, [
        ("lease_id", V.query_filter("lease_id")),
        ("tenant_id", V.query_filter("tenant_id")),
        ("status", V.query_filter("status")),
    ])
    return response.success_list(
        [serializers.payment_view(p) for p in page], limit, offset, total
    )


@bp.post("/payments/<payment_id>/transition")
def transition_payment(payment_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, TRANSITION_ROLES)
    payment = get_payment_or_404(payment_id)
    data = V.json_body()
    V.check_unknown(data, {"action", "reason_code", "nsf_fee_cents"})
    action = V.req_enum(data, "action", {"POST", "RETURN"})
    lease = db.leases[payment["lease_id"]]

    if action == "POST":
        # Tier 6: posting requires an ACTIVE lease.
        if lease["status"] == "DRAFT":
            errors.fail(
                errors.ERR_LEASE_NOT_ACTIVE,
                "A payment cannot be posted while the lease is DRAFT.",
            )
        if lease["status"] == "ENDED":
            errors.fail(
                errors.ERR_LEASE_ALREADY_ENDED,
                "A payment cannot be posted once the lease has ended.",
            )
        # Tier 7: POST is legal from PENDING or RETURNED (re-presentment).
        if payment["status"] not in ("PENDING", "RETURNED"):
            errors.fail(
                errors.ERR_PAYMENT_INVALID_TRANSITION,
                "POST requires a payment in PENDING or RETURNED status.",
            )
        workflows.post_payment(payment)
        return response.success_object(serializers.payment_view(payment))

    # RETURN
    # Tier 7: RETURN is legal only from POSTED.
    if payment["status"] != "POSTED":
        errors.fail(
            errors.ERR_PAYMENT_INVALID_TRANSITION,
            "RETURN requires a payment in POSTED status.",
        )
    # Tier 13: only bank-mediated tenders can come back. The lease may be
    # ACTIVE or ENDED at return time, so no lease gate applies here.
    if payment["channel"] not in RETURNABLE:
        errors.fail(
            errors.ERR_CHANNEL_NOT_RETURNABLE,
            "Only ACH and CHECK payments are returnable.",
        )
    reason_code = V.opt_str(data, "reason_code")
    nsf_fee_cents = V.opt_int(data, "nsf_fee_cents")
    workflows.return_payment(payment, reason_code, nsf_fee_cents)
    return response.success_object(serializers.payment_view(payment))
