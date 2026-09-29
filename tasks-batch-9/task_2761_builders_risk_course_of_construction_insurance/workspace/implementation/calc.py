"""Every calculation rule of SCAFFOLD.yaml `calculations`, implemented in integer cents
with explicit half-up rounding at the pinned points."""
from decimal import Decimal

from db import by_claim, by_policy, store
from enums import ALLOCATION_ORDER
from util import ceil_div, dec, rhu, whole_days

# ---- quote_premium ----------------------------------------------------------------
CONSTRUCTION_RATE_PER_1000_CENTS = {
    "FRAME": Decimal("210"),
    "JOISTED_MASONRY": Decimal("150"),
    "NON_COMBUSTIBLE": Decimal("110"),
    "FIRE_RESISTIVE": Decimal("80"),
}
CAT_LOAD_PCT = {
    "INLAND": Decimal("0.00"),
    "WIND_TIER_2": Decimal("0.18"),
    "SEISMIC": Decimal("0.25"),
    "WIND_TIER_1": Decimal("0.35"),
    "FLOOD_A": Decimal("0.40"),
}
DURATION_LOAD_PCT_PER_MONTH = Decimal("0.02")
SOFT_COST_RATE_PER_1000_CENTS = Decimal("60")
RENOVATION_LOAD_PCT = Decimal("0.12")
DEDUCTIBLE_CREDIT_PCT = {
    "STANDARD_25K": Decimal("0.00"),
    "ELEVATED_100K": Decimal("0.06"),
    "HIGH_250K": Decimal("0.11"),
}
MIN_PREMIUM_CENTS = 250000
UNIT_CENTS = Decimal("100000")

OCCURRENCE_DEDUCTIBLE_CENTS = {
    "STANDARD_25K": 2500000,
    "ELEVATED_100K": 10000000,
    "HIGH_250K": 25000000,
}

# ---- project_risk_score -----------------------------------------------------------
CONSTRUCTION_PTS = {"FRAME": 30, "JOISTED_MASONRY": 20, "NON_COMBUSTIBLE": 12, "FIRE_RESISTIVE": 6}
CAT_PTS = {"INLAND": 0, "WIND_TIER_2": 12, "SEISMIC": 18, "WIND_TIER_1": 25, "FLOOD_A": 30}
VALUE_PTS_STEP_CENTS = 500000000
REFERRAL_THRESHOLD = 75
INELIGIBLE_THRESHOLD = 90

# ---- claim allocation -------------------------------------------------------------
RECONSTRUCTION_UPLIFT = Decimal("1.08")
PM_WEEKLY_PCT = Decimal("0.0015")
PM_MAX_WEEKS = 12

# ---- delay ------------------------------------------------------------------------
WAITING_PERIOD_DAYS = 5

# ---- extension --------------------------------------------------------------------
MAX_CUMULATIVE_EXTENSION_RATIO_NUM = 1
MAX_CUMULATIVE_EXTENSION_RATIO_DEN = 2
SOD_AP_THRESHOLD_CENTS = 500000
CAT_RESLIP_SCORE_THRESHOLD = 85
CAT_RESLIP_LOAD = Decimal("1.25")

# ---- cancellation -----------------------------------------------------------------
SHORT_RATE_RETENTION_PCT = Decimal("0.90")
SHORT_RATE_FEE_CENTS = 25000

# ---- storage / testing ------------------------------------------------------------
MAX_STORAGE_DISTANCE_MILES = Decimal("100")
HOT_WORK_BUFFER_HOURS = 24


def insured_tiv_cents(project, includes_existing_structure):
    total = project["hard_cost_value_cents"]
    if includes_existing_structure:
        total += project["existing_structure_value_cents"]
    return total


def quote_premium(policy, project):
    """Five loaded components, each rounded independently, then a credit and a floor."""
    units = dec(policy["insured_tiv_cents"]) / UNIT_CENTS
    base_cents = rhu(units * CONSTRUCTION_RATE_PER_1000_CENTS[project["construction_type"]])
    cat_cents = rhu(dec(base_cents) * CAT_LOAD_PCT[project["cat_zone"]])
    term_months = ceil_div(policy["original_term_days"], 30)
    excess_months = max(0, term_months - 12)
    duration_cents = rhu(dec(base_cents) * DURATION_LOAD_PCT_PER_MONTH * dec(excess_months))
    soft_sum = 0
    for part in by_policy(store.coverage_parts, policy["id"]):
        if part["part_type"] in ("SOFT_COST", "DELAY_IN_COMPLETION"):
            soft_sum += part["sublimit_cents"]
    soft_cents = rhu((dec(soft_sum) / UNIT_CENTS) * SOFT_COST_RATE_PER_1000_CENTS)
    if project["project_kind"] == "RENOVATION":
        reno_cents = rhu(dec(base_cents) * RENOVATION_LOAD_PCT)
    else:
        reno_cents = 0
    subtotal_cents = base_cents + cat_cents + duration_cents + soft_cents + reno_cents
    credit_cents = rhu(dec(subtotal_cents) * DEDUCTIBLE_CREDIT_PCT[policy["deductible_tier"]])
    before_floor = subtotal_cents - credit_cents
    return max(MIN_PREMIUM_CENTS, before_floor)


