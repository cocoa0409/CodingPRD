"""Comparable grid roll-ups, completeness scoring, reconciliation and the
eight-row automated rule battery."""

from decimal import Decimal

import db
from validate import bps_of, rhu
from services import constants as C


def normalize_address(text):
    return " ".join(text.split()).casefold()


def eligible_comps(appraisal_id):
    return [c for c in db.ordered(db.comparables)
            if c["appraisal_id"] == appraisal_id and c["included_in_grid"]]


def all_comps(appraisal_id):
    return [c for c in db.ordered(db.comparables) if c["appraisal_id"] == appraisal_id]


def refresh_comp_counts(appraisal):
    """Refresh only the two comparable tallies.

    Adding a comparable refreshes ``eligible_comp_count`` and
    ``closed_comp_count`` and nothing else; the adjustment maxima are written by
    the rule-check run, so they stay at their delivered zero until the battery
    has actually run.
    """
    comps = eligible_comps(appraisal["id"])
    appraisal["eligible_comp_count"] = len(comps)
    appraisal["closed_comp_count"] = sum(1 for c in comps if c["sale_status"] == "CLOSED")
    db.touch(appraisal)


def refresh_grid_rollups(appraisal):
    """Refresh the tallies and the adjustment maxima; the rule-check run's job."""
    refresh_comp_counts(appraisal)
    comps = eligible_comps(appraisal["id"])
    appraisal["max_gross_adjustment_bps"] = max([c["gross_adjustment_bps"] for c in comps], default=0)
    appraisal["max_net_adjustment_bps"] = max([c["net_adjustment_bps"] for c in comps], default=0)
    db.touch(appraisal)


def grid_locked(appraisal):
    if appraisal["review_status"] in ("VALUE_ACCEPTED", "VALUE_REVISED", "QUARANTINED", "SUPERSEDED"):
        return True
    for review in db.desk_reviews.values():
        if review["appraisal_id"] == appraisal["id"] and review["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED"):
            return True
    return False


# ------------------------------------------------------------- completeness
def completeness_score(appraisal):
    sections = appraisal["sections_present"] or []
    hits = sum(1 for name in C.REQUIRED_SECTIONS if name in sections)
    section_bps = bps_of(hits, len(C.REQUIRED_SECTIONS))
    comp_bps = bps_of(min(appraisal["closed_comp_count"], C.MIN_CLOSED_COMPS), C.MIN_CLOSED_COMPS)
    exhibit_bps = bps_of(min(appraisal["exhibit_count"], C.MAX_EXHIBITS_SCORED), C.MAX_EXHIBITS_SCORED)
    weighted = (Decimal("0.50") * Decimal(section_bps)
                + Decimal("0.30") * Decimal(comp_bps)
                + Decimal("0.20") * Decimal(exhibit_bps))
    return rhu(weighted)


# ----------------------------------------------------------- reconciliation
def reconciled_value(appraisal):
    comps = eligible_comps(appraisal["id"])
    n = len(comps)
    if n == 0:
        return None, None
    indicated = sum(rhu(c["adjusted_price_cents"], n) for c in comps)
    variance = bps_of(abs(indicated - appraisal["reported_value_cents"]),
                      appraisal["reported_value_cents"])
    return indicated, variance


def distance_ceiling(loan):
    return C.DISTANCE_CEILINGS[loan["market_type"]]


def whole_days(start, end):
    return (end - start).days


