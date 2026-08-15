"""PlanVersion adoption: interval truncation, supersession, mid-year
amendment impact projection (scaffold §1.3 mid_year_amendment_impact / PRD §3.2)."""

import re
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from db import store
from services.common import (
    bump, comp_sum, contribution_sum, employees_of_year,
)

Q6 = Decimal("0.000001")


def _interval(version):
    start = date.fromisoformat(version["effective_start"])
    end = date.fromisoformat(version["effective_end"]) if version["effective_end"] else None
    return start, end


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap [start, end); None end = open-ended."""
    if a_end is not None and a_end <= b_start:
        return False
    if b_end is not None and b_end <= a_start:
        return False
    return True


def adopted_versions_of_plan(plan_id, exclude_id=None):
    versions = [v for v in store.plan_versions.values()
                if v["plan_id"] == plan_id and v["status"] == "ADOPTED"
                and v["id"] != exclude_id]
    versions.sort(key=lambda v: (v["created_at"], v["id"]))
    return versions


def overlapping_adopted(version):
    v_start, v_end = _interval(version)
    result = []
    for other in adopted_versions_of_plan(version["plan_id"], exclude_id=version["id"]):
        o_start, o_end = _interval(other)
        if _overlaps(v_start, v_end, o_start, o_end):
            result.append(other)
    return result


def adopt_version(version):
    """Adopt a DRAFT version. Returns (impact_projection, changed_design_or_comp).

    Truncates or supersedes overlapping ADOPTED versions when the new version
    is an amendment. Raises ApiError on interval conflicts.
    """
    from errors import ApiError, ERR_VERSION_INTERVAL_CONFLICT

    v_start, v_end = _interval(version)
    overlappers = overlapping_adopted(version)

    if version["is_amendment"]:
        if not overlappers:
            raise ApiError(ERR_VERSION_INTERVAL_CONFLICT, 409,
                           "Amendment has no overlapping ADOPTED version to amend")
        changed_design_or_comp = False
        for prior in overlappers:
            p_start, p_end = _interval(prior)
            if (prior["comp_definition"] != version["comp_definition"]
                    or prior.get("safe_harbor_design") != version.get("safe_harbor_design")):
                changed_design_or_comp = True
            # Truncate the prior version's effective_end to the amendment's start
            if p_start >= v_start:
                # Truncation empties the interval entirely -> SUPERSEDED
                prior["effective_end"] = prior["effective_start"]
                prior["status"] = "SUPERSEDED"
                bump(prior)
            else:
                prior["effective_end"] = v_start.isoformat()
                bump(prior)
    else:
        if overlappers:
            raise ApiError(ERR_VERSION_INTERVAL_CONFLICT, 409,
                           "Adoption would leave two ADOPTED versions overlapping")
        changed_design_or_comp = False

    version["status"] = "ADOPTED"
    bump(version)

    impact = None
    if version["is_amendment"]:
        impact = mid_year_amendment_impact(version)
        if changed_design_or_comp:
            from services.common import supersede_terminal_test_runs
            for py in store.plan_years.values():
                if py["plan_id"] != version["plan_id"]:
                    continue
                py_start = date.fromisoformat(py["year_start"])
                py_end = date.fromisoformat(py["year_end"])
                if _overlaps(v_start, v_end, py_start,
                             py_end + _one_day()):
                    supersede_terminal_test_runs(py["id"])
    return impact, changed_design_or_comp


def _one_day():
    from datetime import timedelta
    return timedelta(days=1)


def mid_year_amendment_impact(version):
    """Proration + per-employee safe harbor match projection for amendments."""
    v_start, v_end = _interval(version)
    impact_per_year = []
    for py in store.plan_years.values():
        if py["plan_id"] != version["plan_id"]:
            continue
        py_start = date.fromisoformat(py["year_start"])
        py_end = date.fromisoformat(py["year_end"])
        if not _overlaps(v_start, v_end, py_start, py_end + _one_day()):
            continue
        amended_end = v_end if v_end is not None else py_end + _one_day()
        days_amended = (min(amended_end, py_end + _one_day())
                        - max(v_start, py_start)).days
        days_total = (py_end - py_start).days + 1
        proration = (Decimal(days_amended) / Decimal(days_total)).quantize(
            Q6, rounding=ROUND_HALF_UP)
        entry = {
            "plan_year_id": py["id"],
            "days_amended": days_amended,
            "days_total": days_total,
            "proration": float(proration),
        }
        if version.get("safe_harbor_design") in ("BASIC_MATCH", "ENHANCED_MATCH"):
            comp_def = version["comp_definition"]
            projections = []
            total_match = 0
            for e in employees_of_year(py["id"]):
                comp = comp_sum(e["id"], comp_def, "CURRENT_YEAR")
                deferrals = contribution_sum(
                    e["id"], ("ELECTIVE_DEFERRAL",),
                    ("POSTED", "PENDING_DISTRIBUTION"))
                match = _match_under_formula(version.get("sh_match_formula") or "",
                                             deferrals, comp)
                projected = (Decimal(match) * proration).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP)
                projected = int(projected)
                total_match += projected
                projections.append({
                    "census_employee_id": e["id"],
                    "projected_match_cents": projected,
                })
            entry["projected_safe_harbor_match_cents"] = total_match
            entry["per_employee"] = projections
        impact_per_year.append(entry)
    return {"amendment_impact": impact_per_year}


_FORMULA_RE = re.compile(
    r"(\d+(?:\.\d+)?)%\s*of\s*(?:first|next)\s*(\d+(?:\.\d+)?)%")


def _match_under_formula(formula, deferrals_cents, comp_cents):
    """Parse descriptors like '100% of first 3% + 50% of next 2%'.

    Tiers apply to the employee's deferral rate against compensation.
    """
    if comp_cents <= 0 or deferrals_cents <= 0 or not formula:
        return 0
    deferral_rate = Decimal(100) * Decimal(deferrals_cents) / Decimal(comp_cents)
    match_pct_of_comp = Decimal(0)
    tier_base = Decimal(0)
    for match_pct_s, tier_pct_s in _FORMULA_RE.findall(formula):
        match_pct = Decimal(match_pct_s)
        tier_pct = Decimal(tier_pct_s)
        applied = max(Decimal(0), min(deferral_rate - tier_base, tier_pct))
        match_pct_of_comp += applied * match_pct / Decimal(100)
        tier_base += tier_pct
    match_cents = (match_pct_of_comp * Decimal(comp_cents) / Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(match_cents)
