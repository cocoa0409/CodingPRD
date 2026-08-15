"""Calculation rules (SCAFFOLD Table 3): labor_cost and alignment_verdict."""
from decimal import Decimal

import db
from util import D, num, round_half_up_int

CLASS_RATE_CENTS = {
    "MW_JOURNEYMAN": 8500,
    "MW_APPRENTICE": 5600,
    "MW_FOREMAN": 9800,
    "OPERATOR": 7200,
}
OT_MULT = Decimal("1.5")
NIGHT_SHIFT_MULT = Decimal("1.10")
FRINGE_CENTS_PER_HOUR = 2100
DAILY_OT_THRESHOLD_H = Decimal("8")
WEEKLY_OT_THRESHOLD_H = Decimal("40")

OFFSET_TOLERANCE_MILS = {"STANDARD": D("5.0"), "PRECISION": D("2.0")}
ANGULAR_TOLERANCE = {"STANDARD": D("1.0"), "PRECISION": D("0.5")}


def iso_week_key(d):
    ic = d.isocalendar()
    return (ic[0], ic[1])


def labor_cost(project, worker_ref, classification, work_date, hours_d, shift):
    """labor_cost: components frozen at creation; round each component half-up, then sum."""
    base = CLASS_RATE_CENTS[classification]
    mult = Decimal("1.0") if shift == "DAY" else NIGHT_SHIFT_MULT
    if project["ot_basis"] == "DAILY_OT":
        regular = min(hours_d, DAILY_OT_THRESHOLD_H)
        overtime = max(Decimal("0"), hours_d - DAILY_OT_THRESHOLD_H)
    else:
        # WEEKLY_OT: cumulative same-worker hours in the ISO week (Mon-Sun) of work_date,
        # counting only entries in SUBMITTED/APPROVED/INVOICED.
        wk = iso_week_key(work_date)
        prior = Decimal("0")
        for e in db.labor_entries.values():
            if e["worker_ref"] != worker_ref:
                continue
            if e["status"] not in ("SUBMITTED", "APPROVED", "INVOICED"):
                continue
            if iso_week_key(e["_work_date"]) != wk:
                continue
            prior += D(e["hours_worked"])
        regular = max(Decimal("0"),
                      min(prior + hours_d, WEEKLY_OT_THRESHOLD_H) - min(prior, WEEKLY_OT_THRESHOLD_H))
        overtime = hours_d - regular
    straight = round_half_up_int(regular * base * mult)
    ot_comp = round_half_up_int(overtime * base * OT_MULT * mult)
    fringe = round_half_up_int(hours_d * FRINGE_CENTS_PER_HOUR)
    return {
        "regular_hours": num(regular),
        "overtime_hours": num(overtime),
        "base_rate_cents": base,
        "total_cost_cents": straight + ot_comp + fringe,
    }


def alignment_verdict(tolerance_class, offset_d, angular_d):
    """Threshold comparisons in raw input units; equality passes."""
    offset_passed = offset_d <= OFFSET_TOLERANCE_MILS[tolerance_class]
    angular_passed = angular_d <= ANGULAR_TOLERANCE[tolerance_class]
    return {
        "offset_passed": offset_passed,
        "angular_passed": angular_passed,
        "verdict": "PASS" if (offset_passed and angular_passed) else "FAIL",
    }
