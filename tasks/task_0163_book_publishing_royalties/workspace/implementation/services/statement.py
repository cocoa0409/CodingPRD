"""Statement engine: royalty escalator, reserve sizing/liquidation,
reconciliation waterfall, and the finalize/pay cascades.

All money in integer cents. Rounding is round-half-up (PRD §2.7).
"""
import db
from services.money import D, round_half_up, mul_round


# ---------------------------------------------------------------------------
# Helpers to read related state out of the in-memory store
# ---------------------------------------------------------------------------

def _period_records(period_id):
    return [r for r in db.sales_records.values() if r["period_id"] == period_id]


def _period_net_units(period_id):
    total = 0
    for r in _period_records(period_id):
        total += r["units_sold"] - r["units_returned"]
    return total


def _format_net_units(period_id):
    """Map format_id -> net units, only for formats that appear in the period."""
    by_fmt = {}
    for r in _period_records(period_id):
        by_fmt.setdefault(r["format_id"], 0)
        by_fmt[r["format_id"]] += r["units_sold"] - r["units_returned"]
    return by_fmt


def _contract_tiers(contract_id):
    tiers = [t for t in db.royalty_tiers.values() if t["contract_id"] == contract_id]
    tiers.sort(key=lambda t: t["lower_unit"])
    return tiers


# ---------------------------------------------------------------------------
# Tiered royalty escalator (PRD §3.7, calc tiered_royalty_escalator)
# ---------------------------------------------------------------------------

def _escalator_for_format(tiers, cum_before, net_units, list_price_cents):
    """Run one format's net units through the tier escalator from cum_before.

    Returns integer cents (segment-level round-half-up, accumulated).
    """
    gross = 0
    remaining = net_units
    pos = cum_before
    for t in tiers:
        if remaining <= 0:
            break
        lower = t["lower_unit"]
        upper = t["upper_unit"]
        seg_start = max(pos, lower - 1)
        seg_end = upper if upper is not None else pos + remaining
        avail = seg_end - seg_start
        if avail <= 0:
            continue
        take = min(remaining, avail)
        per_unit = D(t["rate"]) * D(list_price_cents)
        gross += round_half_up(per_unit * D(take))
        remaining -= take
        pos += take
    return gross


def gross_royalty(contract, period_id):
    """Per-format-then-sum gross royalty (PRD §3.7 per-format canonical order)."""
    cum_before = contract["lifetime_net_units"]
    tiers = _contract_tiers(contract["id"])
    fmt_net = _format_net_units(period_id)
    # Formats taken in ascending order of created_at (PRD §3.7).
    fmt_items = []
    for fid, net in fmt_net.items():
        fmt = db.formats.get(fid)
        if fmt is None:
            continue
        fmt_items.append((fmt, net))
    fmt_items.sort(key=lambda pair: (pair[0].get("created_at", ""), pair[0].get("_seq", 0)))
    total = 0
    for fmt, net in fmt_items:
        total += _escalator_for_format(tiers, cum_before, net, fmt["list_price_cents"])
    return total


# ---------------------------------------------------------------------------
# Reserve liquidation arithmetic (PRD §3.8, calc reserve_liquidation)
# ---------------------------------------------------------------------------

def actual_returns_units(contract_id, origin_sequence, finalizing_sequence):
    """Sum of units_returned in the half-open window (origin_seq, finalizing_seq]."""
    # Map period_id -> sequence for this contract.
    seq_by_period = {
        p["id"]: p["sequence"]
        for p in db.sales_periods.values()
        if p["contract_id"] == contract_id
    }
    total = 0
    for r in db.sales_records.values():
        seq = seq_by_period.get(r["period_id"])
        if seq is None:
            continue
        if origin_sequence < seq <= finalizing_sequence:
            total += r["units_returned"]
    return total


