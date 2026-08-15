"""Population trend classification (PRD §2.11, calculation
population_trend_delta).

Surveys are processed in chronological order by surveyed_on, tie-broken by
created_at ascending — never by id. Fewer than two surveys yields
INSUFFICIENT_DATA. Otherwise delta = (last - first) / first, compared
UNROUNDED against inclusive thresholds: <= -0.20 DECLINING, >= +0.20 GROWING,
strictly between FLAT. Zero baseline is a pinned special case: first == 0
yields GROWING when last > 0 and FLAT when last == 0.
"""

from fractions import Fraction

from db import db

DECLINE_THRESHOLD = Fraction(-1, 5)   # -0.20 inclusive
GROWTH_THRESHOLD = Fraction(1, 5)     # +0.20 inclusive


def colony_surveys(colony_id):
    rows = [s for s in db.population_surveys.values()
            if s["colony_id"] == colony_id]
    return sorted(rows, key=lambda s: (s["_surveyed_on"], s["created_at"], s["_seq"]))


def population_report(colony):
    surveys = colony_surveys(colony["id"])
    report = {
        "colony_id": colony["id"],
        "survey_count": len(surveys),
        "first_observed_count": None,
        "last_observed_count": None,
        "delta_pct": None,
        "trend": "INSUFFICIENT_DATA",
    }
    if len(surveys) < 2:
        return report

    first = surveys[0]["observed_count"]
    last = surveys[-1]["observed_count"]
    report["first_observed_count"] = first
    report["last_observed_count"] = last

    if first > 0:
        delta = Fraction(last - first, first)
        report["delta_pct"] = float(delta)
        if delta <= DECLINE_THRESHOLD:
            trend = "DECLINING"
        elif delta >= GROWTH_THRESHOLD:
            trend = "GROWING"
        else:
            trend = "FLAT"
    else:
        # Zero baseline: +INF (GROWING) when last > 0, 0 (FLAT) when last == 0.
        trend = "GROWING" if last > 0 else "FLAT"
        report["delta_pct"] = None if last > 0 else 0.0
    report["trend"] = trend
    return report
