"""Business calculations (SCAFFOLD section 1.3) and shared cascades.

All money is integer cents. Rounding is Decimal ROUND_HALF_UP applied only
at the pinned steps (PRD section 2.7: ties round away from zero).
"""
from decimal import Decimal, ROUND_HALF_UP

import db

PMPM_BASE_CENTS = 100000
MONTHS_PER_YEAR = 12
UPDATE_FACTOR_PROVISIONAL = Decimal("1.030")
UPDATE_FACTOR_FINAL = Decimal("1.021")

RISK_DUAL = Decimal("0.25")
RISK_ESRD = Decimal("0.40")
RISK_DISABLED = Decimal("0.15")
RISK_AGED_75_PLUS = Decimal("0.05")

TRUNCATION_CAP_CENTS = 20000000
HIGH_COST_THRESHOLD_CENTS = 10000000

QUALITY_FULL_THRESHOLD = Decimal("0.7000")
QUALITY_PARTIAL_THRESHOLD = Decimal("0.5000")
BASE_RATE_ONE_SIDED = Decimal("0.40")
BASE_RATE_TWO_SIDED = Decimal("0.60")

MSR_RATE = Decimal("0.02")
MLRR_RATE = Decimal("0.02")
SAVINGS_CAP_RATE = Decimal("0.10")
LOSS_CAP_RATE = Decimal("0.05")
LOSS_SHARE_RATE_TWO_SIDED = Decimal("0.40")
SEQUESTRATION_RATE = Decimal("0.02")

CENT = Decimal("1")
FOUR_DP = Decimal("0.0001")
TWO_DP = Decimal("0.01")


