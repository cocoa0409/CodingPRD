"""Shared claim monetary computations and cross-entity helpers."""
import db
from services import calculations as calc


def claimant_wage_records(claimant_id):
    return [w for w in db.wage_records.values() if w["claimant_id"] == claimant_id]


def run_monetary(claim):
    """Run the full monetary calculation for a claim, returning a dict of
    results (method, base_total, high_quarter, wba, base_mba).

    Does NOT mutate the claim; caller applies results.
    """
    from datetime import date
    filed = date.fromisoformat(claim["filed_date"])
    records = claimant_wage_records(claim["claimant_id"])
    method, base_total, high_quarter = calc.select_method(filed, records)
    if method == "NONE":
        return {
            "method": "NONE",
            "base_total": 0,
            "high_quarter": 0,
            "wba": 0,
            "base_mba": 0,
        }
    wba = calc.weekly_benefit_amount(high_quarter)
    base_mba = calc.base_maximum_benefit_amount(wba, base_total)
    return {
        "method": method,
        "base_total": base_total,
        "high_quarter": high_quarter,
        "wba": wba,
        "base_mba": base_mba,
    }


def selected_base_period_employers(claim):
    """Distinct base-period employers (selected method's quarter set,
    non-disputed only) with their summed wages and employer ordering metadata.

    Returns list of (employer_id, wages_cents, employer_created_at, employer_seq).
    """
    from datetime import date
    method = claim.get("base_period_method")
    if method not in ("STANDARD", "ALTERNATE"):
        return []
    filed = date.fromisoformat(claim["filed_date"])
    standard_set, alternate_set = calc.base_period_sets(filed)
    quarter_set = standard_set if method == "STANDARD" else alternate_set

    from validate import quarter_key
    wages_by_emp = {}
    for w in claimant_wage_records(claim["claimant_id"]):
        if w.get("is_disputed"):
            continue
        if quarter_key(w["calendar_quarter"]) not in quarter_set:
            continue
        wages_by_emp[w["employer_id"]] = wages_by_emp.get(w["employer_id"], 0) + w["gross_wages_cents"]

    pairs = []
    for emp_id, wages in wages_by_emp.items():
        emp = db.employers.get(emp_id)
        created_at = emp["created_at"] if emp else ""
        seq = emp.get("_seq", 0) if emp else 0
        pairs.append((emp_id, wages, created_at, seq))
    return pairs
