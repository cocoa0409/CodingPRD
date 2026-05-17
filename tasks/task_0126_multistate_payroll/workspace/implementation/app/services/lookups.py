"""Lookup helpers — active W-4 resolution, paycheck history, etc."""
from __future__ import annotations

from datetime import date
from typing import Any

from ..clock import parse_iso_date_str
from ..store import store


def find_active_w4_at_pay_date(employee_id: str, target_pay_date: date) -> dict[str, Any] | None:
    """Active W-4 = the W4Profile whose effective_pay_period.pay_date is the latest
    that is <= target_pay_date; tie-broken by W4Profile.created_at ascending (latest wins).
    """
    s = store()
    candidates = []
    for w4 in s.w4_profiles.values():
        if w4["employee_id"] != employee_id:
            continue
        eff_pp = s.pay_periods.get(w4["effective_pay_period_id"])
        if eff_pp is None:
            continue
        eff_pay_date = parse_iso_date_str(eff_pp["pay_date"])
        if eff_pay_date <= target_pay_date:
            candidates.append((eff_pay_date, w4["created_seq"], w4))

    if not candidates:
        return None
    # Pick max by (eff_pay_date asc, created_seq asc)
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[-1][2]


def find_latest_prior_year_w4(employee_id: str, target_tax_year: int) -> dict[str, Any] | None:
    """Pre-fill source: W-4 whose effective_pay_period.pay_date is the latest in
    the prior tax year (target_tax_year - 1).
    """
    s = store()
    prior_year = target_tax_year - 1
    candidates = []
    for w4 in s.w4_profiles.values():
        if w4["employee_id"] != employee_id:
            continue
        eff_pp = s.pay_periods.get(w4["effective_pay_period_id"])
        if eff_pp is None:
            continue
        eff_pay_date = parse_iso_date_str(eff_pp["pay_date"])
        if eff_pay_date.year == prior_year:
            candidates.append((eff_pay_date, w4["created_seq"], w4))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[-1][2]


def has_prefilled_w4_for_year(employee_id: str, target_tax_year: int) -> bool:
    """Whether an (employee, prefilled_from_prior_year=True) profile already exists
    that targets the same tax year (year of its effective_pay_period.pay_date).
    """
    s = store()
    for w4 in s.w4_profiles.values():
        if w4["employee_id"] != employee_id:
            continue
        if not w4.get("prefilled_from_prior_year"):
            continue
        eff_pp = s.pay_periods.get(w4["effective_pay_period_id"])
        if eff_pp is None:
            continue
        eff_pay_date = parse_iso_date_str(eff_pp["pay_date"])
        if eff_pay_date.year == target_tax_year:
            return True
    return False


def employee_has_pending_paycheck(employee_id: str) -> bool:
    """True if any paycheck for the employee is in DRAFT or CALCULATED."""
    for pc in store().paychecks.values():
        if pc["employee_id"] == employee_id and pc["status"] in ("DRAFT", "CALCULATED"):
            return True
    return False


def employee_paychecks_in_year(employee_id: str, tax_year: int) -> list[dict[str, Any]]:
    s = store()
    out = []
    for pc in s.paychecks.values():
        if pc["employee_id"] != employee_id:
            continue
        pp = s.pay_periods.get(pc["pay_period_id"])
        if pp is None:
            continue
        py = parse_iso_date_str(pp["pay_date"]).year
        if py == tax_year:
            out.append(pc)
    return out


def previous_paycheck_for_employee(
    employee_id: str, current_paycheck: dict[str, Any]
) -> dict[str, Any] | None:
    """The 'most recent prior paycheck' for the employee — i.e., the paycheck with
    the greatest created_seq strictly less than current_paycheck's created_seq.
    Used to detect the 'prior paycheck was voided in same tax_year' condition.
    """
    s = store()
    current_seq = current_paycheck["created_seq"]
    pp = s.pay_periods.get(current_paycheck["pay_period_id"])
    if pp is None:
        return None
    current_year = parse_iso_date_str(pp["pay_date"]).year
    candidates = []
    for pc in s.paychecks.values():
        if pc["employee_id"] != employee_id:
            continue
        if pc["id"] == current_paycheck["id"]:
            continue
        if pc["created_seq"] >= current_seq:
            continue
        ppc = s.pay_periods.get(pc["pay_period_id"])
        if ppc is None:
            continue
        py = parse_iso_date_str(ppc["pay_date"]).year
        if py != current_year:
            continue
        candidates.append(pc)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p["created_seq"])
    return candidates[-1]


def active_garnishments_for_employee(
    employee_id: str, target_pay_date: date
) -> list[dict[str, Any]]:
    """ACTIVE garnishment orders effective at target_pay_date, sorted by
    (priority_rank, created_at, id) ascending.
    """
    s = store()
    orders = []
    for g in s.garnishment_orders.values():
        if g["employee_id"] != employee_id:
            continue
        if g["status"] != "ACTIVE":
            continue
        eff = parse_iso_date_str(g["effective_pay_date"])
        if eff > target_pay_date:
            continue
        orders.append(g)
    orders.sort(key=lambda g: (g["priority_rank"], g["created_seq"], g["id"]))
    return orders


def paychecks_in_pay_period(pay_period_id: str) -> list[dict[str, Any]]:
    return [pc for pc in store().paychecks.values() if pc["pay_period_id"] == pay_period_id]


def paychecks_in_year_month(tax_year: int, tax_month: int) -> list[dict[str, Any]]:
    s = store()
    out = []
    for pc in s.paychecks.values():
        pp = s.pay_periods.get(pc["pay_period_id"])
        if pp is None:
            continue
        d = parse_iso_date_str(pp["pay_date"])
        if d.year == tax_year and d.month == tax_month:
            out.append(pc)
    return out


def pay_periods_in_year_month(tax_year: int, tax_month: int) -> list[dict[str, Any]]:
    s = store()
    out = []
    for pp in s.pay_periods.values():
        d = parse_iso_date_str(pp["pay_date"])
        if d.year == tax_year and d.month == tax_month:
            out.append(pp)
    return out
