"""Calculation rules (SCAFFOLD §1.3 / PRD §3). All monetary math is exact
integer arithmetic; rounding primitives come from util (round-half-up away
from zero, truncation toward zero, floor) with the pinned per-record /
per-claim rounding-before-summation order.

Constants:
  DISPUTE_WINDOW_DAYS / DISPUTE_RESOLUTION_DAYS / RECONCILIATION_RUNOUT_DAYS
  are referenced by name in the PRD without numeric values; the values here
  are the ones the task's dated workflow corners pin (finalized 2027-04-01 +
  30d window closes 2027-05-01; filed 2027-04-10 + 60d ends 2027-06-09;
  period_end 2027-01-01 + 90d runout lands 2027-04-01).
"""

from __future__ import annotations

from datetime import date, timedelta

import db
from util import floor_div, rhu, trunc_div

# --- named constants (SCAFFOLD §1.3 constants blocks) ---
MID_MONTH_DAY = 15
DEFAULT_SCORE_MILLI = 1000
SLIDING_BASE_BP = 5000
RENEW_MIN_SAVINGS_BP = 100
QUALITY_DROP_TOLERANCE = 5
COMPLETION_MILLI = {1: 150, 2: 320, 3: 480, 4: 620, 5: 740, 6: 850,
                    7: 910, 8: 950, 9: 970, 10: 985, 11: 995}

# --- window constants (see module docstring) ---
DISPUTE_WINDOW_DAYS = 30
DISPUTE_RESOLUTION_DAYS = 60
RECONCILIATION_RUNOUT_DAYS = 90


# ---------------------------------------------------------------------------
# member_months (mid-month rule)
# ---------------------------------------------------------------------------

def member_months_for(member_id: str, period_start: date, period_end: date) -> int:
    """Count calendar months whose 15th lies in [period_start, period_end) and
    is covered by an ACTIVE EligibilitySpan (closed interval) of the member.
    CLOSED spans are ignored entirely."""
    spans = [
        s for s in db.eligibility_spans.values()
        if s["member_id"] == member_id and s["span_status"] == "ACTIVE"
    ]
    if not spans:
        return 0
    parsed = [(db.parse_date(s["start_date"]), db.parse_date(s["end_date"])) for s in spans]

    months = 0
    year, month = period_start.year, period_start.month
    while True:
        fifteenth = date(year, month, MID_MONTH_DAY)
        if fifteenth >= period_end:
            break
        if fifteenth >= period_start:
            eligible = any(start <= fifteenth <= end for start, end in parsed)
            if eligible:
                months += 1
        # advance one calendar month
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return months


# ---------------------------------------------------------------------------
# Attribution population helpers
# ---------------------------------------------------------------------------

def confirmed_population(year: dict) -> list[dict]:
    """CONFIRMED AttributionRecords of the year's LOCKED run only."""
    run_id = year.get("locked_run_id")
    if run_id is None:
        return []
    return [
        r for r in db.attribution_records.values()
        if r["attribution_run_id"] == run_id and r["record_status"] == "CONFIRMED"
    ]


def _final_score_milli(contract: dict, year: dict, member_id: str) -> int:
    """Authoritative FINAL RiskScore for (member, year) under the contract's
    pinned risk_model; falls back to DEFAULT_SCORE_MILLI when none exists."""
    for score in db.risk_scores.values():
        if (
            score["member_id"] == member_id
            and score["performance_year_id"] == year["id"]
            and score["model_used"] == contract["risk_model"]
            and score["score_status"] == "FINAL"
        ):
            return score["score_milli"]
    return DEFAULT_SCORE_MILLI


# ---------------------------------------------------------------------------
# attribution_rollup (+ risk_model_variant selection)
# ---------------------------------------------------------------------------

def compute_attribution_rollup(contract: dict, year: dict) -> dict:
    """Returns {total_member_months, risk_adjustment_factor_milli,
    benchmark_cost_cents} over the CONFIRMED records of the LOCKED run.
    Per-record benchmark terms are rounded half-up BEFORE summation (pinned);
    RAF is the floor of the member-month-weighted mean (floor division)."""
    population = confirmed_population(year)
    total_mm = sum(r["member_months"] for r in population)
    if total_mm == 0:
        raf = None
        benchmark = 0
    else:
        weighted = 0
        benchmark = 0
        for r in population:
            score = _final_score_milli(contract, year, r["member_id"])
            weighted += r["member_months"] * score
            benchmark += rhu(
                contract["benchmark_pmpm_cents"] * r["member_months"] * score, 1000
            )
        raf = floor_div(weighted, total_mm)
    return {
        "total_member_months": total_mm,
        "risk_adjustment_factor_milli": raf,
        "benchmark_cost_cents": benchmark,
    }


