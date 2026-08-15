"""Nondiscrimination testing engine (scaffold §1.3 / PRD §3.6)."""

import hashlib
from decimal import Decimal, ROUND_HALF_UP

from db import store
from services.common import (
    Q4, active_limit_for_year, adopted_comp_definition, bump, comp_sum,
    contribution_sum, employees_of_year, new_entity, plan_of_year,
)

COVERAGE_THRESHOLD_PCT = Decimal("70.0")
TOP_HEAVY_THRESHOLD_PCT = Decimal("60.0")
CAFETERIA_ELIGIBILITY_THRESHOLD_PCT = Decimal("70.0")
KEY_CONCENTRATION_CEILING_PCT = Decimal("25.0")
AVERAGE_BENEFITS_RATIO = Decimal("0.55")
BASIC_MULTIPLIER = Decimal("1.25")
ALT_ADDER_PCT = Decimal("2.0")
ALT_MULTIPLIER = Decimal("2.0")
FLOOR_PCT = Decimal("3.0")
ZERO4 = Decimal("0.0000")


def _q4(value):
    return Decimal(value).quantize(Q4, rounding=ROUND_HALF_UP)


def _mean(ratios):
    if not ratios:
        return ZERO4
    return _q4(sum(ratios) / Decimal(len(ratios)))


