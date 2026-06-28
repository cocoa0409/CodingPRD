"""Booking credit waterfall and refund (PRD §3.5 booking_credit_debit).

Bucket order is PINNED: subscription granted credits first, then the member's
ACTIVE CreditPacks ordered by (expires_at ASC, created_at ASC). No id is ever
used for ordering. The debit is computed-and-applied atomically: if the wallets
cannot cover the cost, nothing is debited and ERR_INSUFFICIENT_CREDITS is raised.
"""

from clock import parse_iso8601

import errors
from db import db
from helpers import touch
from services.compute import recompute_credit_balance_by_member_id


def _member_active_subscription(member_id):
    for sub in db.subscriptions.values():
        if sub["member_id"] == member_id and sub["status"] != "CANCELLED":
            return sub
    return None


def _active_packs_sorted(member_id):
    packs = [
        p for p in db.credit_packs.values()
        if p["member_id"] == member_id and p["status"] == "ACTIVE"
    ]
    # expires_at ASC, then created_at ASC (tie-break). Never id.
    return sorted(
        packs,
        key=lambda p: (parse_iso8601(p["expires_at"]), parse_iso8601(p["created_at"])),
    )


def debit_credits(member_id, cost):
    """Apply the waterfall. Returns (credits_charged, credit_source, debit_plan).

    Raises ERR_INSUFFICIENT_CREDITS with no mutation if the wallets cannot cover
    the cost. debit_plan records what was taken from where so a later cancel can
    refund to source.
    """
    sub = _member_active_subscription(member_id)
    take_sub = 0
    if sub is not None and sub["status"] == "ACTIVE":
        take_sub = min(cost, sub["granted_credits_remaining"])
    remaining = cost - take_sub

    # Plan the pack draws without mutating yet (atomicity).
    packs = _active_packs_sorted(member_id)
    planned = []  # list of (pack_id, take)
    for pack in packs:
        if remaining <= 0:
            break
        take = min(remaining, pack["remaining_credits"])
        if take > 0:
            planned.append((pack["id"], take))
            remaining -= take

    if remaining > 0:
        raise errors.ApiError(
            errors.ERR_INSUFFICIENT_CREDITS, 422,
            "Credit waterfall cannot cover the service cost")

    # Commit: subscription draw first.
    if take_sub > 0:
        sub["granted_credits_remaining"] -= take_sub
        touch(sub)
    # Commit: pack draws.
    pack_debits = []
    for pack_id, take in planned:
        pack = db.credit_packs[pack_id]
        pack["remaining_credits"] -= take
        if pack["remaining_credits"] == 0:
            pack["status"] = "DEPLETED"
        touch(pack)
        pack_debits.append({"pack_id": pack_id, "credits": take})

    if take_sub == cost:
        credit_source = "SUBSCRIPTION"
    elif take_sub == 0:
        credit_source = "PACK"
    else:
        credit_source = "SPLIT"

    debit_plan = {
        "subscription_id": sub["id"] if take_sub > 0 else None,
        "subscription_credits": take_sub,
        "pack_debits": pack_debits,
    }

    recompute_credit_balance_by_member_id(member_id)
    return cost, credit_source, debit_plan


def refund_credits(member_id, debit_plan):
    """Refund the charged credits to their original source (PRD §3.5 cancel).

    Subscription portion is added back to granted_credits_remaining up to what
    was taken; pack portions return to the originating pack, except packs now in
    REFUNDED/DEPLETED/EXPIRED status are skipped and that portion is forfeited.
    """
    sub_credits = debit_plan.get("subscription_credits", 0)
    sub_id = debit_plan.get("subscription_id")
    if sub_credits > 0 and sub_id is not None:
        sub = db.subscriptions.get(sub_id)
        if sub is not None:
            sub["granted_credits_remaining"] += sub_credits
            touch(sub)
    for pd in debit_plan.get("pack_debits", []):
        pack = db.credit_packs.get(pd["pack_id"])
        if pack is None:
            continue
        # Skip packs no longer ACTIVE (REFUNDED/DEPLETED/EXPIRED) — forfeited.
        if pack["status"] != "ACTIVE":
            continue
        pack["remaining_credits"] += pd["credits"]
        touch(pack)
    recompute_credit_balance_by_member_id(member_id)