# ---------------------------------------------------------------------------
# cost_measurement + withhold_pool
# ---------------------------------------------------------------------------

def _cost_input_claims(year: dict) -> list[dict]:
    """PAID claims of the year, service_date inside the half-open window, whose
    member is attributed (CONFIRMED record in the LOCKED run)."""
    attributed = {r["member_id"] for r in confirmed_population(year)}
    start = db.parse_date(year["period_start"])
    end = db.parse_date(year["period_end"])
    out = []
    for c in db.claims.values():
        if c["performance_year_id"] != year["id"]:
            continue
        if c["claim_status"] != "PAID":
            continue
        if c["member_id"] not in attributed:
            continue
        sd = db.parse_date(c["service_date"])
        if not (start <= sd < end):
            continue
        out.append(c)
    return out


def compute_cost_and_pool(contract: dict, year: dict) -> dict:
    """actual_cost_cents: per-member stop-loss truncation, then summed.
    withhold_pool_cents: per-claim round_half_up BEFORE stop-loss, then summed
    (pinned rounding order; sum-then-round is forbidden)."""
    claims = _cost_input_claims(year)
    per_member: dict[str, int] = {}
    for c in claims:
        per_member[c["member_id"]] = per_member.get(c["member_id"], 0) + c["paid_amount_cents"]
    actual = sum(
        min(total, contract["stop_loss_cents"]) for total in per_member.values()
    )
    pool = sum(rhu(c["paid_amount_cents"] * contract["withhold_rate_bp"], 10000) for c in claims)
    return {"actual_cost_cents": actual, "withhold_pool_cents": pool}


# ---------------------------------------------------------------------------
# achievement_points (quality validate)
# ---------------------------------------------------------------------------

def compute_achievement(contract: dict, measure_code: str, numerator: int, denominator: int) -> dict:
    rate_bp = rhu(numerator * 10000, denominator)
    thresholds = None
    for entry in contract["quality_measures"]:
        if entry["measure_code"] == measure_code:
            thresholds = entry["decile_thresholds_bp"]
            break
    points = sum(1 for t in (thresholds or []) if rate_bp >= t)
    return {"rate_bp": rate_bp, "achievement_points": points}


# ---------------------------------------------------------------------------
# quality_composite (OFFICIAL: LOCKED only; INTERIM: VALIDATED + LOCKED)
# ---------------------------------------------------------------------------

def compute_composite(contract: dict, year: dict, variant: str) -> int:
    """Weighted composite in points 0..100 (PRD §3.10).

    Numerator: sum(achievement_points * weight_bp) over the variant's results.
    Denominator: "the sum of the `weight_bp` values over the same results" —
    the variant's input set only, not the whole catalog. The PRD's zero guard
    ("If the denominator is zero — no locked results, or all weights somehow
    zero") confirms the input-set reading: catalog weights are required
    strictly positive, so only an empty input set can zero the denominator.
    """
    if variant == "official":
        statuses = {"LOCKED"}
    else:
        statuses = {"VALIDATED", "LOCKED"}
    results = [
        r for r in db.quality_results.values()
        if r["performance_year_id"] == year["id"] and r["result_status"] in statuses
    ]
    weight_of = {e["measure_code"]: e["weight_bp"] for e in contract["quality_measures"]}
    num = sum(r["achievement_points"] * weight_of.get(r["measure_code"], 0) for r in results)
    den = sum(weight_of.get(r["measure_code"], 0) for r in results)
    if den == 0:
        return 0
    return rhu(num * 100, 9 * den)


# ---------------------------------------------------------------------------
# quality_gate_multiplier
# ---------------------------------------------------------------------------

def gate_multiplier(contract: dict, composite_points: int) -> int:
    floor_pts = contract["quality_gate_floor_points"]
    excellence = contract["quality_gate_excellence_points"]
    if composite_points >= excellence:
        return 10000
    if composite_points >= floor_pts:
        return SLIDING_BASE_BP + rhu(
            (composite_points - floor_pts) * 5000, excellence - floor_pts
        )
    return 0


# ---------------------------------------------------------------------------
# shared_savings_and_loss (MSR/MLR gates, caps; zero corridor)
# ---------------------------------------------------------------------------

