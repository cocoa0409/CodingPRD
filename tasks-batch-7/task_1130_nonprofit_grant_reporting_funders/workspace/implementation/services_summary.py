"""Computed reads and submit gating: BvA rows, indirect pool, match progress,
burn projections, pacing ratio, variance breach detection (PRD 3.6 / 3.4)."""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import services as S
from db import store
from util import fmt_dt, round_half_up_2, to_dec, variance_pct

TRAILING_WINDOW_PERIODS = 1


def match_totals(grant):
    """(verified_only_cents, pledged_inclusive_cents, verified_pct, pledged_pct)."""
    verified = 0
    inclusive = 0
    for m in S.grant_matches(grant["id"]):
        rv = m["recognized_value_cents"]
        if m["status"] == "VERIFIED":
            verified += rv
        if m["status"] in ("PLEDGED", "DOCUMENTED", "VERIFIED"):
            inclusive += rv
    req = grant["required_match_cents"]
    if req == 0:
        return verified, inclusive, None, None
    v_pct = round_half_up_2(Decimal(verified) / Decimal(req) * Decimal(100))
    p_pct = round_half_up_2(Decimal(inclusive) / Decimal(req) * Decimal(100))
    return verified, inclusive, v_pct, p_pct


def indirect_pool(grant):
    """direct_base = ACTIVE allocations on non-INDIRECT lines; de minimis 10%
    for FEDERAL funders when the negotiated rate is unset (0); floor; cap min."""
    lines_by_id = {l["id"]: l for l in S.grant_lines(grant["id"])}
    direct_base = 0
    for _, a in S.active_allocations(grant["id"]):
        line = lines_by_id.get(a["budget_line_id"])
        if line is not None and line["category"] != "INDIRECT":
            direct_base += a["amount_cents"]
    rate = to_dec(grant["indirect_rate_pct"])
    if rate == 0:
        funder = store["funders"].get(grant["funder_id"])
        if funder is not None and funder["funder_type"] == "FEDERAL":
            rate = Decimal(S.DE_MINIMIS_INDIRECT_PCT)
        else:
            rate = Decimal(0)
    uncapped = int(
        (Decimal(direct_base) * rate / Decimal(100)).to_integral_value(rounding=ROUND_FLOOR)
    )
    cap = grant["indirect_cap_cents"]
    if cap is not None:
        return min(uncapped, cap)
    return uncapped


def bva_rows(grant):
    """One row per (budget line, report period) with period-only and
    cumulative variants."""
    rows = []
    reports = S.grant_reports(grant["id"])
    for line in S.grant_lines(grant["id"]):
        for rep in reports:
            idx = rep["period_index"]
            pa = S.period_actual(line, rep)
            pb = S.period_budget(line, idx)
            ca = S.cumulative_actual(line, rep)
            cb = S.cumulative_budget(line, idx)
            rows.append({
                "budget_line_id": line["id"],
                "category": line["category"],
                "period_index": idx,
                "period_type": rep["period_type"],
                "period_start": rep["period_start"],
                "period_end": rep["period_end"],
                "period_actual_cents": pa,
                "period_budget_cents": pb,
                "period_variance_pct": variance_pct(pa, pb),
                "cumulative_actual_cents": ca,
                "cumulative_budget_cents": cb,
                "cumulative_variance_pct": variance_pct(ca, cb),
            })
    return rows


def burn_projection(grant):
    """Trailing-average (window 1) and cumulative-average burn plus pacing."""
    reports = S.grant_reports(grant["id"])
    total_periods = len(reports)
    closed = [r for r in reports if r["status"] == "ACCEPTED"]
    if not closed or total_periods == 0:
        return 0, 0, None
    window = closed[-TRAILING_WINDOW_PERIODS:]
    totals = [S.period_total(grant["id"], r) for r in window]
    trailing_avg = Decimal(sum(totals)) / Decimal(len(totals))
    burn_trailing = int(
        (trailing_avg * Decimal(total_periods)).to_integral_value(rounding=ROUND_HALF_UP)
    )
    elapsed = len(closed)
    burn_cumulative = int(
        (Decimal(grant["total_expended_cents"]) / Decimal(elapsed) * Decimal(total_periods))
        .to_integral_value(rounding=ROUND_HALF_UP)
    )
    denom = Decimal(grant["award_amount_cents"]) * Decimal(elapsed) / Decimal(total_periods)
    if denom == 0:
        pacing = None
    else:
        pacing = round_half_up_2(Decimal(grant["total_expended_cents"]) / denom)
    return burn_trailing, burn_cumulative, pacing


def compute_summary(grant):
    verified, inclusive, v_pct, p_pct = match_totals(grant)
    burn_t, burn_c, pacing = burn_projection(grant)
    rows = []
    for row in bva_rows(grant):
        row = dict(row)
        row["period_start"] = fmt_dt(row["period_start"])
        row["period_end"] = fmt_dt(row["period_end"])
        rows.append(row)
    return {
        "grant_id": grant["id"],
        "status": grant["status"],
        "total_expended_cents": grant["total_expended_cents"],
        "indirect_pool_cents": indirect_pool(grant),
        "match_verified_only_cents": verified,
        "match_pledged_inclusive_cents": inclusive,
        "match_verified_only_pct": v_pct,
        "match_pledged_inclusive_pct": p_pct,
        "burn_trailing_cents": burn_t,
        "burn_cumulative_cents": burn_c,
        "pacing_ratio": pacing,
        "bva": rows,
    }


def breaching_lines(grant, rep):
    """Lines whose period_only |variance_pct| >= grant.variance_threshold_pct.
    Zero-activity lines (period actuals == 0) are exempt; null variance
    (zero period budget) never breaches."""
    threshold = to_dec(grant["variance_threshold_pct"])
    out = []
    for line in S.grant_lines(grant["id"]):
        pa = S.period_actual(line, rep)
        if pa <= 0:
            continue
        pb = S.period_budget(line, rep["period_index"])
        pct = variance_pct(pa, pb)
        if pct is None:
            continue
        if abs(to_dec(pct)) >= threshold:
            out.append(line)
    return out
