"""Settlement-period revenue calculations."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import List, Tuple

from pv_ops.store import Store
from pv_ops.utils import D, parse_dt, round_half_up


def metering_lines_for(store: Store, settlement_period_id: str) -> List[dict]:
    rows = [m for m in store.metering_records.values() if m.get("settlement_period_id") == settlement_period_id]
    # Stable order by window_start ASC, then by id for tie-breaks
    def key(m):
        return (parse_dt(m["window_start"], "window_start"), m["id"])
    rows.sort(key=key)
    return rows


def compute_provisional_revenue(store: Store, period: dict) -> Decimal:
    """Sum( round(line, 2) ) — per-line round, then sum. No second round."""
    station = store.stations.get(period["station_id"])
    fit = D(station["feed_in_tariff_cny_per_kwh"])
    total = D(0)
    for m in metering_lines_for(store, period["id"]):
        if m["pricing_channel"] == "FEED_IN":
            line = D(m["on_grid_kwh"]) * fit
        else:
            mp = m.get("market_price_cny_per_kwh")
            if mp is None:
                # Should have been caught at metering creation time
                continue
            line = D(m["on_grid_kwh"]) * D(mp)
        total += round_half_up(line, 2)
    return total


def compute_final_revenue(store: Store, period: dict) -> Decimal:
    """Adjusted line-by-line then summed; final round to 2 places."""
    station = store.stations.get(period["station_id"])
    fit = D(station["feed_in_tariff_cny_per_kwh"])
    lines = metering_lines_for(store, period["id"])
    raw_total = sum((D(m["on_grid_kwh"]) for m in lines), start=D(0))
    confirmed = D(period["grid_company_confirmed_kwh"])
    if raw_total == 0:
        ratio = D(1)
    else:
        ratio = confirmed / raw_total

    adjusted_total = D(0)
    for m in lines:
        adjusted_kwh = round_half_up(D(m["on_grid_kwh"]) * ratio, 3)
        if m["pricing_channel"] == "FEED_IN":
            price = fit
        else:
            price = D(m["market_price_cny_per_kwh"])
        line_amount = round_half_up(adjusted_kwh * price, 2)
        adjusted_total += line_amount
    return round_half_up(adjusted_total, 2)


def active_investor_shares(store: Store, period: dict) -> List[dict]:
    """Return shares whose effective range overlaps the period (PRD §3.6)."""
    station_id = period["station_id"]
    p_start = parse_dt(period["period_start"], "period_start")
    p_end = parse_dt(period["period_end"], "period_end")
    rows = []
    for s in store.investor_shares.values():
        if s.get("station_id") != station_id:
            continue
        ef = parse_dt(s["effective_from"], "effective_from")
        et_raw = s.get("effective_to")
        et = parse_dt(et_raw, "effective_to") if et_raw else None
        # active iff ef < period_end AND (et is null OR et > period_start)
        if not (ef < p_end):
            continue
        if et is not None and not (et > p_start):
            continue
        rows.append(s)
    rows.sort(key=lambda s: (s["investor_name"], s["id"]))
    return rows


def distribute_revenue(store: Store, period: dict, final_revenue_cny: Decimal) -> List[dict]:
    """Return a list of dicts representing RevenueDistribution rows (not yet inserted)."""
    shares = active_investor_shares(store, period)
    bps_sum = sum(int(s["share_basis_points"]) for s in shares)
    if bps_sum != 10000:
        raise _InvestorSharesInvalid()

    cents_total = int(round_half_up(final_revenue_cny * D(100), 0))
    allocations: List[Tuple[dict, int]] = []
    acc = 0
    for s in shares:
        raw = int(round_half_up(D(cents_total) * D(s["share_basis_points"]) / D(10000), 0))
        allocations.append((s, raw))
        acc += raw
    drift = cents_total - acc
    if drift != 0 and allocations:
        last_share, last_raw = allocations[-1]
        allocations[-1] = (last_share, last_raw + drift)

    out_rows = []
    for s, raw_cents in allocations:
        out_rows.append(
            {
                "settlement_period_id": period["id"],
                "investor_share_id": s["id"],
                "investor_name": s["investor_name"],
                "share_basis_points": int(s["share_basis_points"]),
                "amount_cny": float(round_half_up(D(raw_cents) / D(100), 2)),
            }
        )
    return out_rows


def overlapping_confirmed_exists(store: Store, period: dict) -> bool:
    p_start = parse_dt(period["period_start"], "period_start")
    p_end = parse_dt(period["period_end"], "period_end")
    for other in store.settlement_periods.values():
        if other["id"] == period["id"]:
            continue
        if other.get("station_id") != period["station_id"]:
            continue
        # Overlap check applies only to CONFIRMED/INVOICED periods (those with a fixed window claim)
        if other.get("state") not in ("CONFIRMED", "INVOICED"):
            continue
        os_dt = parse_dt(other["period_start"], "period_start")
        oe_dt = parse_dt(other["period_end"], "period_end")
        # half-open interval intersection
        if p_start < oe_dt and os_dt < p_end:
            return True
    return False


class _InvestorSharesInvalid(Exception):
    pass


def distributions_for(store: Store, settlement_period_id: str) -> List[dict]:
    return [d for d in store.revenue_distributions.values() if d.get("settlement_period_id") == settlement_period_id]