def engine_input_hash(py):
    """Deterministic hash of census lock version + sorted contribution ids."""
    contrib_ids = sorted(
        c["id"] for c in store.contributions.values()
        if store.census_employees.get(c["census_employee_id"], {}).get("plan_year_id") == py["id"]
    )
    payload = "%s|%s" % (py["census_lock_version"], ",".join(contrib_ids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _make_line(run, metric, value_pct, threshold_pct, outcome, detail):
    line = new_entity({
        "test_run_id": run["id"],
        "metric": metric,
        "value_pct": float(_q4(value_pct)),
        "threshold_pct": float(_q4(threshold_pct)) if threshold_pct is not None else None,
        "outcome": outcome,
        "detail": detail or {},
    })
    store.test_result_lines[line["id"]] = line
    return line


def _cohort(py, for_adr=False):
    employees = employees_of_year(py["id"])
    if for_adr:
        return [e for e in employees
                if e["hce_status"] in ("HCE", "NHCE")
                and e["covered_status"] in ("BENEFITING", "ELIGIBLE_NOT_BENEFITING")]
    return employees


# --------------------------------------------------------------------------
# Coverage 410(b)
# --------------------------------------------------------------------------

def _coverage_410b(run, py):
    employees = [e for e in employees_of_year(py["id"])
                 if e["hce_status"] != "EXCLUDED_FROM_TESTING"]
    benefiting_hce = [e for e in employees if e["covered_status"] == "BENEFITING" and e["hce_status"] == "HCE"]
    eligible_hce = [e for e in employees if e["hce_status"] == "HCE" and e["covered_status"] != "EXCLUDABLE"]
    benefiting_nhce = [e for e in employees if e["covered_status"] == "BENEFITING" and e["hce_status"] == "NHCE"]
    eligible_nhce = [e for e in employees if e["hce_status"] == "NHCE" and e["covered_status"] != "EXCLUDABLE"]
    detail = {
        "benefiting_hce_count": len(benefiting_hce),
        "eligible_hce_count": len(eligible_hce),
        "benefiting_nhce_count": len(benefiting_nhce),
        "eligible_nhce_count": len(eligible_nhce),
        "benefiting_hce_member_ids": [e["id"] for e in benefiting_hce],
        "benefiting_nhce_member_ids": [e["id"] for e in benefiting_nhce],
    }
    if len(eligible_hce) == 0:
        _make_line(run, "COVERAGE_RATIO_PCT", ZERO4, COVERAGE_THRESHOLD_PCT,
                   "NOT_APPLICABLE", detail)
        return
    hce_pct = Decimal(100) * Decimal(len(benefiting_hce)) / Decimal(len(eligible_hce))
    nhce_pct = Decimal(100) * Decimal(len(benefiting_nhce)) / Decimal(len(eligible_nhce)) if eligible_nhce else Decimal(0)
    ratio = (nhce_pct / hce_pct * Decimal(100)) if hce_pct > 0 else Decimal(0)
    value = _q4(ratio)
    outcome = "PASS" if value >= COVERAGE_THRESHOLD_PCT else "FAIL"
    _make_line(run, "COVERAGE_RATIO_PCT", value, COVERAGE_THRESHOLD_PCT, outcome, detail)


# --------------------------------------------------------------------------
# ADP / ACP shared structure
# --------------------------------------------------------------------------

def _member_ratio(e, comp_def, numerator_types, included_statuses):
    comp = comp_sum(e["id"], comp_def, "CURRENT_YEAR")
    numerator = contribution_sum(e["id"], numerator_types, included_statuses)
    if comp > 0:
        ratio = _q4(Decimal(100) * Decimal(numerator) / Decimal(comp))
    else:
        ratio = ZERO4
    return ratio, comp, numerator


def _deferral_statuses(run_mode):
    # Both modes include POSTED and PENDING_DISTRIBUTION. PROVISIONAL also
    # treats DISTRIBUTED / RECHARACTERIZED amounts as if still posted; FINAL
    # excludes them (scaffold adp_test_401k provisional_vs_final variant).
    statuses = ["POSTED", "PENDING_DISTRIBUTION"]
    if run_mode == "PROVISIONAL":
        statuses.extend(["DISTRIBUTED", "RECHARACTERIZED"])
    return tuple(statuses)


def _adp_acp(run, py, comp_def, numerator_types, prefix):
    cohort = _cohort(py, for_adr=True)
    statuses = _deferral_statuses(run["run_mode"])
    hce_members = [e for e in cohort if e["hce_status"] == "HCE"]
    nhce_members = [e for e in cohort if e["hce_status"] == "NHCE"]

    hce_ratios = []
    nhce_ratios = []
    member_breakdown = []
    for e in cohort:
        ratio, comp, numerator = _member_ratio(e, comp_def, numerator_types, statuses)
        member_breakdown.append({
            "member_id": e["id"],
            "hce_status": e["hce_status"],
            "comp_cents": comp,
            "numerator_cents": numerator,
            "ratio_pct": float(ratio),
        })
        if e["hce_status"] == "HCE":
            hce_ratios.append(ratio)
        else:
            nhce_ratios.append(ratio)

    avg_hce = _mean(hce_ratios)
    avg_nhce = _mean(nhce_ratios)
    ceiling = max(avg_nhce * BASIC_MULTIPLIER,
                  min(avg_nhce + ALT_ADDER_PCT, avg_nhce * ALT_MULTIPLIER))
    ceiling = _q4(ceiling)
    outcome = "PASS" if avg_hce <= ceiling else "FAIL"

    base_detail = {
        "hce_cohort_size": len(hce_members),
        "nhce_cohort_size": len(nhce_members),
        "member_ids": [e["id"] for e in hce_members],
        "members": member_breakdown,
    }
    _make_line(run, "%s_HCE_PCT" % prefix, avg_hce, ceiling, outcome,
               dict(base_detail, average_pct=float(avg_hce)))
    _make_line(run, "%s_NHCE_PCT" % prefix, avg_nhce, ceiling, outcome,
               dict(base_detail, average_pct=float(avg_nhce)))
    _make_line(run, "%s_CEILING_PCT" % prefix, ceiling, ceiling, outcome,
               dict(base_detail, ceiling_pct=float(ceiling)))


def _adp_401k(run, py, comp_def):
    _adp_acp(run, py, comp_def, ("ELECTIVE_DEFERRAL",), "ADP")


def _acp_401m(run, py, comp_def):
    _adp_acp(run, py, comp_def, ("MATCH", "QMAC"), "ACP")


# --------------------------------------------------------------------------
# Top-heavy 416
# --------------------------------------------------------------------------

TOP_HEAVY_STATUSES = ("POSTED", "PENDING_DISTRIBUTION", "DISTRIBUTED")


def _top_heavy(run, py, comp_def):
    employees = employees_of_year(py["id"])
    key_members = [e for e in employees if e["key_employee_status"] == "KEY"]
    counted = [e for e in employees if e["key_employee_status"] != "EXCLUDED_FROM_TESTING"]
    all_types = ("ELECTIVE_DEFERRAL", "MATCH", "QNEC", "QMAC", "PROFIT_SHARING",
                 "CAFETERIA_PRETAX", "DEPENDENT_CARE_ELECTIVE")
    key_balance = sum(contribution_sum(e["id"], all_types, TOP_HEAVY_STATUSES)
                      for e in key_members)
    all_balance = sum(contribution_sum(e["id"], all_types, TOP_HEAVY_STATUSES)
                      for e in counted)
    if all_balance > 0:
        ratio = _q4(Decimal(100) * Decimal(key_balance) / Decimal(all_balance))
    else:
        ratio = ZERO4
    outcome = "FAIL" if ratio > TOP_HEAVY_THRESHOLD_PCT else "PASS"
    detail = {
        "key_balance_cents": key_balance,
        "total_balance_cents": all_balance,
        "key_member_ids": [e["id"] for e in key_members],
        "key_cohort_size": len(key_members),
        "counted_cohort_size": len(counted),
    }
    if outcome == "FAIL" and run["run_mode"] == "FINAL":
        detail["min_contribution_cents"] = _top_heavy_minimum_contribution(py, comp_def)
    _make_line(run, "TOP_HEAVY_RATIO_PCT", ratio, TOP_HEAVY_THRESHOLD_PCT, outcome, detail)


def _top_heavy_minimum_contribution(py, comp_def):
    """Least of 3% of NHCE comp or highest key rate; sum of NHCE shortfalls."""
    employees = employees_of_year(py["id"])
    key_members = [e for e in employees if e["key_employee_status"] == "KEY"]
    employer_types = ("MATCH", "QNEC", "QMAC", "PROFIT_SHARING")
    all_types = ("ELECTIVE_DEFERRAL", "MATCH", "QNEC", "QMAC", "PROFIT_SHARING",
                 "CAFETERIA_PRETAX", "DEPENDENT_CARE_ELECTIVE")
    key_rate_max = Decimal(0)
    for e in key_members:
        comp = comp_sum(e["id"], comp_def, "CURRENT_YEAR")
        if comp > 0:
            contribs = contribution_sum(e["id"], all_types, TOP_HEAVY_STATUSES)
            rate = Decimal(100) * Decimal(contribs) / Decimal(comp)
            if rate > key_rate_max:
                key_rate_max = rate
    floor_pct = min(FLOOR_PCT, key_rate_max)
    total_minimum = 0
    nhce_benefiting = [e for e in employees
                       if e["hce_status"] == "NHCE" and e["covered_status"] == "BENEFITING"]
    nhce_benefiting.sort(key=lambda e: (e["created_at"], e["id"]))
    for e in nhce_benefiting:
        comp = comp_sum(e["id"], comp_def, "CURRENT_YEAR")
        owed = (floor_pct * Decimal(comp) / Decimal(100)).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP)
        already = contribution_sum(e["id"], employer_types,
                                   ("POSTED", "PENDING_DISTRIBUTION"))
        shortfall = int(owed) - already
        if shortfall > 0:
            total_minimum += shortfall
    return total_minimum


# --------------------------------------------------------------------------
# Cafeteria 125
# --------------------------------------------------------------------------

def _cafeteria_125(run, py):
    employees = employees_of_year(py["id"])
    nhce_nonexcludable = [e for e in employees
                          if e["hce_status"] == "NHCE" and e["covered_status"] != "EXCLUDABLE"]
    eligible_nhce = [e for e in nhce_nonexcludable
                     if e["covered_status"] in ("BENEFITING", "ELIGIBLE_NOT_BENEFITING")]
    if nhce_nonexcludable:
        eligibility = _q4(Decimal(100) * Decimal(len(eligible_nhce)) / Decimal(len(nhce_nonexcludable)))
    else:
        eligibility = ZERO4
    elig_outcome = "PASS" if eligibility >= CAFETERIA_ELIGIBILITY_THRESHOLD_PCT else "FAIL"
    _make_line(run, "CAFETERIA_ELIGIBILITY_PCT", eligibility,
               CAFETERIA_ELIGIBILITY_THRESHOLD_PCT, elig_outcome, {
                   "eligible_nhce_count": len(eligible_nhce),
                   "nhce_nonexcludable_count": len(nhce_nonexcludable),
                   "eligible_nhce_member_ids": [e["id"] for e in eligible_nhce],
               })

    key_members = [e for e in employees if e["key_employee_status"] == "KEY"]
    pretax_total = sum(
        contribution_sum(e["id"], ("CAFETERIA_PRETAX",), ("POSTED",))
        for e in employees if e["key_employee_status"] != "EXCLUDED_FROM_TESTING")
    pretax_key = sum(contribution_sum(e["id"], ("CAFETERIA_PRETAX",), ("POSTED",))
                     for e in key_members)
    if pretax_total > 0:
        concentration = _q4(Decimal(100) * Decimal(pretax_key) / Decimal(pretax_total))
    else:
        concentration = ZERO4
    conc_outcome = "PASS" if concentration <= KEY_CONCENTRATION_CEILING_PCT else "FAIL"
    _make_line(run, "KEY_EMPLOYEE_CONCENTRATION_PCT", concentration,
               KEY_CONCENTRATION_CEILING_PCT, conc_outcome, {
                   "key_pretax_cents": pretax_key,
                   "total_pretax_cents": pretax_total,
                   "key_member_ids": [e["id"] for e in key_members],
               })

    # Utilization: share of non-excludable NHCEs actually benefiting.
    utilizing = [e for e in nhce_nonexcludable if e["covered_status"] == "BENEFITING"]
    if nhce_nonexcludable:
        utilization = _q4(Decimal(100) * Decimal(len(utilizing)) / Decimal(len(nhce_nonexcludable)))
    else:
        utilization = ZERO4
    _make_line(run, "CAFETERIA_UTILIZATION_PCT", utilization,
               None, "NOT_APPLICABLE", {
                   "utilizing_nhce_count": len(utilizing),
                   "nhce_nonexcludable_count": len(nhce_nonexcludable),
               })


# --------------------------------------------------------------------------
# Dependent care 129
# --------------------------------------------------------------------------

def _dependent_care_129(run, py, comp_def):
    limit = active_limit_for_year(py["year_label"])
    cap = limit["dependent_care_limit_cents"] if limit else 0
    employees = [e for e in employees_of_year(py["id"])
                 if e["hce_status"] != "EXCLUDED_FROM_TESTING"
                 and e["covered_status"] != "EXCLUDABLE"]
    hce_ratios = []
    nhce_ratios = []
    member_breakdown = []
    for e in employees:
        benefit = contribution_sum(e["id"], ("DEPENDENT_CARE_ELECTIVE",), ("POSTED",))
        benefit = min(benefit, cap)
        comp = comp_sum(e["id"], comp_def, "CURRENT_YEAR")
        ratio = _q4(Decimal(100) * Decimal(benefit) / Decimal(comp)) if comp > 0 else ZERO4
        member_breakdown.append({
            "member_id": e["id"],
            "hce_status": e["hce_status"],
            "benefit_cents": benefit,
            "comp_cents": comp,
            "ratio_pct": float(ratio),
        })
        if e["hce_status"] == "HCE":
            hce_ratios.append(ratio)
        else:
            nhce_ratios.append(ratio)
    avg_hce = _mean(hce_ratios)
    avg_nhce = _mean(nhce_ratios)
    if avg_nhce > 0:
        value = _q4(Decimal(100) * avg_hce / avg_nhce)
    else:
        value = ZERO4 if avg_hce == 0 else Decimal("999.9999")
    outcome = "PASS" if avg_hce <= AVERAGE_BENEFITS_RATIO * avg_nhce else "FAIL"
    _make_line(run, "DEPENDENT_CARE_55PCT_AVG_PCT", value, Decimal("55.0"), outcome, {
        "avg_hce_pct": float(avg_hce),
        "avg_nhce_pct": float(avg_nhce),
        "hce_cohort_size": len(hce_ratios),
        "nhce_cohort_size": len(nhce_ratios),
        "members": member_breakdown,
    })


# --------------------------------------------------------------------------
# Engine driver
# --------------------------------------------------------------------------

SCOPE_BATTERIES = {
    "COVERAGE_410B": ("coverage",),
    "ADP_401K": ("adp",),
    "ACP_401M": ("acp",),
    "TOP_HEAVY_416": ("top_heavy",),
    "CAFETERIA_125": ("cafeteria",),
    "DEPENDENT_CARE_129": ("dependent_care",),
    "FULL_SUITE": ("coverage", "adp", "acp", "top_heavy", "cafeteria", "dependent_care"),
}


def execute_run(run):
    """Advance QUEUED -> RUNNING -> PASSED/FAILED synchronously."""
    py = store.plan_years[run["plan_year_id"]]
    plan = plan_of_year(py)
    comp_def = adopted_comp_definition(py)
    run["status"] = "RUNNING"
    bump(run)

    for battery in SCOPE_BATTERIES[run["test_scope"]]:
        if battery == "coverage":
            _coverage_410b(run, py)
        elif battery == "adp":
            _adp_401k(run, py, comp_def)
        elif battery == "acp":
            _acp_401m(run, py, comp_def)
        elif battery == "top_heavy":
            _top_heavy(run, py, comp_def)
        elif battery == "cafeteria":
            if plan and plan["plan_type"] == "CAFETERIA_125":
                _cafeteria_125(run, py)
        elif battery == "dependent_care":
            if plan and plan["plan_type"] == "DEPENDENT_CARE_FSA":
                _dependent_care_129(run, py, comp_def)

    lines = [l for l in store.test_result_lines.values() if l["test_run_id"] == run["id"]]
    failed = any(l["outcome"] == "FAIL" for l in lines)
    if failed:
        run["status"] = "FAILED"
        run["overall_result"] = "FAIL"
        _flag_failed_distribution_review(run, py, lines)
    else:
        run["status"] = "PASSED"
        run["overall_result"] = "PASS"
    bump(run)
    return run


def _flag_failed_distribution_review(run, py, lines):
    """FINAL run failing ADP/ACP: flag HCE members' POSTED deferral/match
    contributions for distribution review via the line detail payload (no
    status change on the contributions themselves)."""
    if run["run_mode"] != "FINAL":
        return
    for line in lines:
        if line["metric"] in ("ADP_HCE_PCT", "ADP_CEILING_PCT",
                              "ACP_HCE_PCT", "ACP_CEILING_PCT") and line["outcome"] == "FAIL":
            member_ids = line.get("detail", {}).get("member_ids", [])
            flagged = []
            for c in store.contributions.values():
                if (c["census_employee_id"] in member_ids
                        and c["status"] == "POSTED"
                        and c["contribution_type"] in ("ELECTIVE_DEFERRAL", "MATCH")):
                    flagged.append(c["id"])
            line["detail"]["distribution_review_contribution_ids"] = flagged
            bump(line)
