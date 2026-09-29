"""The engagement economics forecast and the overrun cascade (PRD 3.7)."""

from decimal import Decimal

from calc import (
    AT_RISK_MARGIN_PCT,
    AT_RISK_VARIANCE_PCT,
    D,
    OVERRUN_MARGIN_PCT,
    OVERRUN_VARIANCE_PCT,
    engagement_economics,
)
from db import touch
from services.cascade import (
    create_escalation,
    opportunity_deliverables,
    reconcile_on_raise,
)


def accepted_weight_sum(engagement):
    total = Decimal("0")
    for d in opportunity_deliverables(engagement["opportunity_id"]):
        if d["status"] == "ACCEPTED":
            total += D(d["completion_weight_pct"])
    return total


def compute(engagement):
    """Pure computation; never mutates."""
    return engagement_economics(engagement, accepted_weight_sum(engagement))


def _overrun_reason(figures):
    if figures["progress_variance_pct"] >= OVERRUN_VARIANCE_PCT:
        return (
            "progress_variance_pct %s reached the %s overrun threshold"
            % (figures["progress_variance_pct"], OVERRUN_VARIANCE_PCT)
        )
    return (
        "projected_margin_pct %s fell below the %s overrun threshold"
        % (figures["projected_margin_pct"], OVERRUN_MARGIN_PCT)
    )


def recompute(engagement):
    """Recompute, persist economics_state and run the overrun cascade."""
    figures = compute(engagement)
    previous = engagement["economics_state"]
    engagement["economics_state"] = figures["economics_state"]
    touch(engagement)
    if figures["economics_state"] == "OVERRUN" and previous != "OVERRUN":
        create_escalation(
            engagement,
            source="ECONOMICS",
            severity="HIGH",
            opened_reason=_overrun_reason(figures),
        )
        reconcile_on_raise(engagement, "HIGH")
    return figures


__all__ = [
    "accepted_weight_sum",
    "compute",
    "recompute",
    "AT_RISK_MARGIN_PCT",
    "AT_RISK_VARIANCE_PCT",
]