def compute_shared(contract: dict, benchmark_cents: int, actual_cents: int) -> dict:
    gross = benchmark_cents - actual_cents
    if benchmark_cents == 0:
        # Guard reachable only via interim estimates before attribution lock.
        return {
            "gross_savings_cents": gross,
            "savings_rate_bp": 0,
            "shared_savings_cents": 0,
            "shared_losses_cents": 0,
        }
    rate_bp = trunc_div(gross * 10000, benchmark_cents)
    if gross >= 0:
        if rate_bp >= contract["min_savings_rate_bp"]:
            uncapped = rhu(gross * contract["shared_savings_rate_bp"], 10000)
            cap = rhu(benchmark_cents * contract["savings_cap_bp"], 10000)
            shared_savings = min(uncapped, cap)
        else:
            shared_savings = 0
        shared_losses = 0
    else:
        shared_savings = 0
        if (
            contract["risk_track"] == "TWO_SIDED"
            and rate_bp <= -contract["min_loss_rate_bp"]
        ):
            uncapped = rhu(-gross * contract["shared_loss_rate_bp"], 10000)
            cap = rhu(benchmark_cents * contract["loss_cap_bp"], 10000)
            shared_losses = min(uncapped, cap)
        else:
            shared_losses = 0
    return {
        "gross_savings_cents": gross,
        "savings_rate_bp": rate_bp,
        "shared_savings_cents": shared_savings,
        "shared_losses_cents": shared_losses,
    }


# ---------------------------------------------------------------------------
# settlement_net — the pinned eight-step chain
# ---------------------------------------------------------------------------

def compute_settlement_chain(contract: dict, year: dict, settlement: dict | None) -> dict:
    """Evaluate the full settlement chain from the year's current stored
    rollups and LOCKED quality results. `settlement` (when given) supplies the
    existing remittances for the undistributed-balance step."""
    benchmark = year["benchmark_cost_cents"]
    actual = year["actual_cost_cents"]
    pool = year["withhold_pool_cents"]

    shared = compute_shared(contract, benchmark, actual)
    composite = compute_composite(contract, year, "official")
    mult = gate_multiplier(contract, composite)

    adjusted = rhu(shared["shared_savings_cents"] * mult, 10000)
    released = rhu(pool * mult, 10000)
    forfeited = pool - released
    net = adjusted + released - shared["shared_losses_cents"]

    committed = 0
    if settlement is not None:
        committed = sum(
            r["amount_cents"]
            for r in db.distribution_remittances.values()
            if r["settlement_id"] == settlement["id"]
            and r["remittance_status"] in ("SCHEDULED", "APPROVED", "PAID")
        )
    undistributed = max(0, net) - committed

    return {
        "gross_savings_cents": shared["gross_savings_cents"],
        "savings_rate_bp": shared["savings_rate_bp"],
        "shared_savings_cents": shared["shared_savings_cents"],
        "shared_losses_cents": shared["shared_losses_cents"],
        "quality_composite_points": composite,
        "quality_multiplier_bp": mult,
        "quality_adjusted_savings_cents": adjusted,
        "withhold_released_cents": released,
        "withhold_forfeited_cents": forfeited,
        "net_payable_cents": net,
        "undistributed_balance_cents": undistributed,
    }


def recompute_undistributed(settlement: dict) -> int:
    committed = sum(
        r["amount_cents"]
        for r in db.distribution_remittances.values()
        if r["settlement_id"] == settlement["id"]
        and r["remittance_status"] in ("SCHEDULED", "APPROVED", "PAID")
    )
    return max(0, settlement["net_payable_cents"]) - committed


# ---------------------------------------------------------------------------
# interim_estimate (ANNUALIZATION vs COMPLETION_FACTOR; INTERIM composite)
# ---------------------------------------------------------------------------

def compute_interim_estimates(contract: dict, year: dict, months_elapsed: int, clock_dt: date) -> dict:
    """YTD paid total over PAID claims with paid_on <= logical clock date and
    member attributed per the current LOCKED run. Both estimate variants are
    computed; the contract's estimate_method selects the authoritative one."""
    attributed = {r["member_id"] for r in confirmed_population(year)}
    ytd_claims = []
    for c in db.claims.values():
        if c["performance_year_id"] != year["id"] or c["claim_status"] != "PAID":
            continue
        if c["member_id"] not in attributed:
            continue
        paid_on = c.get("paid_on")
        if paid_on is None:
            continue
        if db.parse_date(paid_on) <= clock_dt:
            ytd_claims.append(c)

    ytd = sum(c["paid_amount_cents"] for c in ytd_claims)
    ytd_pool = sum(rhu(c["paid_amount_cents"] * contract["withhold_rate_bp"], 10000) for c in ytd_claims)

    est_ann = rhu(ytd * 12, months_elapsed)
    est_comp = rhu(ytd * 1000, COMPLETION_MILLI[months_elapsed])
    est_actual = est_ann if contract["estimate_method"] == "ANNUALIZATION" else est_comp

    shared = compute_shared(contract, year["benchmark_cost_cents"], est_actual)
    composite = compute_composite(contract, year, "interim")
    mult = gate_multiplier(contract, composite)

    est_net = (
        rhu(shared["shared_savings_cents"] * mult, 10000)
        + rhu(ytd_pool * mult, 10000)
        - shared["shared_losses_cents"]
    )
    reserve = rhu(max(0, est_net) * months_elapsed, 12)

    return {
        "est_actual_annualization_cents": est_ann,
        "est_actual_completion_cents": est_comp,
        "est_net_payable_cents": est_net,
        "reserve_accrual_cents": reserve,
    }


