"""YTD ledger and Employee.ytd_* reconciliation."""
from __future__ import annotations

from typing import Any

from ..clock import now_iso, parse_iso_date_str
from ..helpers import new_uuid
from ..store import store


def append_ledger_entry(
    employee_id: str,
    paycheck_id: str,
    tax_year: int,
    gross_delta_cents: int,
    ss_wages_delta_cents: int,
    medicare_wages_delta_cents: int,
    entry_kind: str,
) -> dict[str, Any]:
    s = store()
    entry_id = new_uuid()
    entry = {
        "id": entry_id,
        "employee_id": employee_id,
        "paycheck_id": paycheck_id,
        "tax_year": tax_year,
        "gross_wages_delta_cents": gross_delta_cents,
        "social_security_wages_delta_cents": ss_wages_delta_cents,
        "medicare_wages_delta_cents": medicare_wages_delta_cents,
        "entry_kind": entry_kind,
        "created_at": now_iso(),
        "created_seq": s.next_seq(),
    }
    s.ytd_ledger[entry_id] = entry
    return entry


def recompute_employee_ytd(employee_id: str, tax_year: int) -> None:
    """Recompute Employee.ytd_* fields by summing ledger entries for the year."""
    s = store()
    emp = s.employees.get(employee_id)
    if emp is None:
        return
    g = ss = med = 0
    for e in s.ytd_ledger.values():
        if e["employee_id"] != employee_id:
            continue
        if e["tax_year"] != tax_year:
            continue
        g += e["gross_wages_delta_cents"]
        ss += e["social_security_wages_delta_cents"]
        med += e["medicare_wages_delta_cents"]
    emp["ytd_gross_wages_cents"] = max(0, g)
    emp["ytd_social_security_wages_cents"] = max(0, ss)
    emp["ytd_medicare_wages_cents"] = max(0, med)
    emp["updated_at"] = now_iso()
    emp["version"] = emp["version"] + 1


def paycheck_tax_year(paycheck: dict[str, Any]) -> int:
    pp = store().pay_periods[paycheck["pay_period_id"]]
    return parse_iso_date_str(pp["pay_date"]).year


def employee_ytd_before_paycheck(employee_id: str, tax_year: int) -> dict[str, int]:
    """Compute YTD totals (gross, ss_wages, medicare_wages) from APPROVED ledger entries
    in the given tax year. This matches what Employee.ytd_* should be at any time.
    """
    s = store()
    g = ss = med = 0
    for e in s.ytd_ledger.values():
        if e["employee_id"] != employee_id:
            continue
        if e["tax_year"] != tax_year:
            continue
        g += e["gross_wages_delta_cents"]
        ss += e["social_security_wages_delta_cents"]
        med += e["medicare_wages_delta_cents"]
    return {
        "gross": max(0, g),
        "ss_wages": max(0, ss),
        "medicare_wages": max(0, med),
    }
