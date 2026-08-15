"""Calculation rules (SCAFFOLD.yaml §1.3): adjusted_pay_gap (REGRESSION_OLS /
COHORT_MEDIAN), remediation_suggested_allocation (FULL_CLOSURE / PRO_RATA),
eeo_band_aggregation, pipeline pass-rate analytics. Round-half-up throughout,
with staged rounding applied exactly as specified (PRD §2.7)."""
from decimal import Decimal

from db import db
from services.core import snapshots_of_group, snapshots_of_study, findings_of_study
from util import D, round_half_up

LEVEL_LOADING = Decimal("0.04")
FOUR_FIFTHS_THRESHOLD = Decimal("0.80")

DIMENSION_FIELD = {
    "GENDER": "gender_class",
    "ETHNICITY": "ethnicity_class",
    "AGE_BAND": "age_band",
}
REFERENCE_CLASS = {
    "GENDER": "MALE",
    "ETHNICITY": "WHITE",
    "AGE_BAND": "UNDER_40",
}


# ---------------------------------------------------------------------------
# EmployeeSnapshot derived fields (fte_annualized_base)
# ---------------------------------------------------------------------------

def compute_annualized_base_cents(base_salary_cents, fte_factor) -> int:
    """ROUND(base_salary_cents / fte_factor, 0) half-up."""
    return int(round_half_up(D(base_salary_cents) / D(fte_factor), 0))


def compute_tenure_years(analysis_period_end_iso, hire_date_iso) -> float:
    """ROUND((analysis_period_end - hire_date).days / 365.25, 2) half-up."""
    from util import parse_date
    days = (parse_date(analysis_period_end_iso) - parse_date(hire_date_iso)).days
    return float(round_half_up(D(days) / D("365.25"), 2))


# ---------------------------------------------------------------------------
# adjusted_pay_gap (ModelRun per_class_results)
# ---------------------------------------------------------------------------

def _median_decimal(values):
    """Median of a sorted list of ints; even count -> exact mean of the two
    middle values (may be a .5 Decimal)."""
    vals = sorted(values)
    n = len(vals)
    mid = n // 2
    if n % 2 == 1:
        return D(vals[mid])
    return (D(vals[mid - 1]) + D(vals[mid])) / Decimal(2)


def compute_per_class_results(group, study, methodology):
    """Compute per_class_results for a ModelRun at creation time (PRD §3.2).

    One entry per dimension in study.protected_classes, per non-reference class
    value present among members, provided class_headcount >= 1 and
    reference_headcount >= 1.
    """
    members = snapshots_of_group(group["id"])
    results = {}
    for dimension in study["protected_classes"]:
        field = DIMENSION_FIELD[dimension]
        ref_class = REFERENCE_CLASS[dimension]
        ref_members = [m for m in members if m[field] == ref_class]
        ref_hc = len(ref_members)
        if ref_hc == 0:
            continue
        class_values = sorted({m[field] for m in members if m[field] != ref_class})
        for class_value in class_values:
            class_members = [m for m in members if m[field] == class_value]
            class_hc = len(class_members)
            if class_hc == 0:
                continue
            if methodology == "REGRESSION_OLS":
                # Per-employee level-deflated pay, 2dp half-up BEFORE averaging
                def adj_pay(m):
                    deflator = Decimal(1) + LEVEL_LOADING * D(m["job_level"] - 1)
                    return round_half_up(D(m["annualized_base_cents"]) / deflator, 2)
                mean_ref = round_half_up(
                    sum(adj_pay(m) for m in ref_members) / D(ref_hc), 2)
                mean_class = round_half_up(
                    sum(adj_pay(m) for m in class_members) / D(class_hc), 2)
                if mean_ref == 0:
                    gap = Decimal("0.0000")
                else:
                    gap = round_half_up((mean_ref - mean_class) / mean_ref * 100, 4)
            else:  # COHORT_MEDIAN — raw annualized base, median-based
                median_ref = _median_decimal([m["annualized_base_cents"] for m in ref_members])
                median_class = _median_decimal([m["annualized_base_cents"] for m in class_members])
                if median_ref == 0:
                    gap = Decimal("0.0000")
                else:
                    gap = round_half_up((median_ref - median_class) / median_ref * 100, 4)
            # Significance heuristic uses the ROUNDED 4dp gap
            p_value = round_half_up(
                Decimal(1) / (Decimal(1) + D(class_hc) * abs(gap)), 4)
            results[f"{dimension}:{class_value}"] = {
                "reference_class": ref_class,
                "class_headcount": class_hc,
                "reference_headcount": ref_hc,
                "adjusted_gap_pct": float(gap),
                "p_value": float(p_value),
            }
    return results


# ---------------------------------------------------------------------------
# remediation_suggested_allocation (FULL_CLOSURE / PRO_RATA)
# ---------------------------------------------------------------------------

