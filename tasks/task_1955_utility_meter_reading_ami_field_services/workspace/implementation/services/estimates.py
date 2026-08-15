"""estimate_read_value calculation (TRAILING_AVERAGE / SAME_PERIOD_LAST_YEAR)."""
from datetime import timedelta
from fractions import Fraction

from db import db
from util import parse_dt, parse_date, days_between, round_half_up_decimal

MAX_CONSECUTIVE_ESTIMATES = 3
MIN_TRAILING_VALIDATED_READS = 2
TRAILING_HISTORY_DAYS = 365


def validated_reads(account_id):
    return [
        r for r in db.reads.values()
        if r["service_account_id"] == account_id and r["read_status"] == "VALIDATED"
    ]


def trailing_history_count(account_id, now):
    """VALIDATED reads with read_at inside the trailing 365 days before now."""
    cutoff = now - timedelta(days=TRAILING_HISTORY_DAYS)
    return sum(
        1 for r in validated_reads(account_id)
        if cutoff <= parse_dt(r["read_at"]) <= now
    )


def _latest_and_prior(account_id):
    """Latest validated read and the validated read with greatest read_at strictly
    before the latest one's read_at."""
    reads = validated_reads(account_id)
    if not reads:
        return None, None
    latest = max(reads, key=lambda r: (parse_dt(r["read_at"]), r["_seq"]))
    d_l = parse_dt(latest["read_at"])
    priors = [r for r in reads if parse_dt(r["read_at"]) < d_l]
    prior = None
    if priors:
        prior = max(priors, key=lambda r: (parse_dt(r["read_at"]), r["_seq"]))
    return latest, prior


def _trailing_average_value(account_id, period):
    latest, prior = _latest_and_prior(account_id)
    v_l = latest["read_value"]
    d_l = parse_dt(latest["read_at"])
    close = parse_date(period["read_window_close_date"])
    days_open = days_between(close, d_l)
    if prior is None:
        return v_l  # degenerate: no strictly earlier validated read
    v_p = prior["read_value"]
    d_p = parse_dt(prior["read_at"])
    span = days_between(d_l, d_p)
    if span <= 0:
        return v_l  # degenerate: same-day reads carry no rate information
    avg_daily = Fraction(v_l - v_p, span)  # full precision, no intermediate rounding
    estimate = v_l + int(round_half_up_decimal(avg_daily * days_open))
    return estimate


def estimate_value(account, period):
    """Returns (value, method_used). Method fallback is pinned and observable."""
    method = account["estimation_method"]
    if method == "SAME_PERIOD_LAST_YEAR":
        close = parse_date(period["read_window_close_date"])
        year = close.year - 1
        cands = [
            r for r in validated_reads(account["id"])
            if (lambda d: d.year == year and d.month == close.month)(
                parse_dt(r["read_at"]).date()
            )
        ]
        if len(cands) >= 2:
            latest, _ = _latest_and_prior(account["id"])
            spread = max(r["read_value"] for r in cands) - min(r["read_value"] for r in cands)
            return latest["read_value"] + spread, "SAME_PERIOD_LAST_YEAR"
        # pinned fallback
        return _trailing_average_value(account["id"], period), "TRAILING_AVERAGE"
    return _trailing_average_value(account["id"], period), "TRAILING_AVERAGE"
