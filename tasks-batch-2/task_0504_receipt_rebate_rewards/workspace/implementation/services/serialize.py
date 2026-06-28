"""Serialize stored entities to API output dicts.

Strips internal-only fields (e.g. _seq) and, for Member, injects the derived
wallet balances (PRD §2.6).
"""
from services.wallet import compute_balances


def _public(entity):
    """Return a copy of the entity without internal underscore-prefixed keys."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def merchant_out(store, m):
    return _public(m)


def offer_out(store, o):
    return _public(o)


def member_out(store, m):
    out = _public(m)
    out.update(compute_balances(store, m["id"]))
    return out


def clickthrough_out(store, c):
    return _public(c)


def receipt_scan_out(store, r):
    return _public(r)


def reward_claim_out(store, c):
    return _public(c)


def cashout_out(store, c):
    return _public(c)


def referral_out(store, r):
    return _public(r)


def bonus_streak_out(store, b):
    return _public(b)


def ledger_entry_out(store, e):
    return _public(e)


def return_event_out(store, e):
    return _public(e)
