"""Budget line commitment + dual-variant forecast, per scaffold section 1.3."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from clock import clock, fiscal_year_of
from db import db

PIPELINE_YIELD = 0.80


def fy_window(fiscal_year):
    """July 1 of (fy-1) through July 1 of fy, half-open."""
    start = datetime(fiscal_year - 1, 7, 1, tzinfo=timezone.utc)
    end = datetime(fiscal_year, 7, 1, tzinfo=timezone.utc)
    return start, end


def months_remaining_in_fy(now):
    """Calendar months left in the fiscal year including the current month."""
    fy = fiscal_year_of(now)
    _, fy_end = fy_window(fy)
    # Count months from now's month through the month before fy_end's month.
    count = 0
    y, m = now.year, now.month
    while (y, m) < (fy_end.year, fy_end.month):
        count += 1
        m += 1
        if m > 12:
            m = 1
            y += 1
    return count


def _differential_for_level(level, at=None):
    """Monthly differential of the active criterion for this level; 0 when none."""
    from services.calculations import active_criterion_for
    if level == "CN_I":
        return 0
    c = active_criterion_for(level, at)
    return c["differential_monthly_cents"] if c else 0


def active_diff_annual(unit):
    """12 months of each ACTIVE-differential nurse's level-keyed monthly differential."""
    total = 0
    for n in db.nurses.values():
        if n["home_unit"] != unit:
            continue
        if n["differential_status"] != "ACTIVE":
            continue
        total += _differential_for_level(n["current_level"]) * 12
    return total


def _cert_nurse(cert_id):
    cert = db.certifications.get(cert_id)
    if cert is None:
        return None, None
    return cert, db.nurses.get(cert["nurse_id"])


def calc_budget_commitment(line):
    """committed = annualized ACTIVE differentials + approved-unpaid claims + accrued-unpaid bonuses."""
    unit = line["unit"]
    fy = line["fiscal_year"]
    fy_start, fy_end = fy_window(fy)

    committed = active_diff_annual(unit)

    for claim in db.reimbursement_claims.values():
        if claim["status"] != "APPROVED" or claim["fiscal_year"] != fy:
            continue
        cert, nurse = _cert_nurse(claim["certification_id"])
        if nurse is None or nurse["home_unit"] != unit:
            continue
        committed += claim["approved_amount_cents"] or 0

    for bonus in db.certification_bonuses.values():
        if bonus["status"] != "ACCRUED":
            continue
        if not (fy_start <= bonus["created_at"] < fy_end):
            continue
        cert, nurse = _cert_nurse(bonus["certification_id"])
        if nurse is None or nurse["home_unit"] != unit:
            continue
        committed += bonus["bonus_amount_cents"]

    return committed


def _paid_one_time_in_fy(unit, fy):
    """PAID claims (claim fiscal_year) + PAID bonuses (paid inside the FY window)."""
    fy_start, fy_end = fy_window(fy)
    total = 0
    for claim in db.reimbursement_claims.values():
        if claim["status"] != "PAID" or claim["fiscal_year"] != fy:
            continue
        cert, nurse = _cert_nurse(claim["certification_id"])
        if nurse is None or nurse["home_unit"] != unit:
            continue
        total += claim["approved_amount_cents"] or 0
    for bonus in db.certification_bonuses.values():
        if bonus["status"] != "PAID":
            continue
        paid_at = bonus.get("paid_at")
        if paid_at is None or not (fy_start <= paid_at < fy_end):
            continue
        cert, nurse = _cert_nurse(bonus["certification_id"])
        if nurse is None or nurse["home_unit"] != unit:
            continue
        total += bonus["bonus_amount_cents"]
    return total


def _pipeline_claims(unit, fy):
    """SUBMITTED claims of unit nurses in this fiscal year, weighted by PIPELINE_YIELD."""
    total = 0
    for claim in db.reimbursement_claims.values():
        if claim["status"] != "SUBMITTED" or claim["fiscal_year"] != fy:
            continue
        cert, nurse = _cert_nurse(claim["certification_id"])
        if nurse is None or nurse["home_unit"] != unit:
            continue
        total += claim["claimed_amount_cents"]
    return total


def calc_budget_forecast(line):
    """Dual-variant forecast. Committed first, then variant-specific term.

    PROVISIONAL: committed + active_diff_annual * (months_remaining/12, 2dp) + 0.80*SUBMITTED pipeline.
    FINAL: committed + PAID one-time actuals inside the fiscal year.
    Final figure rounds half-up to integer cents.
    """
    unit = line["unit"]
    fy = line["fiscal_year"]
    committed = calc_budget_commitment(line)

    if line["forecast_variant"] == "FINAL":
        return committed + _paid_one_time_in_fy(unit, fy)

    now = clock.now()
    mr = months_remaining_in_fy(now)
    frac = (Decimal(mr) / Decimal(12)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    diff_term = Decimal(active_diff_annual(unit)) * frac
    pipeline = Decimal(_pipeline_claims(unit, fy)) * Decimal(str(PIPELINE_YIELD))
    total = Decimal(committed) + diff_term + pipeline
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recompute_budget_for_unit_fy(unit, fy):
    line = find_budget_line(unit, fy)
    if line is None:
        return None
    line["committed_cents"] = calc_budget_commitment(line)
    line["forecast_cents"] = calc_budget_forecast(line)
    from clock import clock as _clk
    line["updated_at"] = _clk.now()
    line["version"] += 1
    return line


def recompute_budgets_for_unit(unit):
    """Recompute every budget line for a unit (differential mutations are FY-agnostic)."""
    for line in db.budget_lines.values():
        if line["unit"] == unit:
            line["committed_cents"] = calc_budget_commitment(line)
            line["forecast_cents"] = calc_budget_forecast(line)
            line["updated_at"] = clock.now()
            line["version"] += 1


def find_budget_line(unit, fy):
    for line in db.budget_lines.values():
        if line["unit"] == unit and line["fiscal_year"] == fy:
            return line
    return None


def budget_guard(unit, fy, amount_cents):
    """(unit FY PAID claims + PAID bonuses + this amount) <= allocated_cents.

    A missing BudgetLine for the unit/FY fails the guard outright.
    Returns (ok, line).
    """
    line = find_budget_line(unit, fy)
    if line is None:
        return False, None
    paid = _paid_one_time_in_fy(unit, fy)
    return (paid + amount_cents) <= line["allocated_cents"], line