# ---------------------------------------------------------------------------
# distribution_allocation — largest-remainder waterfall
# ---------------------------------------------------------------------------

def compute_distribution(contract: dict, year: dict, settlement: dict) -> list[dict]:
    """Returns [{practice, practice_member_months, amount_cents}] for practices
    with allocated amount > 0. Per-practice floor, then remainder cents in
    descending fractional part; ties broken by Practice.created_at ascending
    (never by id). Conservation: sum(amounts) == pool exactly."""
    pool = max(0, settlement["net_payable_cents"])
    population = confirmed_population(year)
    weights: dict[str, int] = {}
    for r in population:
        weights[r["practice_id"]] = weights.get(r["practice_id"], 0) + r["member_months"]
    total_w = sum(weights.values())
    if pool == 0 or total_w == 0:
        return []

    rows = []
    for practice_id, weight in weights.items():
        practice = db.practices.get(practice_id)
        created_at = practice["created_at"] if practice else ""
        exact_num = pool * weight  # exact = exact_num / total_w
        amount = exact_num // total_w  # floor (non-negative)
        remainder_part = exact_num % total_w  # fractional part numerator
        rows.append(
            {
                "practice_id": practice_id,
                "created_at": created_at,
                "weight": weight,
                "amount": amount,
                "frac": remainder_part,
            }
        )

    distributed = sum(r["amount"] for r in rows)
    remainder = pool - distributed  # 0 <= remainder < len(rows)
    # Largest fractional part first; ties by practice created_at ascending.
    order = sorted(rows, key=lambda r: (-r["frac"], r["created_at"]))
    for r in order[:remainder]:
        r["amount"] += 1

    return [
        {
            "practice_id": r["practice_id"],
            "practice_member_months": r["weight"],
            "amount_cents": r["amount"],
        }
        for r in sorted(rows, key=lambda r: r["created_at"])
        if r["amount"] > 0
    ]


# ---------------------------------------------------------------------------
# renewal_recommendation
# ---------------------------------------------------------------------------

def compute_renewal_metrics(contract: dict) -> dict:
    """Aggregate over the contract's CLOSED years (>= 1 enforced at create).
    Realized rate truncated toward zero; comparisons >= pinned."""
    closed = [
        y for y in db.performance_years.values()
        if y["contract_id"] == contract["id"] and y["year_status"] == "CLOSED"
    ]
    sum_bm = sum(y["benchmark_cost_cents"] for y in closed)
    sum_act = sum(y["actual_cost_cents"] for y in closed)
    if sum_bm == 0:
        realized = 0
    else:
        realized = trunc_div((sum_bm - sum_act) * 10000, sum_bm)

    def composite_of(year: dict) -> int:
        settlement = next(
            (
                s for s in db.settlements.values()
                if s["performance_year_id"] == year["id"] and s["settlement_status"] != "VOID"
            ),
            None,
        )
        return settlement["quality_composite_points"] if settlement else 0

    latest = max(closed, key=lambda y: y["year_label"])
    earliest = min(closed, key=lambda y: y["year_label"])
    quality_trend = composite_of(latest) - composite_of(earliest)
    raf_latest = latest["risk_adjustment_factor_milli"] or 0
    raf_earliest = earliest["risk_adjustment_factor_milli"] or 0
    risk_growth = raf_latest - raf_earliest

    if realized >= RENEW_MIN_SAVINGS_BP and quality_trend >= -QUALITY_DROP_TOLERANCE:
        recommendation = "RENEW_AS_IS"
    elif realized >= 0:
        recommendation = "RENEW_RENEGOTIATE"
    else:
        recommendation = "DO_NOT_RENEW"

    return {
        "realized_savings_rate_bp": realized,
        "quality_trend_points": quality_trend,
        "risk_growth_milli": risk_growth,
        "recommendation": recommendation,
    }
