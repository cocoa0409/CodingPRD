"""Diversity metric computations per §1.3 / PRD §3.1."""
from decimal import Decimal, ROUND_HALF_UP

import clock
import db


UNDERREPRESENTED_ETHNICITIES = {"BLACK", "HISPANIC", "NATIVE", "PACIFIC", "TWO_OR_MORE"}


def is_underrepresented(candidate: dict) -> bool:
    if candidate is None:
        return False
    if candidate.get("eeo_ethnicity") in UNDERREPRESENTED_ETHNICITIES:
        return True
    if candidate.get("eeo_disability"):
        return True
    if candidate.get("eeo_veteran"):
        return True
    return False


def _round_4(num: int, denom: int) -> float:
    if denom == 0:
        return 0.0
    val = Decimal(num) / Decimal(denom)
    q = val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


def _year_of_iso(ts: str) -> int:
    # All timestamps stored are ISO UTC with trailing 'Z'.
    return int(ts[:4])


def compute_pool_pct(goal: dict) -> float:
    """Applicant-pool underrepresented percentage for this goal."""
    dept_id = goal["department_id"]
    level = goal["target_level"]
    year = goal["period_year"]

    in_scope_reqs = {
        r["id"] for r in db.requisitions.values()
        if r["department_id"] == dept_id and r["target_level"] == level
    }

    candidates_in_scope = set()
    for a in db.applications.values():
        if a["requisition_id"] not in in_scope_reqs:
            continue
        if a["status"] == "WITHDRAWN":
            continue
        if _year_of_iso(a["created_at"]) != year:
            continue
        candidates_in_scope.add(a["candidate_id"])

    denom = len(candidates_in_scope)
    numer = sum(1 for cid in candidates_in_scope if is_underrepresented(db.candidates.get(cid)))
    return _round_4(numer, denom)


def compute_hire_pct(goal: dict) -> float:
    """Hire-cohort underrepresented percentage for this goal."""
    dept_id = goal["department_id"]
    level = goal["target_level"]
    year = goal["period_year"]

    in_scope_reqs = {
        r["id"] for r in db.requisitions.values()
        if r["department_id"] == dept_id and r["target_level"] == level
    }

    hired_candidate_ids = set()
    for a in db.applications.values():
        if a["requisition_id"] not in in_scope_reqs:
            continue
        if a["status"] != "HIRED":
            continue
        if _year_of_iso(a["updated_at"]) != year:
            continue
        hired_candidate_ids.add(a["candidate_id"])

    denom = len(hired_candidate_ids)
    numer = sum(1 for cid in hired_candidate_ids if is_underrepresented(db.candidates.get(cid)))
    return _round_4(numer, denom)
