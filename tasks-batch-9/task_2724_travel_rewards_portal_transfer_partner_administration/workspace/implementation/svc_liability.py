"""The seven pinned steps of the points liability snapshot (PRD 3.11)."""

from core import DB, add_days, dec, ordered, parse_dt, round_half_up

FALLBACK_BLENDED_COST = 1000
EARN_TYPES = ("EARN_BASE", "EARN_BONUS")


def _entries_at_or_before(as_of):
    return [r for r in DB["ledger"].values() if parse_dt(r["occurred_at"]) <= as_of]


def gross_outstanding(as_of):
    """Step one: every entry at or before the cut-off, regardless of entry_type."""
    return sum(r["points_delta"] for r in _entries_at_or_before(as_of))


def _account_outstanding(account_id, as_of):
    return sum(
        r["points_delta"]
        for r in DB["ledger"].values()
        if r["account_id"] == account_id and parse_dt(r["occurred_at"]) <= as_of
    )


def _is_dormant(account_id, as_of):
    """No EARN_BASE and no EARN_BONUS entry strictly after as_of minus 365 days."""
    floor_instant = add_days(as_of, -365)
    for entry in DB["ledger"].values():
        if entry["account_id"] != account_id:
            continue
        if entry["entry_type"] not in EARN_TYPES:
            continue
        occurred = parse_dt(entry["occurred_at"])
        if occurred <= as_of and occurred > floor_instant:
            return False
    return True


def dormant_outstanding(as_of):
    """Step two: split the total by dormancy, walking accounts in created_at order."""
    total = 0
    for account in ordered("accounts"):
        if _is_dormant(account["id"], as_of):
            total += _account_outstanding(account["id"], as_of)
    return total


def breakage_rates(gross_points):
    """Step three: the tier is keyed on the gross figure only."""
    if gross_points < 1000000:
        base = 1200
    elif gross_points < 10000000:
        base = 1800
    else:
        base = 2400
    dormant = min(base + 1000, 5000)
    return base, dormant


def blended_cost_per_1k(method, as_of):
    """Step four: the two methods read disjoint input sets."""
    numerator = 0
    denominator = 0
    for order in DB["orders"].values():
        if method == "COST_BASIS":
            if order["settlement_status"] != "SETTLED":
                continue
            if not order.get("settled_at"):
                continue
            if parse_dt(order["settled_at"]) > as_of:
                continue
            cost = order.get("issuer_cost_final_cents")
            if cost is None:
                cost = 0
        else:
            if order["fulfillment_status"] not in ("CONFIRMED", "TICKETED", "REFUNDED"):
                continue
            if parse_dt(order["created_at"]) > as_of:
                continue
            cost = order.get("issuer_cost_provisional_cents") or 0
        numerator += cost
        denominator += order["points_debited"]
    if denominator == 0:
        return FALLBACK_BLENDED_COST
    return round_half_up(dec(numerator) * 1000 / dec(denominator))


def _bucket_value(points, blended):
    return round_half_up(dec(points) * dec(blended) / dec(1000))


def compute(method, as_of_iso):
    as_of = parse_dt(as_of_iso)
    gross_points = gross_outstanding(as_of)
    dormant_points = dormant_outstanding(as_of)
    non_dormant_points = gross_points - dormant_points
    base_rate, dormant_rate = breakage_rates(gross_points)
    blended = blended_cost_per_1k(method, as_of)

    non_dormant_value = _bucket_value(non_dormant_points, blended)
    dormant_value = _bucket_value(dormant_points, blended)
    gross_liability = non_dormant_value + dormant_value

    breakage = round_half_up(dec(non_dormant_value) * dec(base_rate) / dec(10000))
    breakage += round_half_up(dec(dormant_value) * dec(dormant_rate) / dec(10000))

    net = gross_liability - breakage
    if gross_liability == 0:
        effective_bps = 0
    else:
        effective_bps = round_half_up(dec(breakage) * dec(10000) / dec(gross_liability))

    return {
        "gross_outstanding_points": gross_points,
        "dormant_outstanding_points": dormant_points,
        "blended_cost_per_1k_cents": blended,
        "effective_breakage_rate_bps": effective_bps,
        "gross_liability_cents": gross_liability,
        "breakage_credit_cents": breakage,
        "net_liability_cents": net,
    }
