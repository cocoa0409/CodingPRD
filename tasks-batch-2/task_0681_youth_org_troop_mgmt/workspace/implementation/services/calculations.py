"""Calculation rules (PRD §2.8, §3.3, §3.7, §3.7 sweep; SCAFFOLD §1.3)."""
from datetime import date
from decimal import Decimal

from db import db
from util import round_half_up

# Dues proration constant (SCAFFOLD calculations.dues_proration).
FULL_DUES_MONTHS = 9

# Tiered commission schedule (PRD §3.7 / SCAFFOLD fundraiser_troop_commission).
TIER1_MAX = 100
TIER2_MAX = 500
RATE1 = Decimal("0.15")
RATE2 = Decimal("0.20")
RATE3 = Decimal("0.25")


def dues_proration(base_cents, issued_on_iso):
    """Compute prorated dues in integer cents (PRD §3.3).

    months_remaining = 12 - (month_of(issued_on) - 1), clamped to [1, 12].
    If months_remaining >= 9 -> full base (no proration discount).
    Else -> round_half_up(base * months_remaining / 12).
    """
    month = _month_of(issued_on_iso)
    months_remaining = 12 - (month - 1)
    if months_remaining < 1:
        months_remaining = 1
    if months_remaining > 12:
        months_remaining = 12

    if months_remaining >= FULL_DUES_MONTHS:
        return base_cents
    # Round the single proration product once, half-up.
    return round_half_up(Decimal(base_cents) * Decimal(months_remaining) / Decimal(12))


def _month_of(issued_on_iso):
    """Parse the month number (1-12) from an ISO YYYY-MM-DD date."""
    from errors import err, ERR_INVALID_REQUEST

    if not isinstance(issued_on_iso, str):
        raise err(ERR_INVALID_REQUEST, "issued_on must be an ISO date string")
    try:
        parsed = date.fromisoformat(issued_on_iso.strip())
    except ValueError:
        raise err(ERR_INVALID_REQUEST, f"invalid issued_on date: {issued_on_iso}")
    return parsed.month


def tiered_commission(units, unit_price_cents):
    """Marginal tiered troop commission, integer cents (PRD §3.7).

    Units 1..100 earn 15% of unit price each; 101..500 earn 20%; >500 earn 25%.
    Sum the three tier contributions, then round half-up exactly once.
    """
    t1 = min(units, TIER1_MAX)
    t2 = min(max(units - TIER1_MAX, 0), TIER2_MAX - TIER1_MAX)
    t3 = max(units - TIER2_MAX, 0)
    price = Decimal(unit_price_cents)
    raw = (
        Decimal(t1) * price * RATE1
        + Decimal(t2) * price * RATE2
        + Decimal(t3) * price * RATE3
    )
    return round_half_up(raw)


def settled_troop_dues(troop_id):
    """Settled TROOP_DUES total used by the recharter gate (PRD §3.7).

    Counts only commissions from FILLED orders together with posted payments
    (and recharter reversals/debits). The settled view excludes commission
    credits that belong to orders still in PLACED status.
    """
    total = 0
    for e in db.fund_ledger_entries.values():
        if e["account"] != "TROOP_DUES" or e["troop_id"] != troop_id:
            continue
        kind = e["source_kind"]
        if kind == "FUNDRAISER_ORDER":
            # Only count the commission credit if its order is FILLED.
            order = db.fundraiser_orders.get(e["source_ref_id"])
            if order is not None and order["status"] == "FILLED":
                total += e["amount_cents"]
            # PLACED-order commissions are not settled; skip.
        else:
            # PAYMENT credits, RECHARTER debits, and REVERSAL entries all settle.
            total += e["amount_cents"]
    return total
