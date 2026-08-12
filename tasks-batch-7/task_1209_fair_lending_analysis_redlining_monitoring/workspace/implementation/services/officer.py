"""officer_risk_score calculation + monitoring-tier cascade."""
from decimal import Decimal, ROUND_HALF_UP

import db

PROTECTED = ("PROTECTED_1", "PROTECTED_2")


def D(x):
    return x if isinstance(x, Decimal) else Decimal(str(x))


def q(x, places):
    return float(D(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP))


def officer_components(officer):
    """Compute the officer risk scorecard from current counters."""
    a = max(1, officer["validated_application_count"])
    override_rate = D(officer["confirmed_override_count"]) / D(a)
    exception_rate = D(officer["approved_exception_count"]) / D(a)
    rates = [
        app["note_rate_bps"]
        for app in db.STORES["applications"].values()
        if app["loan_officer_id"] == officer["id"]
        and app["status"] == "VALIDATED"
        and app["outcome"] == "ORIGINATED"
    ]
    dispersion = (max(rates) - min(rates)) if len(rates) >= 2 else 0
    score = (
        D(40) * min(D(1), override_rate / D("0.20"))
        + D(35) * min(D(1), exception_rate / D("0.10"))
        + D(25) * min(D(1), D(dispersion) / D(70))
    )
    score = min(D(100), score)
    score_r = D(score).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if score_r >= 70:
        tier = "RED"
    elif score_r >= 40:
        tier = "WATCH"
    else:
        tier = "GREEN"
    return {
        "application_count": officer["validated_application_count"],
        "confirmed_override_count": officer["confirmed_override_count"],
        "override_rate": q(override_rate, 4),
        "approved_exception_count": officer["approved_exception_count"],
        "exception_approval_rate": q(exception_rate, 4),
        "pricing_dispersion_bps": dispersion,
        "risk_score": float(score_r),
        "monitoring_tier": tier,
    }


def refresh_officer(officer, force_touch=False):
    """Recompute risk_score/monitoring_tier and fire the one-way RED cascade.

    Escalation side effects fire only on upward crossings into RED.
    """
    comp = officer_components(officer)
    changed = (
        comp["risk_score"] != officer["risk_score"]
        or comp["monitoring_tier"] != officer["monitoring_tier"]
    )
    old_tier = officer["monitoring_tier"]
    officer["risk_score"] = comp["risk_score"]
    officer["monitoring_tier"] = comp["monitoring_tier"]
    if force_touch or changed:
        db.touch(officer)
    if old_tier != "RED" and comp["monitoring_tier"] == "RED":
        for exc in db.STORES["exceptions"].values():
            if exc["loan_officer_id"] == officer["id"] and exc["status"] == "REQUESTED":
                exc["status"] = "ESCALATED"
                db.touch(exc)
    return comp
