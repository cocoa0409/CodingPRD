"""Payment endpoints: refund."""
from datetime import timedelta

from flask import Blueprint

import db
from clock import now, parse_iso, iso
from errors import err
from middleware import require_auth
from response import success
from services.validation import get_body, require_reason
from services.projection import payment_view
from services.payment import create_payment
from services.revenue import create_revenue_entry
from services.audit import write_audit


bp = Blueprint("payments", __name__)


@bp.route("/payments/<payment_id>/refund", methods=["POST"])
@require_auth(roles={"Operator"})
def refund_payment(payment_id):
    p = db.payments.get(payment_id)
    if p is None:
        raise err("ERR_NOT_FOUND", "Payment not found")
    if p.get("kind") == "REFUND":
        raise err("ERR_INVALID_STATE", "Cannot refund a refund row")
    body = get_body()
    reason = require_reason(body)

    # priority 17: refund window
    try:
        proc = parse_iso(p["processed_at"])
    except Exception:
        raise err("ERR_BAD_REQUEST", "processed_at unparseable")
    if now() > proc + timedelta(days=7):
        raise err("ERR_REFUND_WINDOW_EXPIRED", "Refund window has closed")

    # Append refund row
    refund = create_payment(
        kind="REFUND",
        subject_id=p["id"],
        amount_cents=int(p["amount_cents"]),
        card_id=p.get("card_id"),
    )

    # Subject lifecycle revert + revenue entry
    subj_kind = p.get("kind")
    sid = p.get("subject_id")
    lot_id = None
    zone_id = None
    if subj_kind == "SESSION_FEE":
        sess = db.sessions_tbl.get(sid)
        if sess is not None and sess.get("payment_status") == "PAID":
            sess["payment_status"] = "UNPAID"
            db.stamp_update(sess)
        if sess is not None:
            lot_id = sess.get("lot_id")
            sp = db.spaces.get(sess.get("space_id")) if sess.get("space_id") else None
            zone_id = sp.get("zone_id") if sp else None
    elif subj_kind == "FINE_PAYMENT":
        vio = db.violations.get(sid)
        if vio is not None:
            lot_id = vio.get("lot_id")
            sp = db.spaces.get(vio.get("space_id")) if vio.get("space_id") else None
            zone_id = sp.get("zone_id") if sp else None
    elif subj_kind == "NO_SHOW_PENALTY":
        res = db.reservations.get(sid)
        if res is not None:
            lot_id = res.get("lot_id")
            sp = db.spaces.get(res.get("space_id")) if res.get("space_id") else None
            zone_id = sp.get("zone_id") if sp else (res.get("zone_id"))
    elif subj_kind == "CARD_RECHARGE":
        # Refunding a recharge debits the card balance — handled via REFUND row
        # accounting (REFUND adds, but here it represents an outflow the
        # operator initiated; the algorithm treats REFUND as inflow which is
        # correct only when the original was an outflow). For a recharge refund,
        # we leave it: the user has acknowledged this edge.
        card = db.cards.get(sid)
        if card is not None:
            lot_id = None  # card-level refunds aren't tied to a lot

    if lot_id is not None:
        create_revenue_entry(
            lot_id=lot_id,
            zone_id=zone_id,
            billing_type="REFUND",
            source_kind="MANUAL",
            source_id=p["id"],
            gross_amount_cents=-int(p["amount_cents"]),
            notes=reason,
        )

    write_audit(
        action="BILLING_ADJUSTMENT",
        subject_kind="Payment",
        subject_id=p["id"],
        before={"refunded": False},
        after={"refunded": True, "refund_id": refund["id"]},
        reason=reason,
    )
    return success(payment_view(refund))