def round_cents(value):
    """Round a Decimal to integer cents, half-up (ties away from zero)."""
    return int(value.quantize(CENT, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Data-sharing elections / privacy
# ---------------------------------------------------------------------------
def latest_election(beneficiary_id, as_of_date):
    """Latest election with effective_date <= as_of_date (tie: latest created_at)."""
    els = [e for e in db.elections.values()
           if e["beneficiary_id"] == beneficiary_id
           and e["effective_date"] <= as_of_date]
    if not els:
        return None
    els.sort(key=lambda e: (e["effective_date"], e["created_at"]))
    return els[-1]


def opted_out_as_of(beneficiary_id, date_str):
    e = latest_election(beneficiary_id, date_str)
    return e is not None and e["direction"] == "OPT_OUT"


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def stale_proposed_settlements(period_id):
    """Every settlement of the period sitting in PROPOSED cascades to STALE."""
    for s in db.settlements.values():
        if s["agreement_period_id"] == period_id and s["status"] == "PROPOSED":
            s["status"] = "STALE"
            db.bump(s)


def is_attributed(beneficiary_id, period_id):
    """Beneficiary holds a record of the period in FINAL or UNDER_APPEAL."""
    return any(
        r["agreement_period_id"] == period_id
        and r["beneficiary_id"] == beneficiary_id
        and r["status"] in ("FINAL", "UNDER_APPEAL")
        for r in db.attribution_records.values()
    )


# ---------------------------------------------------------------------------
# attribution_alignment_run
# ---------------------------------------------------------------------------
def run_attribution(period, run):
    """Sweep PART_B claims in the half-open window and write PROVISIONAL records.

    Returns the number of AttributionRecords created.
    """
    claims = [c for c in db.claims.values()
              if c["agreement_period_id"] == period["id"]
              and c["claim_type"] == "PART_B"
              and c["status"] in ("RECEIVED", "ADJUDICATED")
              and run["window_start_date"] <= c["service_date"] < run["window_end_date"]]
    by_beneficiary = {}
    for c in claims:
        if opted_out_as_of(c["beneficiary_id"], run["window_end_date"]):
            continue
        by_beneficiary.setdefault(c["beneficiary_id"], []).append(c)

    created = 0
    for beneficiary_id, bclaims in by_beneficiary.items():
        per_participant = {}
        for c in bclaims:
            pid = c.get("participant_id")
            if not pid:
                continue  # claims with null participant_id are ignored
            agg = per_participant.setdefault(pid, {"cost": 0, "count": 0})
            agg["cost"] += c["allowed_amount_cents"]
            agg["count"] += 1
        if not per_participant:
            continue
        # Plurality winner: max summed cost; tie -> max claim count;
        # tie -> participant created earliest (created_at ASC).
        winner = min(
            per_participant.keys(),
            key=lambda pid: (
                -per_participant[pid]["cost"],
                -per_participant[pid]["count"],
                db.participants[pid]["created_at"],
            ),
        )
        record = db.stamp_new({
            "id": db.new_id(),
            "agreement_period_id": period["id"],
            "beneficiary_id": beneficiary_id,
            "alignment_run_id": run["id"],
            "participant_id": winner,
            "plurality_cost_cents": per_participant[winner]["cost"],
            "methodology": run["methodology"],
            "status": "PROVISIONAL",
        })
        db.attribution_records[record["id"]] = record
        created += 1
    return created


def supersede_prior_runs(period_id, methodology, new_run_id):
    """Prior same-(period, methodology) COMPLETED runs -> SUPERSEDED; their
    PROVISIONAL records cascade to SUPERSEDED."""
    for r in db.alignment_runs.values():
        if (r["agreement_period_id"] == period_id
                and r["methodology"] == methodology
                and r["id"] != new_run_id
                and r["status"] == "COMPLETED"):
            r["status"] = "SUPERSEDED"
            db.bump(r)
            for rec in db.attribution_records.values():
                if rec["alignment_run_id"] == r["id"] and rec["status"] == "PROVISIONAL":
                    rec["status"] = "SUPERSEDED"
                    db.bump(rec)


# ---------------------------------------------------------------------------
# benchmark_risk_adjustment
# ---------------------------------------------------------------------------
def risk_score(beneficiary, period):
    score = Decimal("1.00")
    if beneficiary["dual_eligible"]:
        score += RISK_DUAL
    if beneficiary["esrd"]:
        score += RISK_ESRD
    if beneficiary["disabled"]:
        score += RISK_DISABLED
    start_year = int(period["performance_start_date"][:4])
    if start_year - beneficiary["birth_year"] >= 75:
        score += RISK_AGED_75_PLUS
    return score


def compute_benchmark(period, variant):
    if variant == "PROVISIONAL":
        statuses = ("PROVISIONAL", "FINAL", "UNDER_APPEAL")
        factor = UPDATE_FACTOR_PROVISIONAL
    else:
        statuses = ("FINAL", "UNDER_APPEAL")
        factor = UPDATE_FACTOR_FINAL
    beneficiary_ids = {
        r["beneficiary_id"]
        for r in db.attribution_records.values()
        if r["agreement_period_id"] == period["id"] and r["status"] in statuses
    }
    # Exact 2-decimal per-beneficiary scores summed with no intermediate rounding.
    risk_score_sum = sum(
        (risk_score(db.beneficiaries[bid], period) for bid in beneficiary_ids),
        Decimal("0"),
    )
    total = round_cents(
        risk_score_sum * PMPM_BASE_CENTS * MONTHS_PER_YEAR * factor)
    return {
        "beneficiary_months": MONTHS_PER_YEAR * len(beneficiary_ids),
        "risk_score_sum": risk_score_sum,
        "update_factor_used": factor,
        "total_benchmark_cents": total,
    }


def active_benchmark(period_id, variant):
    """The ACTIVE benchmark of (period, variant), if any."""
    for b in db.benchmarks.values():
        if (b["agreement_period_id"] == period_id
                and b["variant"] == variant
                and b["status"] == "ACTIVE"):
            return b
    return None


# ---------------------------------------------------------------------------
# expenditure_aggregation_with_truncation
# ---------------------------------------------------------------------------
def expenditure_summary(period_id):
    adjudicated = [c for c in db.claims.values()
                   if c["agreement_period_id"] == period_id
                   and c["status"] == "ADJUDICATED"]
    raw_total = 0
    per_beneficiary = {}
    excluded_count = 0
    for c in adjudicated:
        if (c["review_excluded"]
                or not is_attributed(c["beneficiary_id"], period_id)
                or opted_out_as_of(c["beneficiary_id"], c["service_date"])):
            excluded_count += 1
            continue
        raw_total += c["allowed_amount_cents"]
        per_beneficiary[c["beneficiary_id"]] = (
            per_beneficiary.get(c["beneficiary_id"], 0) + c["allowed_amount_cents"])
    # Truncation applies only when the beneficiary sum exceeds the cap;
    # a sum exactly == cap is NOT truncated (min() handles this).
    truncated_total = sum(min(total, TRUNCATION_CAP_CENTS)
                          for total in per_beneficiary.values())
    return {
        "raw_adjudicated_total_cents": raw_total,
        "truncated_total_cents": truncated_total,
        "truncated_away_cents": raw_total - truncated_total,
        "included_beneficiary_count": len(per_beneficiary),
        "excluded_claim_count": excluded_count,
    }


# ---------------------------------------------------------------------------
# high_cost_flag_threshold
# ---------------------------------------------------------------------------
def ytd_adjudicated(beneficiary_id, period_id):
    return sum(
        c["allowed_amount_cents"]
        for c in db.claims.values()
        if c["agreement_period_id"] == period_id
        and c["beneficiary_id"] == beneficiary_id
        and c["status"] == "ADJUDICATED"
    )


def flagged_review(beneficiary_id, period_id):
    for r in db.high_cost_reviews.values():
        if (r["agreement_period_id"] == period_id
                and r["beneficiary_id"] == beneficiary_id
                and r["status"] == "FLAGGED"):
            return r
    return None


def maybe_flag_high_cost(beneficiary_id, period_id):
    """Boundary pinned: ytd exactly == threshold FLAGS (>=)."""
    ytd = ytd_adjudicated(beneficiary_id, period_id)
    if ytd >= HIGH_COST_THRESHOLD_CENTS and not flagged_review(beneficiary_id, period_id):
        review = db.stamp_new({
            "id": db.new_id(),
            "agreement_period_id": period_id,
            "beneficiary_id": beneficiary_id,
            "flagged_expenditure_cents": ytd,
            "dismissal_reason": None,
            "determined_by_user_id": None,
            "rationale": None,
            "status": "FLAGGED",
        })
        db.high_cost_reviews[review["id"]] = review


def maybe_dismiss_high_cost(beneficiary_id, period_id):
    review = flagged_review(beneficiary_id, period_id)
    if review and ytd_adjudicated(beneficiary_id, period_id) < HIGH_COST_THRESHOLD_CENTS:
        review["status"] = "DISMISSED"
        review["dismissal_reason"] = "THRESHOLD_FALLEN"
        db.bump(review)


# ---------------------------------------------------------------------------
# quality_gate_scoring
# ---------------------------------------------------------------------------
def score_rate_and_points(numerator, denominator, max_points):
    rate = (Decimal(numerator) / Decimal(denominator)).quantize(
        FOUR_DP, rounding=ROUND_HALF_UP)
    # earned_points derives from the (already rounded) performance_rate.
    points = (rate * Decimal(max_points)).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    return rate, points


def quality_aggregate(period_id):
    """Aggregate over VALIDATED scores only; zero VALIDATED -> 0.0000."""
    scores = [s for s in db.quality_scores.values()
              if s["agreement_period_id"] == period_id and s["status"] == "VALIDATED"]
    if not scores:
        return Decimal("0.0000"), Decimal("0.0000")
    total_earned = sum((s["earned_points"] for s in scores), Decimal("0"))
    total_max = sum(s["max_points"] for s in scores)
    quality_score = (total_earned / Decimal(total_max)).quantize(
        FOUR_DP, rounding=ROUND_HALF_UP)
    if quality_score >= QUALITY_FULL_THRESHOLD:
        multiplier = Decimal("1.0000")
    elif quality_score >= QUALITY_PARTIAL_THRESHOLD:
        multiplier = (quality_score / QUALITY_FULL_THRESHOLD).quantize(
            FOUR_DP, rounding=ROUND_HALF_UP)
    else:
        multiplier = Decimal("0.0000")
    return quality_score, multiplier


# ---------------------------------------------------------------------------
# shared_savings_settlement
# ---------------------------------------------------------------------------
def compute_settlement_fields(period, benchmark):
    b_total = benchmark["total_benchmark_cents"]
    expenditure = expenditure_summary(period["id"])["truncated_total_cents"]
    gross = b_total - expenditure
    msr_threshold = round_cents(MSR_RATE * b_total)
    quality_score, multiplier = quality_aggregate(period["id"])
    base_rate = (BASE_RATE_ONE_SIDED if period["track"] == "ONE_SIDED"
                 else BASE_RATE_TWO_SIDED)

    if gross >= 0:
        eligible = gross >= msr_threshold  # == MSR passes (>= pinned)
        if eligible:
            share = round_cents(Decimal(gross) * base_rate * multiplier)
            cap = round_cents(SAVINGS_CAP_RATE * b_total)
            pre_sequestration = min(share, cap)
        else:
            pre_sequestration = 0
        # Levy base is the PRE-sequestration amount, never the post-levy payment.
        levy = round_cents(Decimal(pre_sequestration) * SEQUESTRATION_RATE)
        net = pre_sequestration - levy
        loss = 0
    else:
        mlrr_threshold = round_cents(MLRR_RATE * b_total)
        if period["track"] == "TWO_SIDED" and abs(gross) >= mlrr_threshold:
            raw_loss = Decimal(round_cents(Decimal(gross) * LOSS_SHARE_RATE_TWO_SIDED))
            loss_floor = -round_cents(LOSS_CAP_RATE * b_total)
            loss = int(max(raw_loss, loss_floor))
        else:
            loss = 0
        pre_sequestration = 0
        levy = 0
        net = 0

    return {
        "benchmark_id": benchmark["id"],
        "expenditure_total_cents": expenditure,
        "gross_savings_cents": gross,
        "msr_threshold_cents": msr_threshold,
        "quality_score_snapshot": quality_score,
        "quality_multiplier_snapshot": multiplier,
        "shared_savings_pre_sequestration_cents": pre_sequestration,
        "sequestration_levy_cents": levy,
        "net_shared_savings_cents": net,
        "shared_loss_cents": loss,
        "distributable_pool_cents": max(net, 0),
    }


# ---------------------------------------------------------------------------
# distribution_waterfall_allocation
# ---------------------------------------------------------------------------
def waterfall_allocations(pool, period_id):
    """Floor per line first, then remainder pennies in allocation order
    (share_weight_bp DESC, tie Participant.created_at ASC), at most one pass.
    Returns list of (participant, amount_cents); sum == pool exactly."""
    participants = [p for p in db.participants.values()
                    if p["agreement_period_id"] == period_id
                    and p["share_weight_bp"] > 0]
    total_weight = sum(p["share_weight_bp"] for p in participants)
    if not participants or total_weight <= 0:
        return []
    allocations = []
    for p in participants:
        amount = (pool * p["share_weight_bp"]) // total_weight  # integer floor
        allocations.append([p, amount])
    remainder = pool - sum(amount for _, amount in allocations)
    order = sorted(allocations,
                   key=lambda pa: (-pa[0]["share_weight_bp"], pa[0]["created_at"]))
    idx = 0
    while remainder > 0 and idx < len(order):
        order[idx][1] += 1
        remainder -= 1
        idx += 1
    return [(p, amount) for p, amount in allocations]


# ---------------------------------------------------------------------------
# Settlement helpers
# ---------------------------------------------------------------------------
def recompute_reconciliation_balance(settlement):
    balance = 0
    for a in db.adjustments.values():
        if a["settlement_id"] == settlement["id"] and a["status"] == "POSTED":
            if a["direction"] == "CREDIT":
                balance += a["amount_cents"]
            else:
                balance -= a["amount_cents"]
    settlement["reconciliation_balance_cents"] = balance


def reopen_settlement(settlement):
    """FINAL -> REOPENED: recompute money fields against current inputs and
    void PENDING/APPROVED distribution lines (PAID lines untouched)."""
    period = db.periods[settlement["agreement_period_id"]]
    benchmark = active_benchmark(period["id"], "FINAL")
    if benchmark is None:
        # The referenced benchmark was pinned LOCKED at finalize; recompute
        # against the settlement's own referenced benchmark in that case.
        benchmark = db.benchmarks[settlement["benchmark_id"]]
    settlement.update(compute_settlement_fields(period, benchmark))
    for line in db.distribution_lines.values():
        if (line["settlement_id"] == settlement["id"]
                and line["status"] in ("PENDING", "APPROVED")):
            line["status"] = "VOIDED"
            db.bump(line)
    settlement["status"] = "REOPENED"
    db.bump(settlement)


def maybe_settle_from_lines(settlement):
    """Bubble: no PENDING/APPROVED lines and >=1 PAID -> SETTLED -> period."""
    if settlement["status"] != "FINAL":
        return
    lines = [l for l in db.distribution_lines.values()
             if l["settlement_id"] == settlement["id"]]
    open_lines = [l for l in lines if l["status"] in ("PENDING", "APPROVED")]
    paid_lines = [l for l in lines if l["status"] == "PAID"]
    if not open_lines and paid_lines:
        settlement["status"] = "SETTLED"
        db.bump(settlement)
        bubble_period_settled(settlement["agreement_period_id"])


def bubble_period_settled(period_id):
    period = db.periods.get(period_id)
    if period and period["status"] == "ASSIGNMENT_LOCKED":
        period["status"] = "SETTLED"
        db.bump(period)
