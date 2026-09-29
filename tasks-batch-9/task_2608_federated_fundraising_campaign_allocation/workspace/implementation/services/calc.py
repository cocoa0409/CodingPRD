"""Calculation rules (SCAFFOLD 1.3 / PRD 3.3, 3.5, 3.6, 3.7, 3.8, 3.9).

Every rounding order below is pinned by the PRD and must not be "simplified".
"""

from decimal import Decimal

from store import D, q0, q2, q4, ZERO

# --- pledge_designation_fee_allocation ------------------------------------- #
DESIGNATION_FEE_RATE = Decimal("0.0725")
MIN_LINE_FEE = Decimal("1.50")
MIN_DESIGNATION_AMOUNT = Decimal("25.00")

# --- campaign_pledge_loss_estimate ----------------------------------------- #
SHRINKAGE_ESCROW_THRESHOLD_BPS = 1500

# --- agency_financial_standing_score --------------------------------------- #
PROGRAM_RATIO_FLOOR = Decimal("0.65")
RESERVE_POINTS_PER_MONTH = Decimal("5")
GOVERNANCE_POINTS_EACH = Decimal("2.5")
ADMIN_RATIO_FREE_CEILING = Decimal("0.25")
RESTATEMENT_TOLERANCE = Decimal("0.02")
RESTATEMENT_PENALTY = Decimal("7.5")
STANDARDS_PASS_SCORE = Decimal("70.00")
PROBATION_FLOOR_SCORE = Decimal("55.00")
AUDIT_POINTS = {
    "UNQUALIFIED": Decimal("10"),
    "QUALIFIED": Decimal("5"),
    "ADVERSE": Decimal("0"),
    "NONE": Decimal("0"),
}

# --- request_panel_composite_score ----------------------------------------- #
W_PRIORITY = Decimal("0.40")
W_OUTCOME = Decimal("0.35")
W_CAPACITY = Decimal("0.25")
PANEL_QUORUM = 3
TRIM_MIN_COUNT = 5
FOCUS_MULTIPLIER = Decimal("1.15")
PANEL_APPROVAL_THRESHOLD = Decimal("72.00")

# --- community_impact_fund_allocation -------------------------------------- #
OFFSET_TIER_1_FLOOR = Decimal("50000.00")
OFFSET_TIER_2_FLOOR = Decimal("150000.00")
SUPPLEMENT_TIER_1_CEILING = Decimal("50000.00")
SUPPLEMENT_TIER_2_CEILING = Decimal("120000.00")
OUTCOME_REPORT_DUE_DAYS = 180
REQUEST_CAP_MULTIPLE = Decimal("2.0")
CYCLE_RESTRICT_RATIO = Decimal("0.34")

# --- outcome_report_expenditure_variance ----------------------------------- #
MAX_REVISION_ROUNDS = 2
SITE_VISIT_BUFFER_DAYS = 3
SITE_VISIT_MAX_LEAD_DAYS = 90


# ========================================================================== #
# pledge_designation_fee_allocation
# ========================================================================== #


def allocate_designation_fees(pledge, active_lines):
    """Per-line fee rounded to cents FIRST, then summed. Never re-round totals."""
    ordered = sorted(active_lines, key=lambda l: l["designation_sequence"])
    for line in ordered:
        raw_fee = line["designated_amount"] * DESIGNATION_FEE_RATE
        fee = q2(raw_fee)
        if fee < MIN_LINE_FEE:
            fee = MIN_LINE_FEE
        line["processing_fee"] = fee
        line["net_designated_amount"] = line["designated_amount"] - fee

    designated_total = ZERO
    fee_total = ZERO
    for line in ordered:
        designated_total = designated_total + line["designated_amount"]
        fee_total = fee_total + line["processing_fee"]

    pledge["designated_amount_total"] = q2(designated_total)
    pledge["undesignated_amount"] = q2(pledge["gross_amount"] - designated_total)
    pledge["designation_fee_total"] = q2(fee_total)
    pledge["net_designated_total"] = q2(designated_total - fee_total)


