"""Annual report statistics (PRD section 3.9)."""

from datetime import date

from db import DB
from services import calc, derive
from services.calc import D


def _date(text):
    return date.fromisoformat(text)


def window_of(report):
    return calc.window_bounds(
        _date(report["reporting_period_start"]), _date(report["reporting_period_end"])
    )


def pending_samples_in_window(term, report):
    """True when an unadjudicated wet-weather sample sits inside the window."""
    start, end = window_of(report)
    for obs in derive.observations_of_term(term["id"]):
        if obs["observation_type"] != "WET_WEATHER_SAMPLE":
            continue
        if obs.get("validation_status") != "PENDING":
            continue
        if calc.in_window(derive.to_dt(obs["observed_at"]), start, end):
            return True
    return False


def statistics(term, report):
    term_id = term["id"]
    start, end = window_of(report)
    start_date = _date(report["reporting_period_start"])
    end_date = _date(report["reporting_period_end"])

    outfalls = derive.outfalls_of_term(term_id)
    active_outfalls = [o for o in outfalls if o["status"] == "ACTIVE"]

    screenings = 0
    screened_outfall_ids = set()
    for obs in derive.observations_of_term(term_id):
        if obs["observation_type"] != "DRY_WEATHER_SCREENING":
            continue
        if not calc.in_window(derive.to_dt(obs["observed_at"]), start, end):
            continue
        screenings += 1
        screened_outfall_ids.add(obs["outfall_id"])

    denominator = len(active_outfalls)
    if denominator == 0:
        coverage = D("0.00")
    else:
        covered = len([o for o in active_outfalls if o["id"] in screened_outfall_ids])
        coverage = calc.rhu(D(100) * D(covered) / D(denominator), 2)

    cases = derive.cases_of_term(term_id)
    cases_opened = len(
        [c for c in cases if calc.in_window(derive.to_dt(c.get("opened_at")), start, end)]
    )
    cases_resolved = len(
        [
            c
            for c in cases
            if c["status"] == "RESOLVED"
            and calc.in_window(derive.to_dt(c.get("resolved_at")), start, end)
        ]
    )

    construction_finalized = 0
    facility_finalized = 0
    for inspection in DB.inspections.values():
        if inspection.get("status") != "FINALIZED":
            continue
        owner = derive.term_of_inspection(inspection)
        if owner is None or owner["id"] != term_id:
            continue
        if not calc.in_window(derive.to_dt(inspection.get("finalized_at")), start, end):
            continue
        if inspection["inspection_type"] == "CONSTRUCTION_ESC":
            construction_finalized += 1
        else:
            facility_finalized += 1

    actions_issued = 0
    penalty_total = 0
    for action in DB.enforcement_actions.values():
        if action["status"] not in ("ISSUED", "ESCALATED", "CLOSED"):
            continue
        owner = derive.term_of_action(action)
        if owner is None or owner["id"] != term_id:
            continue
        if not calc.in_window(derive.to_dt(action.get("issued_at")), start, end):
            continue
        actions_issued += 1
        penalty_total += int(action.get("penalty_cents") or 0)

    lane_miles = D(0)
    for outfall in outfalls:
        for run in outfall.get("sweeping_runs", []):
            run_start = _date(run["run_start_date"])
            if start_date <= run_start <= end_date:
                lane_miles += D(run["lane_miles_swept"])

    net_load = D(0)
    for outfall in active_outfalls:
        if outfall.get("last_assessed_year") == end_date.year:
            net_load += D(outfall.get("last_assessed_net_load_lb") or 0)

    measures = derive.measures_of_term(term_id)
    active_measures = [m for m in measures if m["status"] == "ACTIVE"]
    goals_met = len([m for m in active_measures if m["goal_status"] == "MET"])

    return {
        "screenings_completed": screenings,
        "outfall_screening_coverage_pct": float(coverage),
        "cases_opened": cases_opened,
        "cases_resolved": cases_resolved,
        "construction_inspections_finalized": construction_finalized,
        "facility_inspections_finalized": facility_finalized,
        "enforcement_actions_issued": actions_issued,
        "total_penalty_assessed_cents": penalty_total,
        "swept_lane_miles": calc.num(lane_miles, 2),
        "net_annual_load_lb": calc.num(net_load, 2),
        "measurable_goals_met_count": goals_met,
        "compliance_index": float(calc.compliance_index(active_measures)),
    }
