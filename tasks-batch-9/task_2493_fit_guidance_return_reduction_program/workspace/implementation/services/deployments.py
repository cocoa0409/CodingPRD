"""calculations.deployment_window_rates and calculations.intervention_savings."""

import constants as C
from db import db
from numeric import bp_rate, floor_div
from services.derive import (deployments_of_intervention, funding_posture,
                             lines_of_item)


def _fit_refunded_cases(lines, lower=None, upper=None):
    """Refunded FIT cases on exactly these lines, filtered on requested_at."""
    line_ids = {line["id"] for line in lines}
    count = 0
    for case in db.return_cases.values():
        if case["order_line_id"] not in line_ids:
            continue
        if case["reason_family"] != "FIT":
            continue
        if case["status"] != "RESOLVED_REFUNDED":
            continue
        requested_at = case["requested_at"]
        if requested_at is None:
            continue
        if lower is not None and requested_at < lower:
            continue
        if upper is not None and requested_at >= upper:
            continue
        count += 1
    return count


def snapshot_baseline(deployment):
    """SCHEDULED -> ACTIVE: everything strictly before window_start."""
    window_start = deployment["window_start"]
    lines = [line for line in lines_of_item(deployment["item_id"])
             if line["delivered_at"] < window_start]
    units = sum(line["quantity"] for line in lines)
    fit_returns = _fit_refunded_cases(lines, upper=window_start)
    deployment["baseline_units_count"] = units
    deployment["baseline_return_rate_bp"] = bp_rate(fit_returns, units)


def measure_window(deployment):
    """TERMINATED -> MEASURED: the half-open window [window_start, window_end)."""
    window_start = deployment["window_start"]
    window_end = deployment["window_end"]
    lines = [line for line in lines_of_item(deployment["item_id"])
             if window_start <= line["delivered_at"] < window_end]
    units = sum(line["quantity"] for line in lines)
    fit_returns = _fit_refunded_cases(lines, lower=window_start, upper=window_end)

    measured_rate = bp_rate(fit_returns, units)
    baseline_rate = deployment["baseline_return_rate_bp"] or 0
    rate_delta_bp = max(0, baseline_rate - measured_rate)
    avoided = floor_div(rate_delta_bp * units, 10000)

    item = db.items.get(deployment["item_id"])
    valuation = C.SAVED_COST_PER_AVOIDED_RETURN_CENTS[item["category_code"]]

    deployment["window_units_count"] = units
    deployment["measured_return_rate_bp"] = measured_rate
    deployment["avoided_return_count"] = avoided
    deployment["attributed_savings_cents"] = avoided * valuation


# ---------------------------------------------------------------------------
# The savings report: a computed read that never writes
# ---------------------------------------------------------------------------
def savings_report(intervention, variant):
    deployments = deployments_of_intervention(intervention["id"])
    measured = [d for d in deployments if d["status"] == "MEASURED"]
    spend = sum(d["spend_cents"] for d in deployments
                if d["status"] in ("TERMINATED", "MEASURED"))

    if variant == "cohort_chronological":
        gross, avoided_total = _cohort_chronological(measured)
    else:
        gross = sum(d["attributed_savings_cents"] or 0 for d in measured)
        avoided_total = sum(d["avoided_return_count"] or 0 for d in measured)

    net = gross - spend
    return {
        "variant_applied": variant,
        "gross_savings_cents": gross,
        "spend_cents": spend,
        "net_savings_cents": net,
        "measured_deployment_count": len(measured),
        "avoided_return_count": avoided_total,
        "funding_posture": funding_posture(net),
    }


def _cohort_chronological(measured):
    """Replay the MEASURED deployments against one running cohort baseline."""
    if not measured:
        return 0, 0
    ordered_measured = sorted(
        measured,
        key=lambda d: (d["window_start"], d["window_end"], d["created_at"], d["_seq"]),
    )
    running_baseline_bp = ordered_measured[0]["baseline_return_rate_bp"] or 0
    gross = 0
    avoided_total = 0
    for deployment in ordered_measured:
        measured_rate = deployment["measured_return_rate_bp"] or 0
        units = deployment["window_units_count"] or 0
        delta = max(0, running_baseline_bp - measured_rate)
        avoided = floor_div(delta * units, 10000)
        item = db.items.get(deployment["item_id"])
        valuation = C.SAVED_COST_PER_AVOIDED_RETURN_CENTS[item["category_code"]]
        gross += avoided * valuation
        avoided_total += avoided
        # the running baseline is updated only after the credit has been taken
        running_baseline_bp = measured_rate
    return gross, avoided_total
