"""PointsTransaction ledger helpers.

The ledger is append-only. The single source of truth for Member.points_balance
is the ledger sum (see PRD §2.8). FIFO consumption of ACCRUAL buckets by later
debits is recorded on each ACCRUAL row's remaining_unredeemed field, so the
points_expiration sweep can rapidly find unredeemed amounts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..store import store, new_uuid


CONSUMING_KINDS = {"REDEMPTION", "GIFT_OUT", "GIFT_FEE", "EXPIRATION"}


def append(
    *,
    member_id: str,
    kind: str,
    points_delta: int,
    posted_at: datetime,
    qualifying_points: int = 0,
    expires_at: Optional[datetime] = None,
    remaining_unredeemed: Optional[int] = None,
    related_segment_id: Optional[str] = None,
    related_booking_id: Optional[str] = None,
    related_certificate_id: Optional[str] = None,
    counterparty_member_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    now: Optional[datetime] = None,
) -> dict:
    if now is None:
        from ..timeutil import clock
        now = clock.now()
    tid = new_uuid()
    txn = {
        "id": tid,
        "member_id": member_id,
        "created_at": now,
        "kind": kind,
        "points_delta": points_delta,
        "qualifying_points": qualifying_points,
        "posted_at": posted_at,
        "expires_at": expires_at,
        "remaining_unredeemed": remaining_unredeemed,
        "related_segment_id": related_segment_id,
        "related_booking_id": related_booking_id,
        "related_certificate_id": related_certificate_id,
        "counterparty_member_id": counterparty_member_id,
        "idempotency_key": idempotency_key,
        "_seq": store.next_seq(),
    }
    store.points_transactions[tid] = txn

    # FIFO bucket consumption for negative ledger rows
    if kind in CONSUMING_KINDS and points_delta < 0:
        consume_buckets(member_id, -points_delta, exclude_id=tid)
    elif kind == "ACCRUAL" and points_delta < 0:
        # Negative ACCRUAL (segment refund) — also consumes the original bucket's
        # remaining_unredeemed if any is left.
        consume_buckets(member_id, -points_delta, exclude_id=tid)

    return txn


def consume_buckets(member_id: str, amount: int, exclude_id: Optional[str] = None) -> None:
    """Draw down ACCRUAL buckets FIFO by posted_at, tie on id ascending.

    Only buckets with remaining_unredeemed > 0 are eligible. Caller is responsible
    for sufficiency — over-consumption simply reduces remaining_unredeemed to 0.
    """
    if amount <= 0:
        return
    accruals = [
        t for t in store.points_transactions.values()
        if t["member_id"] == member_id
        and t["kind"] == "ACCRUAL"
        and t.get("remaining_unredeemed") is not None
        and t["remaining_unredeemed"] > 0
        and t["id"] != exclude_id
        and t["points_delta"] > 0
    ]
    accruals.sort(key=lambda t: (t["posted_at"], t["id"]))
    left = amount
    for t in accruals:
        if left <= 0:
            return
        take = min(t["remaining_unredeemed"], left)
        t["remaining_unredeemed"] -= take
        left -= take
