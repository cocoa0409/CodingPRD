"""Calculation rules: split allocation, rollup, attainment, curve, settlement, effectiveness.

Implements scaffold §1.3 calculation rules exactly.
"""
from db import db
from util import round_half_up_int, new_id, now_ts


# ---------------------------------------------------------------------------
# split_credit_allocation
# ---------------------------------------------------------------------------

def split_credit_allocation(amount_cents, splits):
    """Allocate credit per split with per-split round-half-up, remainder to largest.

    Returns list of credit amounts in the same order as splits.
    Invariant: sum(returned) == amount_cents exactly.
    """
    credits = []
    for split in splits:
        raw = amount_cents * split["split_bps"]
        credit = round_half_up_int(raw, 10000)
        credits.append(credit)

    remainder = amount_cents - sum(credits)
    if remainder != 0:
        # Target: largest split_bps; tie -> lowest array index
        target_idx = 0
        for i, split in enumerate(splits):
            if split["split_bps"] > splits[target_idx]["split_bps"]:
                target_idx = i
        credits[target_idx] += remainder

    return credits


# ---------------------------------------------------------------------------
# rollup_credit_amount
# ---------------------------------------------------------------------------

def compute_rollup_amount(credit_amount_cents, rollup_rate_bps):
    """round_half_up(credit_amount_cents * rollup_rate_bps / 10000)."""
    return round_half_up_int(credit_amount_cents * rollup_rate_bps, 10000)


# ---------------------------------------------------------------------------
# attainment_calculation
# ---------------------------------------------------------------------------

def mode_filtered_earned(assignment, plan):
    """Current-period earned filtered by plan's attainment_mode.

    DIRECT_ONLY: only DIRECT credits count (subtract rollup portion from raw).
    INCLUDE_ROLLUP: both DIRECT and ROLLUP count (= raw counter).
    """
    raw = assignment["current_period_earned_cents"]
    if plan["attainment_mode"] == "DIRECT_ONLY":
        return raw - assignment.get("_rollup_earned_cents", 0)
    return raw


def compute_attainment_bps(earned_cents, quota_cents):
    """floor(earned * 10000 / quota_cents); 0 when earned <= 0."""
    if earned_cents <= 0:
        return 0
    return (earned_cents * 10000) // quota_cents


# ---------------------------------------------------------------------------
# quota_to_payout_curve
# ---------------------------------------------------------------------------

def quota_to_payout_curve(earned_cents, plan, quota_cents, ignore_cap=False):
    """Marginal tiered curve over attainment-defined credit bands.

    Returns (gross_payout_cents, payout_cap_applied).
    Per-band round-half-up, then sum; cap applied last.
    """
    tiers = plan["curve_tiers"]
    gross_uncapped = 0

    for i, tier in enumerate(tiers):
        floor_i = tier["attainment_floor_bps"]
        rate_i = tier["rate_bps"]
        lo_cents = (floor_i * quota_cents) // 10000

        if i + 1 < len(tiers):
            floor_next = tiers[i + 1]["attainment_floor_bps"]
            hi_cents = (floor_next * quota_cents) // 10000
            band_width = hi_cents - lo_cents
            band_credit = min(max(earned_cents - lo_cents, 0), band_width)
        else:
            # Top tier: open-ended
            band_credit = max(earned_cents - lo_cents, 0)

        band_payout = round_half_up_int(band_credit * rate_i, 10000)
        gross_uncapped += band_payout

    cap = plan.get("payout_cap_cents")
    if not ignore_cap and cap is not None:
        payout_cap_applied = gross_uncapped > cap
        gross = min(gross_uncapped, cap)
    else:
        payout_cap_applied = False
        gross = gross_uncapped

    return gross, payout_cap_applied


# ---------------------------------------------------------------------------
# payout_estimate (provisional)
# ---------------------------------------------------------------------------

def compute_provisional_payout(assignment, plan):
    """Provisional estimate: curve applied to mode-filtered (earned + PENDING), no cap."""
    earned = mode_filtered_earned(assignment, plan)
    pending = sum(
        c["credit_amount_cents"]
        for c in db["credit_entries"].values()
        if c["assignment_id"] == assignment["id"]
        and c["status"] == "PENDING"
        and (plan["attainment_mode"] != "DIRECT_ONLY" or c["credit_type"] == "DIRECT")
    )
    total = earned + pending
    if total <= 0:
        return 0
    gross, _ = quota_to_payout_curve(total, plan, assignment["quota_cents"], ignore_cap=True)
    return gross


def recompute_assignment_indicators(assignment):
    """Recompute current_attainment_bps and provisional_period_payout_cents."""
    plan = db["plans"][assignment["plan_id"]]
    earned = mode_filtered_earned(assignment, plan)
    assignment["current_attainment_bps"] = compute_attainment_bps(
        earned, assignment["quota_cents"]
    )
    assignment["provisional_period_payout_cents"] = compute_provisional_payout(
        assignment, plan
    )


