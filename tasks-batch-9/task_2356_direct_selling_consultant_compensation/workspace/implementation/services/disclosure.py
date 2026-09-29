"""Income disclosure population selection and distribution metrics (PRD 3.9)."""

from common import parse_dt, rhu
from db import db
from services.commission import active_statements
from services.genealogy import by_created

BUCKET_BOUNDS = ((0, 0), (1, 9999), (10000, 49999), (50000, None))


def _ceil_div(numerator, denominator):
    return -((-int(numerator)) // int(denominator))


def population_earnings(run, plan, period, basis):
    """Ascending list of per-member gross earnings for the chosen basis."""
    actives = active_statements(run["id"])
    by_consultant = {}
    for statement in actives:
        by_consultant[statement["consultant_id"]] = statement

    earnings = []
    if basis == "PAID_ONLY":
        for statement in actives:
            if statement["payout_status"] == "PAID":
                earnings.append(int(statement["gross_commission_cents"]))
    else:  # ALL_ENROLLED
        period_end = parse_dt(period["period_end"])
        for consultant in by_created(list(db.consultants.values())):
            if consultant["compensation_plan_id"] != plan["id"]:
                continue
            if consultant["status"] == "TERMINATED":
                continue
            completed = parse_dt(consultant.get("enrollment_completed_at") or "")
            if completed is None or period_end is None or not (completed < period_end):
                continue
            statement = by_consultant.get(consultant["id"])
            earnings.append(int(statement["gross_commission_cents"]) if statement else 0)
    earnings.sort()
    return earnings


def metrics(earnings):
    n = len(earnings)
    total = sum(earnings)
    zero_count = len([e for e in earnings if e == 0])

    if n == 0:
        return {
            "population_count": 0,
            "zero_earner_count": 0,
            "total_earnings_cents": 0,
            "median_earnings_cents": 0,
            "mean_earnings_cents": 0,
            "p90_earnings_cents": 0,
            "top_decile_share_bp": 0,
            "distribution_buckets": [
                {
                    "lower_cents": lower,
                    "upper_cents": upper,
                    "consultant_count": 0,
                    "share_bp": 0,
                }
                for lower, upper in BUCKET_BOUNDS
            ],
        }

    mean = rhu(total, n)
    if n % 2 == 1:
        median = earnings[(n - 1) // 2]
    else:
        median = rhu(earnings[n // 2 - 1] + earnings[n // 2], 2)

    p90_index = _ceil_div(90 * n, 100) - 1
    if p90_index < 0:
        p90_index = 0
    if p90_index > n - 1:
        p90_index = n - 1
    p90 = earnings[p90_index]

    decile_size = max(1, _ceil_div(n, 10))
    top_total = sum(earnings[n - decile_size:])
    top_share_bp = 0 if total == 0 else rhu(top_total * 10000, total)

    buckets = []
    for lower, upper in BUCKET_BOUNDS:
        if upper is None:
            count = len([e for e in earnings if e >= lower])
        else:
            count = len([e for e in earnings if lower <= e <= upper])
        buckets.append(
            {
                "lower_cents": lower,
                "upper_cents": upper,
                "consultant_count": count,
                "share_bp": rhu(count * 10000, n),
            }
        )

    return {
        "population_count": n,
        "zero_earner_count": zero_count,
        "total_earnings_cents": total,
        "median_earnings_cents": median,
        "mean_earnings_cents": mean,
        "p90_earnings_cents": p90,
        "top_decile_share_bp": top_share_bp,
        "distribution_buckets": buckets,
    }
