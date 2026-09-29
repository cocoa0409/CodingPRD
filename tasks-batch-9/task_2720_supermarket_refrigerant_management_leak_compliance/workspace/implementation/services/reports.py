"""Regulatory filing mass accounting and late-filing assessment (PRD 3.9)."""
from decimal import Decimal

import constants
import db
import util
from services import ledger

ZERO = Decimal("0")


def participating_systems(store_id, period_end):
    """Regulated systems of the store installed on or before the period end."""
    systems = [
        system for system in db.values("systems")
        if system["store_id"] == store_id
        and system["applicability"] == "REGULATED"
        and system["installed_on"] <= period_end
    ]
    systems.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return systems


def window_bounds(report):
    """The inclusive accounting window [period_start, min(period_end, clock)]."""
    clock = db.now()
    end = report["period_end"] if report["period_end"] <= clock else clock
    return report["period_start"], end


def window_records(system_id, start, end):
    return [
        record for record in ledger.system_records(system_id)
        if start <= record["performed_at"] <= end
    ]


def total_leaked_lbs(report):
    """CHARGE_BASED sums charged mass; BALANCE_BASED reconciles inventory.

    Either way the sum is rounded exactly once, at the end (PRD 2.6).
    """
    start, end = window_bounds(report)
    systems = participating_systems(report["store_id"], report["period_end"])
    total = ZERO
    if report["leaked_lbs_method"] == "BALANCE_BASED":
        for system in systems:
            added = ZERO
            recovered = ZERO
            for record in window_records(system["id"], start, end):
                added = added + record["refrigerant_added_lbs"]
                recovered = recovered + record["refrigerant_recovered_lbs"]
            opening = ledger.charge_at(system, report["period_start"])
            closing = ledger.charge_at(system, end)
            total = total + opening + added - recovered - closing
    else:
        for system in systems:
            for record in window_records(system["id"], start, end):
                if record["service_type"] in constants.LEAK_RATE_SERVICE_TYPES:
                    total = total + record["refrigerant_added_lbs"]
    return util.q1(total), len(systems)


def recompute_totals(report):
    leaked, count = total_leaked_lbs(report)
    report["total_leaked_lbs"] = leaked
    report["included_system_count"] = count


def surcharge_rate(base):
    """The rate is selected from the base assessment alone (PRD 3.9)."""
    for ceiling, rate in constants.SURCHARGE_TIERS:
        if base < ceiling:
            return rate
    return constants.TOP_SURCHARGE_RATE


def assess_late_filing(report, submitted_at):
    """days_late -> base -> surcharge -> total, each rounded half up to cents."""
    elapsed = util.whole_days_between(report["due_on"], submitted_at)
    days_late = elapsed if elapsed > 0 else 0
    base = util.q2(constants.DAILY_LATE_RATE * Decimal(days_late))
    rate = surcharge_rate(base)
    surcharge = util.q2(base * rate)
    report["days_late"] = days_late
    report["base_assessment_usd"] = base
    report["administrative_surcharge_usd"] = surcharge
    report["late_filing_assessment_usd"] = util.q2(base + surcharge)


def overlapping_report(store_id, period_start, period_end, exclude_id=None):
    """PRD 3.9: two filings may not share even a single day of their inclusive
    periods unless the earlier one has been rejected."""
    for report in db.values("regulatory_reports"):
        if report["store_id"] != store_id:
            continue
        if report["status"] == "REJECTED":
            continue
        if exclude_id is not None and report["id"] == exclude_id:
            continue
        if period_start <= report["period_end"] and report["period_start"] <= period_end:
            return report
    return None