def scale_collected_designated(pledge, active_lines):
    """collected_designated_amount = net * (collected / gross), rounded to cents."""
    gross = pledge["gross_amount"]
    collected = pledge["collected_amount"]
    for line in sorted(active_lines, key=lambda l: l["designation_sequence"]):
        if gross is None or gross == 0:
            line["collected_designated_amount"] = ZERO
            continue
        ratio = D(collected) / D(gross)
        line["collected_designated_amount"] = q2(line["net_designated_amount"] * ratio)


# ========================================================================== #
# campaign_pledge_loss_estimate
# ========================================================================== #


def provisional_loss(projected_payroll_total, historical_shrinkage_rate_bps):
    return q2(D(projected_payroll_total) * D(historical_shrinkage_rate_bps) / D(10000))


def final_loss(candidate_pledges, loss_reserve_amount):
    """All-or-nothing reserve absorption in the pinned chronological order.

    candidate_pledges must already be ordered created_at ASC, gross_amount DESC,
    donor_reference ASC.
    """
    remaining_reserve = D(loss_reserve_amount)
    absorbed = ZERO
    total_uncollected = ZERO
    for pledge in candidate_pledges:
        uncollected = D(pledge["uncollected_amount"])
        total_uncollected = total_uncollected + uncollected
        if uncollected <= remaining_reserve:
            remaining_reserve = remaining_reserve - uncollected
            absorbed = absorbed + uncollected
    return q2(absorbed), q2(total_uncollected - absorbed)


def realized_shrinkage_bps(final_actual_loss, confirmed_gross_total):
    if confirmed_gross_total is None or D(confirmed_gross_total) == 0:
        return 0
    return q0(D(final_actual_loss) / D(confirmed_gross_total) * D(10000))


# ========================================================================== #
# agency_financial_standing_score
# ========================================================================== #


def standing_score(review, variant):
    """Returns (score, restatement_penalty_applied)."""
    if variant == "PRELIMINARY":
        prog = review["program_expense_ratio"]
        admin = review["admin_expense_ratio"]
        res = review["months_operating_reserve"]
        audit_points = Decimal("0")
    else:
        prog = review["audited_program_expense_ratio"]
        admin = review["audited_admin_expense_ratio"]
        res = review["audited_months_operating_reserve"]
        audit_points = AUDIT_POINTS[review["audit_opinion"]]

    above_floor = D(prog) - PROGRAM_RATIO_FLOOR
    if above_floor < 0:
        above_floor = Decimal("0")
    program_points = q2(above_floor * Decimal("400"))
    if program_points > Decimal("40"):
        program_points = Decimal("40")

    reserve_points = q2(D(res) * RESERVE_POINTS_PER_MONTH)
    if reserve_points > Decimal("25"):
        reserve_points = Decimal("25")

    governance_points = q2(
        D(review["governance_checklist_passed_count"]) * GOVERNANCE_POINTS_EACH
    )

    raw = program_points + reserve_points + governance_points + audit_points

    if D(admin) <= ADMIN_RATIO_FREE_CEILING:
        admin_penalty = ZERO
    else:
        admin_penalty = q2((D(admin) - ADMIN_RATIO_FREE_CEILING) * Decimal("200"))

    restatement_applied = False
    restatement = ZERO
    if variant == "CERTIFIED":
        if D(review["audited_program_expense_ratio"]) < (
            D(review["program_expense_ratio"]) - RESTATEMENT_TOLERANCE
        ):
            restatement = RESTATEMENT_PENALTY
            restatement_applied = True

    # Pinned order: subtract both penalties, clamp to [0, 100], round last.
    value = raw - admin_penalty - restatement
    if value > Decimal("100"):
        value = Decimal("100")
    if value < Decimal("0"):
        value = Decimal("0")
    return q2(value), restatement_applied