# ---------------------------------------------------------------------------
# period_settlement
# ---------------------------------------------------------------------------

def period_settlement(assignment, program, closing_period):
    """Compute all money fields for a DRAFT PayoutStatement at period close.

    Pinned evaluation order per scaffold §1.3 period_settlement.
    Mutates assignment draw ledger and lifetime counters.
    Returns the created statement dict.
    """
    plan = db["plans"][assignment["plan_id"]]

    # e1: mode-filtered earned
    e1 = mode_filtered_earned(assignment, plan)

    # e2: e1 + APPROVED adjustments for closing period
    adjustments_sum = sum(
        a["amount_cents"]
        for a in db["adjustments"].values()
        if a["assignment_id"] == assignment["id"]
        and a["status"] == "APPROVED"
        and a["period_index"] == closing_period
    )
    e2 = e1 + adjustments_sum

    # attainment and gross
    if e2 <= 0:
        attainment_bps = 0
        gross = 0
        payout_cap_applied = False
        deficit = -e2  # 0 when e2 == 0
    else:
        attainment_bps = compute_attainment_bps(e2, assignment["quota_cents"])
        gross, payout_cap_applied = quota_to_payout_curve(
            e2, plan, assignment["quota_cents"]
        )
        deficit = 0

    # draws
    draw_paid = assignment["draw_amount_cents_per_period"]
    if assignment["draw_recoverable"]:
        assignment["draw_outstanding_cents"] = (
            assignment.get("draw_outstanding_cents", 0) + draw_paid
        )
    draw_recovered = min(gross, assignment.get("draw_outstanding_cents", 0))
    assignment["draw_outstanding_cents"] = (
        assignment.get("draw_outstanding_cents", 0) - draw_recovered
    )

    # guarantee
    net_before_guarantee = gross - draw_recovered
    guarantee_trueup = max(
        0, assignment["guarantee_amount_cents_per_period"] - net_before_guarantee
    )
    net_payable = net_before_guarantee + guarantee_trueup

    # deficit handling
    if deficit > 0:
        if assignment["draw_recoverable"]:
            assignment["draw_outstanding_cents"] = (
                assignment.get("draw_outstanding_cents", 0) + deficit
            )
        else:
            assignment["draw_forgiven_cents"] = (
                assignment.get("draw_forgiven_cents", 0) + deficit
            )

    # ledger sync
    assignment["lifetime_earned_cents"] = (
        assignment.get("lifetime_earned_cents", 0) + e2
    )
    assignment["lifetime_paid_cents"] = (
        assignment.get("lifetime_paid_cents", 0) + net_payable
    )

    # create statement
    ts = now_ts()
    statement = {
        "id": new_id(),
        "assignment_id": assignment["id"],
        "period_index": closing_period,
        "earned_credits_cents": e1,
        "adjustments_cents": adjustments_sum,
        "earned_total_cents": e2,
        "attainment_bps": attainment_bps,
        "gross_payout_cents": gross,
        "payout_cap_applied": payout_cap_applied,
        "draw_paid_cents": draw_paid,
        "draw_recovered_cents": draw_recovered,
        "guarantee_trueup_cents": guarantee_trueup,
        "deficit_cents": deficit,
        "net_payable_cents": net_payable,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db["statements"][statement["id"]] = statement
    return statement


# ---------------------------------------------------------------------------
# plan_effectiveness
# ---------------------------------------------------------------------------

def plan_effectiveness(plan_id):
    """Compute plan effectiveness analytics (computed on read)."""
    plan_assignments = [
        a for a in db["assignments"].values() if a["plan_id"] == plan_id
    ]
    assignments_count = len(plan_assignments)

    assignment_ids = {a["id"] for a in plan_assignments}
    statements = [
        s for s in db["statements"].values() if s["assignment_id"] in assignment_ids
    ]
    statements_count = len(statements)

    if statements_count == 0:
        avg_attainment_bps = 0
    else:
        avg_attainment_bps = (
            sum(s["attainment_bps"] for s in statements) // statements_count
        )

    total_earned_cents = sum(s["earned_total_cents"] for s in statements)
    total_payout_cents = sum(s["net_payable_cents"] for s in statements)

    distribution = {
        "LT_8000": sum(1 for s in statements if s["attainment_bps"] < 8000),
        "B8000_10000": sum(
            1 for s in statements if 8000 <= s["attainment_bps"] < 10000
        ),
        "GTE_10000": sum(1 for s in statements if s["attainment_bps"] >= 10000),
    }

    return {
        "plan_id": plan_id,
        "assignments_count": assignments_count,
        "statements_count": statements_count,
        "avg_attainment_bps": avg_attainment_bps,
        "total_earned_cents": total_earned_cents,
        "total_payout_cents": total_payout_cents,
        "distribution": distribution,
    }
