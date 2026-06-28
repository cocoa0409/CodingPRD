"""Credit wallet reconciliation (PRD §2.6, calc credit_wallet_balance).

held/consumed are SUMS over the wallet's bookings; available is derived from
them in a pinned order so a circular read never occurs:
  STEP 1  held_credits     = sum(credit_cost where funding_id==wallet AND credit_status==HELD)
  STEP 2  consumed_credits = sum(credit_cost where funding_id==wallet AND credit_status IN {CONSUMED, FORFEITED})
  STEP 3  granted_credits  = (Membership: included + carried rollover) | (CreditPack: pack_credits)
  STEP 4  available_credits = max(0, granted - held - consumed)
"""
from db import store


def _bookings_for(wallet_id):
    return [b for b in store.bookings.values() if b.get("funding_id") == wallet_id]


def _held_sum(wallet_id):
    return sum(b["credit_cost"] for b in _bookings_for(wallet_id)
               if b["credit_status"] == "HELD")


def _consumed_sum(wallet_id):
    return sum(b["credit_cost"] for b in _bookings_for(wallet_id)
               if b["credit_status"] in ("CONSUMED", "FORFEITED"))


def membership_wallet_fields(m):
    held = _held_sum(m["id"])
    # consumed_credits resets to 0 on renewal (PRD §3.7): subtract the consumed
    # baseline captured at the last renewal so prior-cycle consumption is excluded
    # without ever mutating booking records.
    raw_consumed = _consumed_sum(m["id"])
    baseline = m.get("consumed_baseline", 0)
    consumed = max(0, raw_consumed - baseline)
    granted = m["granted_credits"]
    available = max(0, granted - held - consumed)
    return {
        "granted_credits": granted,
        "held_credits": held,
        "consumed_credits": consumed,
        "available_credits": available,
    }


def creditpack_wallet_fields(p):
    held = _held_sum(p["id"])
    consumed = _consumed_sum(p["id"])
    granted = p["pack_credits"]
    available = max(0, granted - held - consumed)
    return {
        "granted_credits": granted,
        "held_credits": held,
        "consumed_credits": consumed,
        "available_credits": available,
    }


def wallet_available(funding_source, wallet):
    """available_credits for the given wallet record."""
    if funding_source == "MEMBERSHIP":
        return membership_wallet_fields(wallet)["available_credits"]
    return creditpack_wallet_fields(wallet)["available_credits"]


def reconcile_creditpack_status(pack):
    """Bounce CreditPack ACTIVE<->DEPLETED on available_credits, never touch EXPIRED.

    (scaffold CreditPack state machine: informational depletion; EXPIRED terminal.)
    """
    if pack["status"] == "EXPIRED":
        return
    avail = creditpack_wallet_fields(pack)["available_credits"]
    if avail == 0:
        pack["status"] = "DEPLETED"
    else:
        pack["status"] = "ACTIVE"
