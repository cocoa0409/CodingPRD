"""Quality scoring calculations: error_density, scoring_rubric, rolling/latest rating."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from clock import clock
from db import store
from services.common import round_half_up_2dp

SEVERITY_WEIGHT = {"MINOR": 1, "MAJOR": 3, "CRITICAL": 9}
PENALTY_PER_DENSITY_UNIT = Decimal("2.5")
ROLLING_WINDOW_DAYS = 90


def compute_error_density(errors: list[dict], word_count: int) -> float:
    weighted = 0
    for e in errors or []:
        sev = e.get("severity")
        cnt = e.get("count", 0)
        weighted += SEVERITY_WEIGHT.get(sev, 0) * int(cnt)
    words = max(1, int(word_count))
    density = Decimal(weighted) * Decimal(1000) / Decimal(words)
    return round_half_up_2dp(density)


def compute_score(error_density) -> float:
    raw = Decimal(100) - Decimal(str(error_density)) * PENALTY_PER_DENSITY_UNIT
    if raw < 0:
        raw = Decimal(0)
    if raw > 100:
        raw = Decimal(100)
    return round_half_up_2dp(raw)


def refresh_translator_rating(translator_id: str) -> None:
    tr = store.translators.get(translator_id)
    if tr is None:
        return
    now = clock.now()
    window_start = now - timedelta(days=ROLLING_WINDOW_DAYS)
    finalized = []
    for q in store.quality_scores.values():
        if q["state"] != "FINALIZED":
            continue
        if q.get("translator_id") != translator_id:
            continue
        finalized.append(q)

    # Rolling average within window
    in_window = [q for q in finalized if q.get("finalized_at") and q["finalized_at"] > window_start]
    if in_window:
        avg = sum(Decimal(str(q["score"])) for q in in_window) / Decimal(len(in_window))
        tr["rolling_quality_score"] = round_half_up_2dp(avg)
    else:
        tr["rolling_quality_score"] = 100.00

    # Latest
    if finalized:
        finalized.sort(key=lambda q: (q.get("finalized_at") or q["updated_at"], q["id"]))
        latest = finalized[-1]
        # tie-break: same finalized_at, lexicographically smallest id wins ascending
        candidates = [q for q in finalized if (q.get("finalized_at") or q["updated_at"]) == (latest.get("finalized_at") or latest["updated_at"])]
        candidates.sort(key=lambda q: q["id"])
        tr["latest_quality_score"] = candidates[0]["score"]
    else:
        tr["latest_quality_score"] = 100.00

    # Bump version/updated_at — translator entity mutated as a cascade
    from services.common import touch
    touch(tr)
