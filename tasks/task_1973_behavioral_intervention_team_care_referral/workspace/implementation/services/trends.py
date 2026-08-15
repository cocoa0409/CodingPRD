from decimal import Decimal, ROUND_HALF_UP

from db import store, all_sorted
from services.domain import CONCERN_CATEGORIES, r1


def compute_trend_metrics(window_start, window_end, variant):
    """trend_report_metrics + trend_category_distribution. Windows are closed intervals."""
    cases = all_sorted(store.cases)
    if variant == "ENTRY_COHORT":
        input_set = [c for c in cases if window_start <= c["created_at"] <= window_end]
    else:  # ACTIVE_IN_WINDOW
        input_set = [
            c
            for c in cases
            if c["created_at"] <= window_end
            and (c["closed_at"] is None or c["closed_at"] >= window_start)
        ]
    total = len(input_set)
    closed_in = [
        c
        for c in input_set
        if c["closed_at"] is not None and window_start <= c["closed_at"] <= window_end
    ]
    n_closed = len(closed_in)
    if total == 0:
        closure_rate = 0.0
    else:
        closure_rate = r1(Decimal(100) * Decimal(n_closed) / Decimal(total))
    if n_closed == 0:
        avg_days = 0.0
    else:
        day_spans = [
            Decimal(str((c["closed_at"] - c["created_at"]).total_seconds())) / Decimal(86400)
            for c in closed_in
        ]
        avg_days = r1(sum(day_spans) / Decimal(n_closed))

    # Category distribution with pinned rounding order: first four categories
    # rounded independently, WELLBEING_GENERAL receives the residual.
    counts = {c: 0 for c in CONCERN_CATEGORIES}
    for case in input_set:
        report = store.reports.get(case["opened_from_report_id"])
        if report is not None and report["category"] in counts:
            counts[report["category"]] += 1
    if total == 0:
        distribution = {c: 0.0 for c in CONCERN_CATEGORIES}
    else:
        first_four = [
            (Decimal(100) * Decimal(counts[c]) / Decimal(total)).quantize(
                Decimal("0.1"), rounding=ROUND_HALF_UP
            )
            for c in CONCERN_CATEGORIES[:4]
        ]
        last = (Decimal(100) - sum(first_four)).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )
        distribution = {c: float(first_four[i]) for i, c in enumerate(CONCERN_CATEGORIES[:4])}
        distribution[CONCERN_CATEGORIES[4]] = float(last)

    return {
        "total_cases": total,
        "closed_in_window": n_closed,
        "closure_rate_pct": closure_rate,
        "avg_days_to_close": avg_days,
        "category_distribution": distribution,
    }