# ------------------------------------------------------------- rule battery
def run_rule_checks(appraisal, loan):
    """Write exactly eight ordered rows, replacing any prior generation."""
    for key in [k for k, v in db.rule_checks.items() if v["appraisal_id"] == appraisal["id"]]:
        del db.rule_checks[key]

    refresh_grid_rollups(appraisal)
    comps = eligible_comps(appraisal["id"])
    ceiling = distance_ceiling(loan)

    appraisal["completeness_score_bps"] = completeness_score(appraisal)
    indicated, variance = reconciled_value(appraisal)
    appraisal["indicated_value_cents"] = indicated
    appraisal["variance_vs_reported_bps"] = variance

    rows = []

    score = appraisal["completeness_score_bps"]
    if score < C.COMPLETENESS_FAIL_BELOW:
        outcome = "FAIL"
    elif score < C.COMPLETENESS_WARN_BELOW:
        outcome = "WARN"
    else:
        outcome = "PASS"
    rows.append(("CHK_COMPLETENESS", outcome, str(score),
                 "Weighted completeness score in basis points."))

    closed = appraisal["closed_comp_count"]
    rows.append(("CHK_COMP_COUNT", "FAIL" if closed < C.MIN_CLOSED_COMPS else "PASS",
                 str(closed), "Closed comparable sales included in the grid."))

    distances = [c["distance_miles"] for c in comps]
    max_distance = max(distances) if distances else Decimal("0.00")
    if any(d > ceiling * 2 for d in distances):
        outcome = "FAIL"
    elif any(d > ceiling for d in distances):
        outcome = "WARN"
    else:
        outcome = "PASS"
    rows.append(("CHK_COMP_DISTANCE", outcome, "%.2f" % max_distance,
                 "Greatest comparable distance against the %s ceiling of %.2f miles."
                 % (loan["market_type"], ceiling)))

    ages = [whole_days(c["sale_date"], appraisal["effective_date"]) for c in comps]
    max_age = max(ages) if ages else 0
    rows.append(("CHK_COMP_AGE", "FAIL" if any(a > C.STALE_SALE_DAYS for a in ages) else "PASS",
                 str(max_age), "Greatest comparable sale age in whole days."))

    gross = appraisal["max_gross_adjustment_bps"]
    if gross > C.GROSS_ADJ_FAIL_ABOVE:
        outcome = "FAIL"
    elif gross > C.GROSS_ADJ_WARN_ABOVE:
        outcome = "WARN"
    else:
        outcome = "PASS"
    rows.append(("CHK_GROSS_ADJUSTMENT", outcome, str(gross),
                 "Largest gross adjustment in basis points of sale price."))

    net = appraisal["max_net_adjustment_bps"]
    if net > C.NET_ADJ_FAIL_ABOVE:
        outcome = "FAIL"
    elif net > C.NET_ADJ_WARN_ABOVE:
        outcome = "WARN"
    else:
        outcome = "PASS"
    rows.append(("CHK_NET_ADJUSTMENT", outcome, str(net),
                 "Largest absolute net adjustment in basis points of sale price."))

    if variance is None:
        outcome = "PASS"
    elif variance > C.VARIANCE_FAIL_ABOVE:
        outcome = "FAIL"
    elif variance > C.VARIANCE_WARN_ABOVE:
        outcome = "WARN"
    else:
        outcome = "PASS"
    rows.append(("CHK_VALUE_RECONCILIATION", outcome,
                 str(variance if variance is not None else 0),
                 "Variance of the reconciled indicated value against the reported value."))

    form_fail = (appraisal["report_form_type"] == "FORM_2055"
                 and loan["risk_tier"] in ("ELEVATED", "HIGH"))
    rows.append(("CHK_FORM_TYPE", "FAIL" if form_fail else "PASS",
                 appraisal["report_form_type"],
                 "Report form suitability for the loan risk tier."))

    results = []
    for index, (code, outcome, observed, detail) in enumerate(rows, start=1):
        rec = db.make_record({
            "appraisal_id": appraisal["id"],
            "sequence_no": index,
            "check_code": code,
            "outcome": outcome,
            "observed_value": observed,
            "detail": detail,
        }, versioned=False)
        db.rule_checks[rec["id"]] = rec
        results.append(rec)

    appraisal["rule_check_fail_count"] = sum(1 for r in results if r["outcome"] == "FAIL")
    appraisal["rule_check_warn_count"] = sum(1 for r in results if r["outcome"] == "WARN")
    if appraisal["current_value_cents"] is None:
        appraisal["current_value_cents"] = appraisal["reported_value_cents"]
    appraisal["review_status"] = ("RULES_FLAGGED" if appraisal["rule_check_fail_count"] > 0
                                 else "RULES_CLEARED")
    return results
