"""The out-of-control cascade (PRD 3.2).

Link one (the monitoring system's own demotion) is applied by the caller,
because a triggering calibration and an explicit declaration stamp
``out_of_control_since_utc`` from different sources. Links two, three and four
are identical in both paths and live here.
"""

from db import db, touch
from lookup import hours_of_unit
from services import permits
from services.reports import (
    period_of_hour,
    recompute_report,
    recompute_unit_availability_for_periods,
)
from util import truncate_to_hour


def run_links_two_to_four(system, anchor_dt):
    unit = db.units.get(system["unit_id"])
    if unit is None:
        return {"flipped_hours": [], "reports": [], }
    cutoff = truncate_to_hour(anchor_dt)

    # ---- link two: retroactive hour invalidation --------------------------
    flipped = [
        h for h in hours_of_unit(unit["id"])
        if h["_hour_begin"] >= cutoff and h["data_quality"] == "MEASURED"
    ]
    flipped.sort(key=lambda h: (h["_hour_begin"], h["created_at"], h["_seq"]))
    for hour in flipped:
        hour["data_quality"] = "UNAVAILABLE"
        hour["so2_mass_lbs"] = None
    if flipped:
        recompute_unit_availability_for_periods(unit, [period_of_hour(h) for h in flipped])

    # ---- link three: owning report roll-ups ------------------------------
    seen = []
    for hour in flipped:
        report_id = hour.get("quarterly_report_id")
        if report_id and report_id not in seen:
            seen.append(report_id)
    reports = [db.quarterly_reports[rid] for rid in seen if rid in db.quarterly_reports]
    reports.sort(key=lambda r: (r["created_at"], r["_seq"]))
    for report in reports:
        recompute_report(report, revert_validated=True, bump=True)

    # ---- link four: permit limit re-evaluation ---------------------------
    permits.reevaluate_unit_limits(unit["id"])

    return {"flipped_hours": flipped, "reports": reports}


def demote_system_out_of_control(system, since_raw, since_dt, fail_calibration=True):
    """Link one.

    ``fail_calibration`` is only true on the calibration-driven path, where PRD
    3.2 link one states ``cal_status`` becomes ``CAL_FAILED``. A QAAnalyst
    declaration moves the QA axis and stamps ``out_of_control_since_utc`` only,
    then runs the identical link two/three/four chain -- the two status fields
    are parallel independent dimensions, so a declared system may legitimately
    sit at OUT_OF_CONTROL with CAL_CURRENT.
    """
    system["qa_status"] = "OUT_OF_CONTROL"
    if fail_calibration:
        system["cal_status"] = "CAL_FAILED"
    system["out_of_control_since_utc"] = since_raw
    system["_out_of_control_since"] = since_dt
    touch(system)