def compute_suggested_allocation(plan):
    """Universe: all TARGETED GapFindings of the plan's study. Per finding,
    affected employees are snapshots of the study in the finding's group whose
    dimension value equals the finding's class_value (PRD §3.4)."""
    study_id = plan["study_id"]
    targeted = [f for f in findings_of_study(study_id) if f["status"] == "TARGETED"]
    targeted.sort(key=lambda f: (f["created_at"], f["_seq"]))
    snaps = snapshots_of_study(study_id)

    rows = []  # (employee_snapshot_id, gap_finding_id, per_capita_gap_cents, created_at, seq)
    for finding in targeted:
        field = DIMENSION_FIELD[finding["protected_class"]]
        affected = [s for s in snaps
                    if s.get("comparator_group_id") == finding["comparator_group_id"]
                    and s[field] == finding["class_value"]]
        affected.sort(key=lambda s: (s["created_at"], s["_seq"]))
        for s in affected:
            per_capita = int(round_half_up(
                D(s["annualized_base_cents"]) * D(finding["adjusted_gap_pct"]) / 100, 0))
            rows.append({
                "employee_snapshot_id": s["id"],
                "gap_finding_id": finding["id"],
                "per_capita_gap_cents": per_capita,
                "_created": s["created_at"],
                "_seq": s["_seq"],
            })

    strategy = plan["allocation_strategy"]
    if strategy == "FULL_CLOSURE":
        for r in rows:
            r["suggested_cents"] = r["per_capita_gap_cents"]
    else:  # PRO_RATA — budget-constrained waterfall with deterministic remainder
        budget = plan["total_budget_cents"]
        total_gap = sum(r["per_capita_gap_cents"] for r in rows)
        if total_gap == 0:
            for r in rows:
                r["suggested_cents"] = 0
        else:
            for r in rows:
                raw = D(r["per_capita_gap_cents"]) * D(budget) / D(total_gap)
                r["suggested_cents"] = int(raw)  # FLOOR (amounts are non-negative)
            remainder = budget - sum(r["suggested_cents"] for r in rows)
            # One cent at a time, ordered by per_capita_gap DESC then created_at ASC,
            # one cent per employee per pass, until remainder == 0.
            order = sorted(rows, key=lambda r: (-r["per_capita_gap_cents"], r["_created"], r["_seq"]))
            idx = 0
            while remainder > 0 and order:
                order[idx % len(order)]["suggested_cents"] += 1
                remainder -= 1
                idx += 1

    suggestions = [{
        "employee_snapshot_id": r["employee_snapshot_id"],
        "gap_finding_id": r["gap_finding_id"],
        "per_capita_gap_cents": r["per_capita_gap_cents"],
        "suggested_cents": r["suggested_cents"],
    } for r in rows]
    return {
        "strategy": strategy,
        "total_suggested_cents": sum(r["suggested_cents"] for r in rows),
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# eeo_band_aggregation (ReportFiling compile)
# ---------------------------------------------------------------------------

BAND_EDGES = [
    ("BAND_A", 0, 5_000_000),
    ("BAND_B", 5_000_000, 7_500_000),
    ("BAND_C", 7_500_000, 10_000_000),
    ("BAND_D", 10_000_000, 15_000_000),
    ("BAND_E", 15_000_000, None),
]
GENDER_ORDER = ["MALE", "FEMALE", "NONBINARY"]


def band_for(annualized_base_cents) -> str:
    """Lower-inclusive / upper-exclusive band edges (PRD §3.5)."""
    for name, lo, hi in BAND_EDGES:
        if annualized_base_cents >= lo and (hi is None or annualized_base_cents < hi):
            return name
    return "BAND_E"


def compile_band_rows(study_id):
    """One row per band x gender_class value present; total == snapshot_count."""
    snaps = snapshots_of_study(study_id)
    counts = {}
    for s in snaps:
        key = (band_for(s["annualized_base_cents"]), s["gender_class"])
        counts[key] = counts.get(key, 0) + 1
    band_rows = []
    for band, _lo, _hi in BAND_EDGES:
        for gender in GENDER_ORDER:
            if (band, gender) in counts:
                band_rows.append({
                    "band": band,
                    "gender_class": gender,
                    "headcount": counts[(band, gender)],
                })
    total = sum(r["headcount"] for r in band_rows)
    return band_rows, total


# ---------------------------------------------------------------------------
# adverse_impact_ratio (PipelineAnalysis)
# ---------------------------------------------------------------------------

def compute_pipeline_analytics(records):
    """pass_rates 4dp half-up per class FIRST; ratio from the ROUNDED rates,
    itself 4dp half-up; flag strictly < 0.80 (0.8000 is NOT flagged);
    highest_rate_class ties broken by earliest records index (PRD §3.6)."""
    pass_rates = {}
    first_index = {}
    for idx, rec in enumerate(records):
        label = rec["class_label"]
        if label not in first_index:
            first_index[label] = idx
        if rec["count_in"] > 0 and label not in pass_rates:
            pass_rates[label] = round_half_up(D(rec["count_passed"]) / D(rec["count_in"]), 4)

    if not pass_rates:
        highest_rate_class = None
    else:
        highest_rate_class = max(
            pass_rates.keys(),
            key=lambda lbl: (pass_rates[lbl], -first_index[lbl]),
        )

    if len(pass_rates) < 2:
        ratio = None
        flag = False
    else:
        ratio = round_half_up(min(pass_rates.values()) / max(pass_rates.values()), 4)
        flag = bool(ratio < FOUR_FIFTHS_THRESHOLD)

    return {
        "pass_rates": {k: float(v) for k, v in pass_rates.items()},
        "adverse_impact_ratio": float(ratio) if ratio is not None else None,
        "adverse_impact_flag": flag,
        "highest_rate_class": highest_rate_class,
    }
