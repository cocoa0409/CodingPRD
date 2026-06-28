"""CreditPack derived fields, lazy expiry, and refund calculation.

PRD §3.3 (pack lifecycle), §3.9 (refund amount), scaffold calculations
pack_refund_amount.
"""
from decimal import Decimal

from clock import clock
from db import db, touch
from util import round_half_up


def remaining_credits(pack):
    """CLASS_PACK: purchased - consumed (never below zero).
    MEMBERSHIP: sentinel -1 (unlimited). PRD §3.3."""
    if pack["kind"] == "MEMBERSHIP":
        return -1
    rem = pack["purchased_credits"] - pack["consumed_credits"]
    return rem if rem > 0 else 0


def lazy_expire(pack):
    """Lazily transition ACTIVE/EXHAUSTED -> EXPIRED when clock >= expires_at
    (PRD §3.3, §3.11). Returns True if a transition occurred."""
    if pack["status"] in ("ACTIVE", "EXHAUSTED") and clock.now() >= pack["expires_at"]:
        pack["status"] = "EXPIRED"
        touch(pack)
        return True
    return False


def is_chargeable(pack):
    """A pack is chargeable when ACTIVE, not expired, and either MEMBERSHIP or a
    CLASS_PACK with >= 1 remaining credit (PRD §3.4 charge resolution)."""
    lazy_expire(pack)
    if pack["status"] != "ACTIVE":
        return False
    if clock.now() >= pack["expires_at"]:
        return False
    if pack["kind"] == "MEMBERSHIP":
        return True
    return remaining_credits(pack) >= 1


def debit_one(pack):
    """Debit one credit from a CLASS_PACK; MEMBERSHIP unchanged.
    If CLASS_PACK remaining hits 0, transition ACTIVE -> EXHAUSTED. PRD §3.4."""
    if pack["kind"] == "CLASS_PACK":
        pack["consumed_credits"] += 1
        if remaining_credits(pack) == 0 and pack["status"] == "ACTIVE":
            pack["status"] = "EXHAUSTED"
        touch(pack)


def restore_one(pack):
    """Restore one credit to a CLASS_PACK (conserved-credit invariant). An
    EXHAUSTED pack returns to ACTIVE when remaining rises above zero and the
    clock is still before expires_at. PRD §3.2 / §3.5."""
    if pack["kind"] != "CLASS_PACK":
        return
    if pack["consumed_credits"] > 0:
        pack["consumed_credits"] -= 1
    if pack["status"] == "EXHAUSTED" and remaining_credits(pack) > 0 and clock.now() < pack["expires_at"]:
        pack["status"] = "ACTIVE"
    touch(pack)


def _days_between(start, end):
    """Whole-day count between two instants (PRD §3.9: counting the start day,
    excluding the end day). Computed from the calendar-date difference."""
    return (end.date() - start.date()).days


def refund_amount(pack):
    """Compute the refund per PRD §3.9 / scaffold pack_refund_amount.

    EXPIRED at refund time -> 0 regardless of kind.
    CLASS_PACK (unused_value): round_half_up(price/purchased) * remaining.
    MEMBERSHIP (prorata_time): round_half_up(price * unused_days / total_days).
    """
    if pack["status"] == "EXPIRED":
        return 0

    if pack["kind"] == "CLASS_PACK":
        purchased = pack["purchased_credits"]
        if purchased <= 0:
            return 0
        unit_value = round_half_up(Decimal(pack["price_cents"]) / Decimal(purchased))
        return unit_value * remaining_credits(pack)

    # MEMBERSHIP
    total_days = _days_between(pack["activated_at"], pack["expires_at"])
    if total_days <= 0:
        return 0
    used_days = _days_between(pack["activated_at"], clock.now())
    if used_days < 0:
        used_days = 0
    if used_days > total_days:
        used_days = total_days
    unused_days = total_days - used_days
    return round_half_up(Decimal(pack["price_cents"]) * Decimal(unused_days) / Decimal(total_days))


def expire_all_due():
    """Sweep all packs for lazy expiry (called on clock advance / member read
    contexts). Idempotent."""
    for pack in db.credit_packs.values():
        lazy_expire(pack)