def apply_referral_load(quoted_premium_cents, referral_load_pct):
    return rhu(dec(quoted_premium_cents) * (Decimal("1") + dec(referral_load_pct)))


def _risk_score(project, tiv_cents, duration_days, claim_count):
    construction_pts = CONSTRUCTION_PTS[project["construction_type"]]
    cat_pts = CAT_PTS[project["cat_zone"]]
    value_pts = min(20, tiv_cents // VALUE_PTS_STEP_CENTS)
    duration_pts = min(15, 2 * max(0, ceil_div(duration_days, 30) - 12))
    renovation_pts = 10 if project["project_kind"] == "RENOVATION" else 0
    claim_pts = min(15, 5 * claim_count)
    return min(
        100,
        construction_pts + cat_pts + value_pts + duration_pts + renovation_pts + claim_pts,
    )


def submission_basis_score(project):
    """SUBMISSION_BASIS: the existing structure always counts; claim_count is 0 by definition."""
    tiv = project["hard_cost_value_cents"] + project["existing_structure_value_cents"]
    duration_days = whole_days(project["planned_start_date"], project["projected_completion_date"])
    return _risk_score(project, tiv, duration_days, 0)


def audit_basis_score(project, policy):
    """AUDIT_BASIS: realised inputs read off the project's single non-terminal policy."""
    tiv = policy["insured_tiv_cents"]
    duration_days = whole_days(project["planned_start_date"], policy["adjusted_completion_date"])
    claim_count = 0
    for claim in by_policy(store.claims, policy["id"]):
        if claim["adjustment_status"] in ("ADJUSTED", "SETTLED", "CLOSED"):
            claim_count += 1
    return _risk_score(project, tiv, duration_days, claim_count)


def slip_factor_for(cumulative_after, original_term_days):
    """Exact-fraction tiering: ratio <= 1/10 -> 1.00, <= 1/4 -> 1.15, else 1.40."""
    if cumulative_after * 10 <= original_term_days:
        return Decimal("1.00")
    if cumulative_after * 4 <= original_term_days:
        return Decimal("1.15")
    return Decimal("1.40")


def extension_limit_exceeded(cumulative_extension_days, requested_extension_days, original_term_days):
    """(cumulative + requested) / original_term_days must not exceed one half."""
    return 2 * (cumulative_extension_days + requested_extension_days) > original_term_days


def price_extension(policy, project, requested_extension_days):
    """Returns (slip_factor, additional_premium_cents) in the pinned five-step order."""
    original_term_days = policy["original_term_days"]
    cumulative_after = policy["cumulative_extension_days"] + requested_extension_days
    slip = slip_factor_for(cumulative_after, original_term_days)
    daily_base_cents = rhu(dec(policy["quoted_premium_cents"]) / dec(original_term_days))
    ap_cents = rhu(dec(daily_base_cents) * dec(requested_extension_days) * slip)
    score = project["audit_risk_score"]
    if score is None:
        score = project["submission_risk_score"]
    if score is not None and score >= CAT_RESLIP_SCORE_THRESHOLD:
        ap_cents = rhu(dec(ap_cents) * CAT_RESLIP_LOAD)
    return slip, ap_cents


def delay_indemnity(policy, project):
    """Returns (indemnified_days, gross_delay_cents) off the adjusted baseline."""
    raw_days = max(0, whole_days(policy["adjusted_completion_date"],
                                project["actual_substantial_completion_date"]))
    indemnified_days = max(0, raw_days - WAITING_PERIOD_DAYS)
    return indemnified_days, indemnified_days * policy["daily_delay_rate_cents"]


def _order_index(part_type):
    return ALLOCATION_ORDER.index(part_type)


def run_waterfall(policy, parts_by_type, items, adjustment_basis, continuing_pm_weeks):
    """Seven pinned steps. `items` is a list of {part_type, gross_loss_cents} dicts.

    Returns (lines, indemnity_cents, claim_uncovered_cents)."""
    # Step one -- line assembly, sorted by the pinned bucket sequence.
    lines = []
    for item in sorted(items, key=lambda i: _order_index(i["part_type"])):
        part = parts_by_type.get(item["part_type"])
        lines.append({
            "part_type": item["part_type"],
            "coverage_part_id": part["id"] if part else None,
            "gross_loss_cents": item["gross_loss_cents"],
            "covered_basis_cents": 0,
            "deductible_applied_cents": 0,
            "allocated_cents": 0,
            "uncovered_cents": 0,
        })

    # Step two -- valuation basis, rounded per line; a delay line never takes the uplift.
    reconstruction = adjustment_basis == "RECONSTRUCTION_COST"
    for line in lines:
        gross = line["gross_loss_cents"]
        if reconstruction and line["part_type"] != "DELAY_IN_COMPLETION":
            line["covered_basis_cents"] = rhu(dec(gross) * RECONSTRUCTION_UPLIFT)
        else:
            line["covered_basis_cents"] = gross

    # Step three -- continuing project management, RECONSTRUCTION_COST only.
    if reconstruction:
        weeks = min(continuing_pm_weeks, PM_MAX_WEEKS)
        basis_sum = sum(line["covered_basis_cents"] for line in lines)
        pm_cents = rhu(dec(basis_sum) * PM_WEEKLY_PCT * dec(weeks))
    else:
        pm_cents = 0
    if pm_cents > 0:
        soft = next((line for line in lines if line["part_type"] == "SOFT_COST"), None)
        if soft is None:
            soft_part = parts_by_type.get("SOFT_COST")
            soft = {
                "part_type": "SOFT_COST",
                "coverage_part_id": soft_part["id"] if soft_part else None,
                "gross_loss_cents": 0,
                "covered_basis_cents": 0,
                "deductible_applied_cents": 0,
                "allocated_cents": 0,
                "uncovered_cents": 0,
            }
            lines.append(soft)
            lines.sort(key=lambda line: _order_index(line["part_type"]))
        soft["covered_basis_cents"] += pm_cents

    # Step four -- the occurrence deductible, applied exactly once.
    target = None
    for line in lines:
        if line["part_type"] == "DELAY_IN_COMPLETION":
            continue
        if target is None or line["covered_basis_cents"] > target["covered_basis_cents"]:
            target = line
    deductible_retained = 0
    if target is not None:
        target["deductible_applied_cents"] = min(
            target["covered_basis_cents"], policy["occurrence_deductible_cents"]
        )
        deductible_retained = target["deductible_applied_cents"]
    nets = {}
    for idx, line in enumerate(lines):
        nets[idx] = line["covered_basis_cents"] - line["deductible_applied_cents"]

    # Step five -- the sublimit cap, against live erosion.
    for idx, line in enumerate(lines):
        part = parts_by_type.get(line["part_type"])
        room = (part["sublimit_cents"] - part["eroded_cents"]) if part else 0
        line["allocated_cents"] = min(nets[idx], room)

    # Step six -- the policy aggregate cap, walked once in the pinned sequence.
    already = 0
    for line in lines:
        remaining = policy["limit_cents"] - policy["eroded_total_cents"] - already
        line["allocated_cents"] = max(0, min(line["allocated_cents"], remaining))
        already += line["allocated_cents"]

    # Step seven -- claim totals; no rounding occurs after step three.
    indemnity_cents = sum(line["allocated_cents"] for line in lines)
    for idx, line in enumerate(lines):
        line["uncovered_cents"] = nets[idx] - line["allocated_cents"]
    claim_uncovered = sum(line["uncovered_cents"] for line in lines) + deductible_retained
    return lines, indemnity_cents, claim_uncovered


def return_premium(policy, cancel_reason, cancel_effective_date):
    total_days = policy["original_term_days"] + policy["cumulative_extension_days"]
    earned_days = whole_days(policy["term_start_date"], cancel_effective_date)
    unearned_days = max(0, total_days - earned_days)
    pro_rata_cents = rhu(
        dec(policy["written_premium_cents"]) * dec(unearned_days) / dec(total_days)
    )
    if cancel_reason == "INSURED_REQUEST":
        return max(0, rhu(dec(pro_rata_cents) * SHORT_RATE_RETENTION_PCT) - SHORT_RATE_FEE_CENTS)
    return pro_rata_cents


def windows_overlap(existing_start, existing_end, new_start, new_end):
    """Half-open overlap: touching endpoints do not overlap."""
    return existing_start < new_end and new_start < existing_end


def facility_peak_exposure(facility_id, stored_value_cents, window_start, window_end):
    peak = stored_value_cents
    for row in store.assignments.values():
        if row["facility_id"] != facility_id or row["status"] != "APPROVED":
            continue
        if windows_overlap(row["window_start"], row["window_end"], window_start, window_end):
            peak += row["stored_value_cents"]
    return peak


def testing_window_conflict(project_id, hot_work, window_start, window_end):
    """The buffer inflates both intervals whenever either notice declares hot work."""
    from datetime import timedelta

    for row in store.notices.values():
        if row["project_id"] != project_id or row["status"] not in ("SCHEDULED", "APPROVED"):
            continue
        buffer = timedelta(hours=HOT_WORK_BUFFER_HOURS) if (hot_work or row["hot_work"]) else timedelta(0)
        if window_start < row["window_end"] + buffer and row["window_start"] < window_end + buffer:
            return True
    return False
