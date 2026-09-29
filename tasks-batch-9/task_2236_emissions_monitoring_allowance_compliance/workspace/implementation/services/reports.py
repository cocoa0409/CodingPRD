"""Quarterly report roll-up maintenance (PRD 3.6 / 3.7).

A "recompute" always rewrites the four counts, the availability percentage and
the five totals from the report's own hours, reverts a VALIDATED report to DRAFT
and increments the report's version by exactly one.
"""

from db import db, touch
from services import calc
from util import D, quarter_of


def report_hours(report_id):
    """A report's hours in canonical order: hour_begin ascending, ties by the
    earlier created_at.
    """
    rows = [h for h in db.operating_hours.values() if h["quarterly_report_id"] == report_id]
    rows.sort(key=lambda h: (h["_hour_begin"], h["created_at"], h["_seq"]))
    return rows


def recompute_report(report, revert_validated=True, bump=True):
    hours = report_hours(report["id"])
    operating, measured, substituted = calc.report_counts(hours)
    totals = calc.report_totals(hours)
    report["operating_hour_count"] = operating
    report["measured_hour_count"] = measured
    report["substituted_hour_count"] = substituted
    report["monitor_data_availability_pct"] = calc.availability_pct(
        report["unit_id"], report["year"], report["quarter"]
    )
    report.update(totals)
    if revert_validated and report["status"] == "VALIDATED":
        report["status"] = "DRAFT"
    if bump:
        touch(report)
    return report


def recompute_unit_availability(unit, year, quarter):
    """The unit-level mirror of the report's availability percentage."""
    unit["data_availability_pct"] = calc.availability_pct(unit["id"], year, quarter)


def recompute_unit_availability_for_periods(unit, periods):
    """``periods`` is an iterable of ``(year, quarter)``. The unit carries a
    single percentage, so the latest period touched wins.
    """
    ordered = sorted(set(periods))
    if not ordered:
        return
    year, quarter = ordered[-1]
    recompute_unit_availability(unit, year, quarter)


def period_of_hour(hour):
    hb = hour["_hour_begin"]
    return hb.year, quarter_of(hb)


def find_open_report(unit_id, year, quarter):
    """The report that owns an hour: same unit, same calendar quarter, standing
    at DRAFT or VALIDATED.
    """
    for report in db.quarterly_reports.values():
        if report["unit_id"] != unit_id:
            continue
        if report["year"] != year or report["quarter"] != quarter:
            continue
        if report["status"] in ("DRAFT", "VALIDATED"):
            return report
    return None


def find_report_for_period(unit_id, year, quarter):
    for report in db.quarterly_reports.values():
        if report["unit_id"] == unit_id and report["year"] == year and report["quarter"] == quarter:
            return report
    return None


def total_so2_tons_of(reports):
    total = D(0)
    for report in reports:
        value = report.get("total_so2_tons")
        total += D(value if value is not None else 0)
    return total
