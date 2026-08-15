"""DMR computation: monitoring completeness, summary lines, loading."""

import math
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from util import round_half_up, num_out

CONVERSION_KG_PER_MG_L_MGD = Decimal("3.785")


def _comparison_value(result):
    if result["qualifier"] == "BELOW_MDL":
        return Decimal(result["method_detection_limit"])
    return Decimal(result["reported_value"])


def _active_limits_covering(outfall_id, period_start, period_end):
    """ACTIVE limits for the outfall whose effective range intersects the period."""
    out = []
    for lim in db.effluent_limits.values():
        if lim["outfall_id"] != outfall_id or lim["status"] != "ACTIVE":
            continue
        ef = lim["effective_from"]
        et = lim["effective_to"]
        # intersects [period_start, period_end] iff ef <= period_end and (et is None or et > period_start)
        if ef <= period_end and (et is None or et > period_start):
            out.append(lim)
    return out


def _months_touched(period_start, period_end):
    """Number of calendar months touched by [period_start, period_end] inclusive."""
    months = set()
    d = period_start.date()
    end = period_end.date()
    cur = d.replace(day=1)
    while cur <= end:
        months.add((cur.year, cur.month))
        # advance to next month
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    return len(months)


def _validated_results_in_period(outfall_id, period_start, period_end):
    """VALIDATED LabResults for this outfall whose sample was collected within the period (inclusive)."""
    out = []
    for r in db.lab_results.values():
        if r["validation_status"] != "VALIDATED":
            continue
        ev = db.sampling_events.get(r["sampling_event_id"])
        if ev is None or ev["outfall_id"] != outfall_id:
            continue
        if ev["collected_at"] is None:
            continue
        if period_start <= ev["collected_at"] <= period_end:
            out.append((ev, r))
    # Order by collected_at ASC, tie-break created_at ASC (then insertion seq)
    out.sort(key=lambda t: (t[0]["collected_at"], t[1]["created_at"], t[1]["_seq"]))
    return out


def compute_dmr_picture(outfall_id, period_start, period_end):
    """Compute required_sample_count, total_validated_results, ratio, summary_lines."""
    limits = _active_limits_covering(outfall_id, period_start, period_end)
    days_in_period = (period_end.date() - period_start.date()).days + 1
    months = _months_touched(period_start, period_end)

    # Per-parameter required counts; a parameter may hold both a DAILY_MAX and
    # a MONTHLY_AVG limit — each limit drives its own required count.
    # Group by parameter for summary lines, but required counts are summed per limit.
    params = {}
    for lim in limits:
        entry = params.setdefault(lim["parameter_code"], {"limits": [], "required": 0})
        entry["limits"].append(lim)
        if lim["monitoring_frequency"] == "WEEKLY":
            entry["required"] += math.ceil(days_in_period / 7)
        else:  # MONTHLY
            entry["required"] += months

    required_sample_count = sum(v["required"] for v in params.values())
    validated = _validated_results_in_period(outfall_id, period_start, period_end)
    total_validated_results = len(validated)

    if required_sample_count == 0:
        ratio = Decimal("0")
    else:
        ratio = round_half_up(Decimal(total_validated_results) / Decimal(required_sample_count), 4)

    summary_lines = []
    for param_code in sorted(params.keys()):
        info = params[param_code]
        results = [(ev, r) for (ev, r) in validated if r["parameter_code"] == param_code]
        sample_count = len(results)

        # Average follows the parameter limit's average_method. Prefer the
        # MONTHLY_AVG limit's method when present; else the first limit's method.
        monthly_lim = next(
            (l for l in info["limits"] if l["limit_type"] == "MONTHLY_AVG"), None
        )
        daily_lim = next(
            (l for l in info["limits"] if l["limit_type"] == "DAILY_MAX"), None
        )
        governing_for_method = monthly_lim or (info["limits"][0] if info["limits"] else None)
        method = governing_for_method["average_method"] if governing_for_method else "ARITHMETIC"

        comp_values = [_comparison_value(r) for (_, r) in results]
        flows = [Decimal(r["flow_mgd"]) for (_, r) in results]

        if sample_count == 0:
            avg = None
            max_conc = None
            total_loading = Decimal("0")
        else:
            if method == "FLOW_WEIGHTED":
                num = sum(c * f for c, f in zip(comp_values, flows))
                den = sum(flows)
                avg = round_half_up(num / den, 3)
            else:
                avg = round_half_up(sum(comp_values) / Decimal(sample_count), 3)
            max_conc = max(comp_values)
            per_sample_loads = [
                round_half_up(c * f * CONVERSION_KG_PER_MG_L_MGD, 3)
                for c, f in zip(comp_values, flows)
            ]
            total_loading = round_half_up(sum(per_sample_loads), 2)

        exceeds = False
        if monthly_lim is not None and avg is not None:
            if avg > Decimal(monthly_lim["limit_value"]):
                exceeds = True
        if daily_lim is not None and max_conc is not None:
            if max_conc > Decimal(daily_lim["limit_value"]):
                exceeds = True

        summary_lines.append(
            {
                "parameter_code": param_code,
                "sample_count": sample_count,
                "avg_concentration": num_out(avg) if avg is not None else None,
                "max_concentration": num_out(max_conc) if max_conc is not None else None,
                "total_loading_kg": num_out(total_loading) if total_loading is not None else None,
                "exceeds_limit": exceeds,
            }
        )

    return {
        "required_sample_count": required_sample_count,
        "total_validated_results": total_validated_results,
        "monitoring_completeness_ratio": ratio,
        "summary_lines": summary_lines,
    }
