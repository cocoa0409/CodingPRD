"""Census-lock determination sweep: ownership attribution, HCE, key employee,
and coverage cohort classification (scaffold §1.3 / PRD §3.5)."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from db import store
from services.common import (
    Q4, active_limit_for_year, comp_sum, contribution_sum, employees_of_year,
    plan_of_year, employer_of_plan, bump,
)

HCE_OWNERSHIP_TEST_PCT = Decimal("5.0")
KEY_OWNERSHIP_TEST_PCT = Decimal("5.0")
KEY_ONE_PCT_OWNER_TEST_PCT = Decimal("1.0")
ONE_PCT_OWNER_COMP_CENTS = 15000000
OWNERSHIP_CAP_PCT = Decimal("100.0000")


def _plan_year_comp_definition(py, adopted_version):
    return adopted_version["comp_definition"]


def ownership_attribution(py):
    """IRC 318-style rollup: direct + family-in + family-out, capped at 100.

    Family attribution flows both directions along the declared link, one hop
    only (A->B->C does not attribute A to C).
    """
    employees = employees_of_year(py["id"])
    by_ssn = {e["ssn"]: e for e in employees}
    for e in employees:
        attributed = Decimal(str(e["ownership_pct_direct"]))
        # family in: employees who name e as their family member
        for f in employees:
            if f["id"] == e["id"]:
                continue
            if f.get("family_member_of_ssn") == e["ssn"]:
                attributed += Decimal(str(f["ownership_pct_direct"]))
        # family out: the employee e names as family member
        ref_ssn = e.get("family_member_of_ssn")
        if ref_ssn and ref_ssn != e["ssn"]:
            p = by_ssn.get(ref_ssn)
            if p is not None:
                attributed += Decimal(str(p["ownership_pct_direct"]))
        attributed = attributed.quantize(Q4, rounding=ROUND_HALF_UP)
        e["attributed_ownership_pct"] = float(min(attributed, OWNERSHIP_CAP_PCT))


def hce_determination(py, adopted_version):
    """HCE on lookback-year (PRIOR_YEAR) compensation, ownership, officer prongs."""
    limit = active_limit_for_year(py["year_label"])
    comp_def = _plan_year_comp_definition(py, adopted_version)
    year_start = date.fromisoformat(py["year_start"])
    for e in employees_of_year(py["id"]):
        if (e["employment_status"] == "TERMINATED"
                and e.get("date_of_termination")
                and date.fromisoformat(e["date_of_termination"]) < year_start):
            e["hce_status"] = "EXCLUDED_FROM_TESTING"
            continue
        comp_prior = comp_sum(e["id"], comp_def, "PRIOR_YEAR")
        attributed = Decimal(str(e.get("attributed_ownership_pct", 0) or 0))
        is_hce = (
            attributed > HCE_OWNERSHIP_TEST_PCT
            or comp_prior > limit["hce_comp_threshold_cents"]
            or (e["is_officer"] and comp_prior > limit["key_officer_comp_threshold_cents"])
        )
        e["hce_status"] = "HCE" if is_hce else "NHCE"


def key_employee_determination(py, adopted_version):
    """Key employee on CURRENT_YEAR compensation + ownership + officer prongs."""
    limit = active_limit_for_year(py["year_label"])
    comp_def = _plan_year_comp_definition(py, adopted_version)
    year_start = date.fromisoformat(py["year_start"])
    for e in employees_of_year(py["id"]):
        if (e["employment_status"] == "TERMINATED"
                and e.get("date_of_termination")
                and date.fromisoformat(e["date_of_termination"]) < year_start):
            e["key_employee_status"] = "EXCLUDED_FROM_TESTING"
            continue
        comp_cur = comp_sum(e["id"], comp_def, "CURRENT_YEAR")
        attributed = Decimal(str(e.get("attributed_ownership_pct", 0) or 0))
        is_key = (
            attributed > KEY_OWNERSHIP_TEST_PCT
            or (attributed > KEY_ONE_PCT_OWNER_TEST_PCT
                and comp_cur > ONE_PCT_OWNER_COMP_CENTS)
            or (e["is_officer"] and comp_cur > limit["key_officer_comp_threshold_cents"])
        )
        e["key_employee_status"] = "KEY" if is_key else "NON_KEY"


def coverage_cohort_classification(py):
    """Assign covered_status from current census snapshot inputs.

    INELIGIBLE: never eligible by lock day (hired after year_end).
    EXCLUDABLE: statutory exclusions (terminated before or during the plan
    year, or hired after year_start — not yet eligible for the full year).
    BENEFITING: has any posted plan-year accrual or an active safe harbor
    design covering the year.
    ELIGIBLE_NOT_BENEFITING: otherwise.
    """
    plan = plan_of_year(py)
    employer = employer_of_plan(plan) if plan else None
    plan_type = plan["plan_type"] if plan else "401K"
    adopted = store.plan_versions.get(py["adopted_version_id"]) if py.get("adopted_version_id") else None
    safe_harbor_active = bool(
        adopted and adopted.get("safe_harbor_design") in
        ("BASIC_MATCH", "ENHANCED_MATCH", "QNEC_3PCT", "QACA")
    )
    if plan_type == "401K":
        benefit_types = ("ELECTIVE_DEFERRAL", "MATCH", "QNEC", "QMAC", "PROFIT_SHARING")
    elif plan_type == "CAFETERIA_125":
        benefit_types = ("CAFETERIA_PRETAX",)
    else:
        benefit_types = ("DEPENDENT_CARE_ELECTIVE",)

    year_start = date.fromisoformat(py["year_start"])
    year_end = date.fromisoformat(py["year_end"])
    for e in employees_of_year(py["id"]):
        hire = date.fromisoformat(e["date_of_hire"]) if e.get("date_of_hire") else None
        term = date.fromisoformat(e["date_of_termination"]) if e.get("date_of_termination") else None
        if hire is not None and hire > year_end:
            e["covered_status"] = "INELIGIBLE"
            continue
        if term is not None and term <= year_end:
            e["covered_status"] = "EXCLUDABLE"
            continue
        if hire is not None and hire > year_start:
            e["covered_status"] = "EXCLUDABLE"
            continue
        posted = contribution_sum(e["id"], benefit_types,
                                  ("POSTED", "PENDING_DISTRIBUTION", "DISTRIBUTED"))
        if posted > 0 or safe_harbor_active:
            e["covered_status"] = "BENEFITING"
        else:
            e["covered_status"] = "ELIGIBLE_NOT_BENEFITING"


def run_determination_sweep(py, adopted_version):
    """The four determinations, in scaffold order, then persist timestamps."""
    ownership_attribution(py)
    hce_determination(py, adopted_version)
    key_employee_determination(py, adopted_version)
    coverage_cohort_classification(py)
    for e in employees_of_year(py["id"]):
        bump(e)
