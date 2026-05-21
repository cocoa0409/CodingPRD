"""Gift point transfer endpoint."""

from __future__ import annotations

from flask import Blueprint, g

from .. import errors as E
from ..auth import require_roles
from ..envelope import ok_object
from ..store import store
from ..timeutil import clock
from ..services.common import (
    get_json_body, require_fields, bump_version,
    get_member_or_404, enforce_member_ownership, enforce_member_status,
)
from ..services.serialize import (
    serialize_points_transaction, compute_points_balance,
)
from ..services import calc, ledger


gifts_bp = Blueprint("gifts", __name__)


def _payload_signature(body: dict) -> tuple:
    return (
        body.get("recipient_member_id"),
        body.get("amount"),
    )


@gifts_bp.post("/members/<sender_id>/gifts")
@require_roles("Member", "BookingAgent")
def gift_points(sender_id):
    sender = get_member_or_404(sender_id)
    enforce_member_ownership(g.user_id, g.user_role, sender_id)
    body = get_json_body()
    require_fields(body, "recipient_member_id", "amount", "idempotency_key")
    if not isinstance(body["amount"], int) or isinstance(body["amount"], bool):
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "amount must be an integer.")
    if not isinstance(body["idempotency_key"], str) or not body["idempotency_key"].strip():
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "idempotency_key required.")
    recipient_id = body["recipient_member_id"]
    if not isinstance(recipient_id, str) or not recipient_id.strip():
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "recipient_member_id required.")
    # Idempotency check first (cheap structural check)
    idem_key = (sender_id, body["idempotency_key"])
    sig = _payload_signature(body)
    existing = store.gift_idempotency.get(idem_key)
    if existing is not None:
        if existing["signature"] != sig:
            raise E.ApiError(E.ERR_IDEMPOTENCY_CONFLICT, 409,
                             "Idempotency key reused with different payload.")
        # Idempotent replay — return the previously appended rows.
        txns = [store.points_transactions[tid] for tid in existing["transaction_ids"]]
        data = [serialize_points_transaction(t) for t in txns]
        return ok_object(data, 201)
    # Recipient must exist
    recipient = store.members.get(recipient_id)
    if not recipient:
        raise E.ApiError(E.ERR_MEMBER_NOT_FOUND, 404, "Recipient member not found.")
    # Below-minimum check
    amount = body["amount"]
    if amount < calc.GIFT_MIN:
        raise E.ApiError(E.ERR_GIFT_BELOW_MINIMUM, 400, f"Gift amount below minimum {calc.GIFT_MIN}.")
    # Member-status guards
    enforce_member_status(sender)
    enforce_member_status(recipient)
    now = clock.now()
    # Daily cap (sender, UTC calendar day)
    today = now.date()
    daily_sent = 0
    for t in store.points_transactions.values():
        if t["member_id"] != sender_id or t["kind"] != "GIFT_OUT":
            continue
        if t["posted_at"].date() == today:
            daily_sent += -t["points_delta"]  # GIFT_OUT delta is negative
    if daily_sent + amount > calc.GIFT_MAX_PER_DAY_PER_SENDER:
        raise E.ApiError(E.ERR_GIFT_DAILY_CAP_EXCEEDED, 402, "Daily gift cap exceeded.")
    # Sufficiency
    bal = compute_points_balance(sender_id, now)
    if bal < amount:
        raise E.ApiError(E.ERR_INSUFFICIENT_POINTS, 402, "Insufficient points.")
    # Fee math
    fee_points, delivered = calc.gift_fee_and_delivered(amount)
    # Atomic three-row append
    out = ledger.append(
        member_id=sender_id, kind="GIFT_OUT", points_delta=-amount,
        posted_at=now, counterparty_member_id=recipient_id,
        idempotency_key=body["idempotency_key"], now=now,
    )
    fee = ledger.append(
        member_id=sender_id, kind="GIFT_FEE", points_delta=0,
        posted_at=now, counterparty_member_id=recipient_id,
        idempotency_key=body["idempotency_key"], now=now,
    )
    in_ = ledger.append(
        member_id=recipient_id, kind="GIFT_IN", points_delta=delivered,
        posted_at=now, counterparty_member_id=sender_id,
        idempotency_key=body["idempotency_key"], now=now,
    )
    # Also consume the fee_points from the sender's FIFO buckets (since the sender's
    # balance dropped by amount = delivered + fee_points; GIFT_OUT only consumed
    # delivered worth — we additionally consume fee_points to keep accrual buckets aligned).
    # Note: ledger.append already consumed |GIFT_OUT.points_delta| = amount via FIFO
    # because GIFT_OUT is in CONSUMING_KINDS. So buckets are correctly drawn down.

    store.gift_idempotency[idem_key] = {
        "signature": sig,
        "transaction_ids": [out["id"], fee["id"], in_["id"]],
    }
    sender["last_activity_at"] = now
    recipient["last_activity_at"] = now
    bump_version(sender, now)
    bump_version(recipient, now)
    data = [
        serialize_points_transaction(out),
        serialize_points_transaction(fee),
        serialize_points_transaction(in_),
    ]
    return ok_object(data, 201)