# ========================================================================== #
# request_panel_composite_score
# ========================================================================== #


def weighted_score(priority_alignment, outcome_evidence, capacity):
    return q2(
        W_PRIORITY * D(priority_alignment)
        + W_OUTCOME * D(outcome_evidence)
        + W_CAPACITY * D(capacity)
    )


def composite_score(pool_scores, focus_match):
    """Plain / trimmed mean already resolved by the caller; applies multiplier."""
    total = ZERO
    for row in pool_scores:
        total = total + D(row["weighted_score"])
    base = q2(total / D(len(pool_scores)))
    multiplier = FOCUS_MULTIPLIER if focus_match else Decimal("1.00")
    value = base * multiplier
    if value > Decimal("100"):
        value = Decimal("100")
    return q2(value)


def select_trimmed(eligible_rows):
    """Returns (pool, dropped) for a pool of TRIM_MIN_COUNT or more scores.

    Exactly one row holding the highest weighted_score and exactly one holding
    the lowest are dropped; ties at either extreme break by earliest created_at
    (never by id).
    """
    if len(eligible_rows) < TRIM_MIN_COUNT:
        return list(eligible_rows), []
    ordered = sorted(eligible_rows, key=lambda r: (r["created_at"], r["_seq"]))
    highest = max(D(r["weighted_score"]) for r in ordered)
    lowest = min(D(r["weighted_score"]) for r in ordered)
    drop_high = None
    for row in ordered:
        if D(row["weighted_score"]) == highest:
            drop_high = row
            break
    drop_low = None
    for row in ordered:
        if row is drop_high:
            continue
        if D(row["weighted_score"]) == lowest:
            drop_low = row
            break
    dropped = [r for r in (drop_high, drop_low) if r is not None]
    pool = [r for r in ordered if r not in dropped]
    return pool, dropped


# ========================================================================== #
# community_impact_fund_allocation
# ========================================================================== #


def offset_rate(base_award):
    if D(base_award) < OFFSET_TIER_1_FLOOR:
        return Decimal("0.00")
    if D(base_award) < OFFSET_TIER_2_FLOOR:
        return Decimal("0.15")
    return Decimal("0.35")


def supplement_rate(net_after_offset):
    if D(net_after_offset) < SUPPLEMENT_TIER_1_CEILING:
        return Decimal("0.06")
    if D(net_after_offset) < SUPPLEMENT_TIER_2_CEILING:
        return Decimal("0.03")
    return Decimal("0.01")


def award_waterfall(requested_amount, max_award_per_agency, composite, available_pool,
                    designated_passthrough_ytd):
    """Seven-step waterfall. Returns a dict of the four award components plus the
    step-6 unclamped total, which is what the pool-sufficiency gate tests."""
    eligible_request_amount = min(D(requested_amount), D(max_award_per_agency))
    score_scaled = q2(eligible_request_amount * (D(composite) / D(100)))
    base_award = min(score_scaled, D(available_pool))
    rate = offset_rate(base_award)
    designation_offset = q2(base_award * rate)
    cap = D(designated_passthrough_ytd)
    if designation_offset > cap:
        designation_offset = q2(cap)
    net_after_offset = q2(base_award - designation_offset)
    strategic = q2(net_after_offset * supplement_rate(net_after_offset))
    unclamped = q2(net_after_offset + strategic)
    total_award = min(unclamped, q2(D(available_pool)))
    return {
        "base_award": q2(base_award),
        "designation_offset": designation_offset,
        "strategic_supplement": strategic,
        "total_award_unclamped": unclamped,
        "total_award": q2(total_award),
    }


# ========================================================================== #
# outcome_report_expenditure_variance
# ========================================================================== #


def expenditure_variance(funds_expended, total_award):
    if total_award is None or D(total_award) == 0:
        return ZERO
    return q2((D(funds_expended) - D(total_award)) / D(total_award) * D(100))
