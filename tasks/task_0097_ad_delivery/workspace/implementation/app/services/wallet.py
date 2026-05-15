"""Wallet ledger and balance-posture derivation."""
from .. import store
from ..audit import emit as audit_emit
from ..clock import now_iso
from ..errors import ApiError


def recompute_balance(advertiser: dict):
    """Recompute balance_cents and consumed_cents from the WalletTransaction ledger."""
    bal = 0
    consumed = 0
    for tx in store.list_all("WalletTransaction"):
        if tx.get("advertiser_id") != advertiser["id"]:
            continue
        if tx.get("status") != "SETTLED":
            continue
        bal += int(tx["amount_cents"])
        if tx["tx_type"] == "CONSUMPTION":
            consumed += -int(tx["amount_cents"])  # consumption amounts are negative
    advertiser["balance_cents"] = bal
    advertiser["consumed_cents"] = consumed


def derive_balance_state(balance_cents: int, threshold: int) -> str:
    if balance_cents <= 0:
        return "ZERO_BALANCE"
    if balance_cents <= threshold:
        return "LOW_BALANCE"
    return "HEALTHY"


def recompute_balance_state(advertiser: dict, *, triggered_by: str | None = None):
    """Recompute balance_state. If posture worsens to ZERO_BALANCE, cascade pause."""
    prev = advertiser.get("balance_state", "HEALTHY")
    new = derive_balance_state(int(advertiser["balance_cents"]), int(advertiser.get("low_balance_threshold_cents", 0)))
    advertiser["balance_state"] = new

    if prev == "HEALTHY" and new == "LOW_BALANCE":
        audit_emit(
            "BALANCE_ADJUSTMENT",
            "Advertiser",
            advertiser["id"],
            before_value={"balance_state": prev},
            after_value={"balance_state": new, "note": "low_balance_alert"},
            actor_user_id="system",
            actor_role="system",
        )

    if new == "ZERO_BALANCE" and prev != "ZERO_BALANCE":
        _cascade_pause_on_zero(advertiser)


def _cascade_pause_on_zero(advertiser: dict):
    from .lifecycle import pause_campaign_cascade  # avoid circular import

    for camp in list(store.list_all("Campaign")):
        if camp.get("advertiser_id") != advertiser["id"]:
            continue
        if camp.get("status") == "ACTIVE":
            pause_campaign_cascade(camp, cascade=True)


def create_wallet_tx(
    advertiser: dict,
    tx_type: str,
    amount_cents: int,
    idempotency_key: str,
    reference_event_id: str | None = None,
    note: str | None = None,
    actor_user_id: str | None = None,
    actor_role: str | None = None,
    audit_action: str | None = None,
) -> dict:
    if tx_type == "ADJUSTMENT" and (not note or not str(note).strip()):
        raise ApiError("ERR_INVALID_REQUEST", "Field 'note' is required for ADJUSTMENT.")

    # PRD §3.8: idempotency-key conflict + balance update must serialise
    # so the loser of a concurrent same-key race gets ERR_IDEMPOTENCY_CONFLICT
    # and balance reflects exactly one credit.
    with store.lock():
        # Idempotency check across (advertiser_id, tx_type, idempotency_key).
        for existing in store.list_all("WalletTransaction"):
            if (
                existing.get("advertiser_id") == advertiser["id"]
                and existing.get("tx_type") == tx_type
                and existing.get("idempotency_key") == idempotency_key
            ):
                raise ApiError("ERR_IDEMPOTENCY_CONFLICT")

        # Credit-floor checks for refunds and adjustments that decrease balance.
        new_bal = int(advertiser["balance_cents"]) + int(amount_cents)
        credit_line = int(advertiser.get("credit_line_cents", 0))
        if tx_type == "REFUND" and new_bal < -credit_line:
            raise ApiError("ERR_REFUND_WOULD_BREACH_CREDIT_FLOOR")
        if tx_type == "ADJUSTMENT" and int(amount_cents) < 0 and new_bal < -credit_line:
            raise ApiError("ERR_INSUFFICIENT_BALANCE")

        rec = {
            "id": store.gen_uuid(),
            "advertiser_id": advertiser["id"],
            "tx_type": tx_type,
            "amount_cents": int(amount_cents),
            "reference_event_id": reference_event_id,
            "status": "SETTLED",
            "idempotency_key": idempotency_key,
            "note": note,
        }
        store.stamp_common(rec, with_version=False)
        store.insert("WalletTransaction", rec)

        # Apply to advertiser balance.
        recompute_balance(advertiser)
        recompute_balance_state(advertiser)

        if audit_action:
            audit_emit(
                audit_action,
                "WalletTransaction",
                rec["id"],
                before_value={"balance_cents": new_bal - int(amount_cents)},
                after_value={"balance_cents": advertiser["balance_cents"], "amount_cents": int(amount_cents)},
                actor_user_id=actor_user_id,
                actor_role=actor_role,
            )

    return rec


def reverse_wallet_tx(advertiser: dict, tx: dict, note: str) -> dict:
    if tx.get("status") != "SETTLED":
        raise ApiError("ERR_INVALID_REQUEST", "Only SETTLED wallet transactions can be reversed.")
    if not note or not str(note).strip():
        raise ApiError("ERR_INVALID_REQUEST", "Field 'note' is required for reversal.")

    inverse = -int(tx["amount_cents"])
    new_bal = int(advertiser["balance_cents"]) + inverse
    credit_line = int(advertiser.get("credit_line_cents", 0))
    if new_bal < -credit_line:
        raise ApiError("ERR_REFUND_WOULD_BREACH_CREDIT_FLOOR")

    # PRD §3.8: reversal sets the transaction's status to REVERSED and
    # applies the inverse amount to balance_cents. The append-only
    # ledger requires balance_cents = sum(amount_cents) over SETTLED
    # rows (§3.9); marking the original as REVERSED removes its
    # contribution from that sum, which IS the inverse application,
    # giving the forward-plus-reverse net-zero invariant.
    tx["status"] = "REVERSED"
    tx["reversal_note"] = note

    recompute_balance(advertiser)
    recompute_balance_state(advertiser)

    audit_emit(
        "BALANCE_ADJUSTMENT",
        "WalletTransaction",
        tx["id"],
        before_value={"status": "SETTLED", "amount_cents": int(tx["amount_cents"])},
        after_value={"status": "REVERSED", "balance_cents": advertiser["balance_cents"]},
    )
    return tx