def liquidation_amounts(reserve, finalizing_sequence):
    """Return (consumed_cents, released_cents) for a reserve at finalize time.

    reserve_unit_value_cents is held at full precision (PRD §2.7). We realize
    that full precision by computing consumed_cents directly from the exact
    integer ratio reserve_held_cents/reserve_units, which is identical to
    round_half_up(reserve_unit_value_cents * charged) with no float drift.
    """
    origin_stmt = db.author_statements.get(reserve["origin_statement_id"])
    origin_seq = None
    if origin_stmt is not None:
        origin_period = db.sales_periods.get(origin_stmt["period_id"])
        if origin_period is not None:
            origin_seq = origin_period["sequence"]
    if origin_seq is None:
        origin_seq = reserve["eligible_sequence"] - 0  # fallback; should not happen
    returns = actual_returns_units(reserve["contract_id"], origin_seq, finalizing_sequence)
    charged = min(returns, reserve["reserve_units"])
    units = reserve["reserve_units"]
    if units > 0:
        consumed = round_half_up(D(reserve["reserve_held_cents"]) * D(charged) / D(units))
    else:
        consumed = 0
    released = reserve["reserve_held_cents"] - consumed
    return consumed, released


# ---------------------------------------------------------------------------
# Subsidiary income (PRD §3.4 / §3.9, calc subsidiary_author_income)
# ---------------------------------------------------------------------------

def registered_rights(contract_id):
    rights = [
        sr for sr in db.subsidiary_rights.values()
        if sr["contract_id"] == contract_id and sr["status"] == "REGISTERED"
    ]
    rights.sort(key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    return rights


# ---------------------------------------------------------------------------
# Full reconciliation snapshot (PRD §3.9 waterfall) — pure computation
# ---------------------------------------------------------------------------

def compute_snapshot(contract, period, committed):
    """Compute every monetary field for a statement.

    When committed=False this is the provisional generate-time snapshot
    (no state mutated). When committed=True the caller will apply the
    cascades after reading these figures; the figures themselves are the
    same arithmetic against current live state.

    Returns a dict of computed monetary fields plus the eligible reserve
    ids and credited right ids (so the finalize cascade can act on them).
    """
    period_id = period["id"]
    finalizing_seq = period["sequence"]

    gr = gross_royalty(contract, period_id)
    reserve_held = mul_round(gr, contract["reserve_pct"])
    royalty_credited = gr - reserve_held

    # Reserve releases: HELD reserves whose eligible_sequence <= finalizing seq.
    eligible_reserves = [
        rv for rv in db.returns_reserves.values()
        if rv["contract_id"] == contract["id"]
        and rv["status"] == "HELD"
        and rv["eligible_sequence"] <= finalizing_seq
    ]
    eligible_reserves.sort(key=lambda rv: (rv.get("created_at", ""), rv.get("_seq", 0)))
    reserve_released = 0
    reserve_plan = []  # (reserve, consumed, released)
    for rv in eligible_reserves:
        consumed, released = liquidation_amounts(rv, finalizing_seq)
        reserve_released += released
        reserve_plan.append((rv, consumed, released))

    # Subsidiary income: REGISTERED rights on this contract.
    rights = registered_rights(contract["id"])
    subsidiary_income = 0
    for sr in rights:
        subsidiary_income += sr["author_income_cents"]

    period_earnings = royalty_credited + reserve_released + subsidiary_income
    advance_recouped = min(period_earnings, contract["unrecouped_advance_cents"])
    if advance_recouped < 0:
        advance_recouped = 0
    payable_before = period_earnings - advance_recouped
    agent_commission = mul_round(payable_before, contract["agent_commission_pct"])
    net_to_author = payable_before - agent_commission  # tax applied only at pay

    return {
        "gross_royalty_cents": gr,
        "reserve_held_cents": reserve_held,
        "royalty_credited_cents": royalty_credited,
        "reserve_released_cents": reserve_released,
        "subsidiary_income_cents": subsidiary_income,
        "period_earnings_cents": period_earnings,
        "advance_recouped_cents": advance_recouped,
        "payable_before_commission_cents": payable_before,
        "agent_commission_cents": agent_commission,
        "net_to_author_cents": net_to_author,
        "_reserve_plan": reserve_plan,
        "_credited_rights": rights,
        "_period_net_units": _period_net_units(period_id),
    }
