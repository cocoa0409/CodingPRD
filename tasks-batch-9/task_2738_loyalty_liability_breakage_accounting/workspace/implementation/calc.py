"""Every calculation the PRD names, in the exact order and rounding it names.

All arithmetic is exact integer or Decimal arithmetic; `rhu` is the single
round-half-up primitive and it is applied once at each point the specification
names a division.
"""
import db
from errors import ApiError
from util import add_days, clamp, clock, rhu, whole_days_between

OUTSTANDING_LIFECYCLE = ("OUTSTANDING", "PARTIALLY_REDEEMED")
CLOSED_PERIOD_STATES = ("SOFT_CLOSED", "HARD_CLOSED")
RATE_FLOOR_BP = 200
RATE_CEIL_BP = 9800
DORMANCY_DAYS_FOR_MEMBER_FLAG = 730


# --- PointLot derived-on-read figures (PRD §3.3) -----------------------------

def lot_remaining_gross_ssp_cents(lot):
    return rhu(lot["points_remaining"] * lot["ssp_millicents_per_point_at_issue"], 1000)


def lot_remaining_deferred_cents(lot):
    gross = lot_remaining_gross_ssp_cents(lot)
    return gross - rhu(gross * lot["breakage_rate_bp_at_issue"], 10000)


def is_outstanding(lot):
    return lot["lifecycle_state"] in OUTSTANDING_LIFECYCLE


# --- Member derived-on-read figures (PRD §3.1) -------------------------------

def member_outstanding_lots(member_id):
    return db.rows(
        db.store.point_lots,
        lambda l: l["member_id"] == member_id and is_outstanding(l),
    )


def member_point_balance(member_id):
    return sum(l["points_remaining"] for l in member_outstanding_lots(member_id))


def member_outstanding_gross_ssp_cents(member_id):
    return sum(
        lot_remaining_gross_ssp_cents(l) for l in member_outstanding_lots(member_id)
    )


def member_dormancy_days(member):
    return whole_days_between(clock.now(), member["last_activity_at"])


# --- LoyaltyProgram derived-on-read figures (PRD §3.1) -----------------------

def program_outstanding_lots(program_id):
    return [l for l in db.program_lots(program_id) if is_outstanding(l)]


def program_total_deferred_revenue_cents(program_id):
    return sum(
        lot_remaining_deferred_cents(l) for l in program_outstanding_lots(program_id)
    )


def program_recognized_breakage_ytd_cents(program_id):
    return sum(
        p["breakage_recognized_cents"]
        for p in db.program_periods(program_id)
        if p["state"] in CLOSED_PERIOD_STATES
    )


def program_outstanding_gross_ssp_cents(program_id):
    """Per-lot rounding, then summation (PRD §2.5, §3.7 step 7)."""
    return sum(
        lot_remaining_gross_ssp_cents(l) for l in program_outstanding_lots(program_id)
    )


# --- Point issuance measurement (PRD §3.3) ----------------------------------

def issuance_measurement(base_points, promo_multiplier_bp, tier_multiplier_bp,
                         ssp_millicents, breakage_rate_bp):
    tier_points = rhu(base_points * tier_multiplier_bp, 10000)
    points_issued = rhu(tier_points * promo_multiplier_bp, 10000)
    gross_ssp_cents = rhu(points_issued * ssp_millicents, 1000)
    breakage_reserve_cents = rhu(gross_ssp_cents * breakage_rate_bp, 10000)
    return {
        "tier_points": tier_points,
        "points_issued": points_issued,
        "points_remaining": points_issued,
        "gross_ssp_cents": gross_ssp_cents,
        "breakage_reserve_cents": breakage_reserve_cents,
        "deferred_revenue_cents": gross_ssp_cents - breakage_reserve_cents,
        "tier_benefit_expense_cents": rhu(
            (tier_points - base_points) * ssp_millicents, 1000
        ),
        "promo_expense_cents": rhu(
            (points_issued - tier_points) * ssp_millicents, 1000
        ),
    }


# --- Breakage estimate measurement (PRD §3.6) -------------------------------

def cohort_lots(cohort_id):
    member_ids = set(
        m["id"] for m in db.store.members.values() if m["cohort_id"] == cohort_id
    )
    return db.rows(
        db.store.point_lots,
        lambda l: l["member_id"] in member_ids and is_outstanding(l),
    )


def cohort_clamped_rate(cohort):
    return clamp(
        cohort["observed_redemption_rate_bp"] + cohort["program_change_adjustment_bp"],
        RATE_FLOOR_BP,
        RATE_CEIL_BP,
    )


def _snapshot(lots):
    return (
        sum(l["points_remaining"] for l in lots),
        sum(lot_remaining_gross_ssp_cents(l) for l in lots),
    )


def no_outstanding_points():
    return ApiError("ERR_NO_OUTSTANDING_POINTS", 409)


def estimate_measurement(program, cohort):
    """Returns the frozen measurement snapshot for a new BreakageEstimate.

    The rate is measured first where the variant makes it knowable, because the
    sensitivity-band rung sits above the outstanding-points rung in the ladder.
    """
    if cohort is not None:
        lots = cohort_lots(cohort["id"])
        points, gross = _snapshot(lots)
        rate = cohort_clamped_rate(cohort)
        method = "SINGLE_COHORT"
        empty = points <= 0
    elif program["breakage_method"] == "PROGRAM_HISTORICAL":
        lots = program_outstanding_lots(program["id"])
        points, gross = _snapshot(lots)
        rate = program["historical_redemption_rate_bp"]
        method = "PROGRAM_HISTORICAL"
        empty = points <= 0
    else:
        candidates = []
        for candidate in db.cohort_order(db.program_cohorts(program["id"])):
            weight = sum(l["points_remaining"] for l in cohort_lots(candidate["id"]))
            if weight > 0:
                candidates.append((candidate, weight))
        method = "COHORT_WEIGHTED"
        if not candidates:
            raise no_outstanding_points()
        total_weight = sum(w for _, w in candidates)
        weighted = sum(cohort_clamped_rate(c) * w for c, w in candidates)
        rate = rhu(weighted, total_weight)
        lots = program_outstanding_lots(program["id"])
        points, gross = _snapshot(lots)
        empty = points <= 0
    return {
        "method_applied": method,
        "estimated_redemption_rate_bp": rate,
        "outstanding_points_at_estimate": points,
        "outstanding_gross_ssp_cents_at_estimate": gross,
        "empty": empty,
    }


def sensitivity_bands(estimate):
    gross = estimate["outstanding_gross_ssp_cents_at_estimate"]
    low = rhu(gross * estimate["sensitivity_low_bp"], 10000)
    base = rhu(gross * estimate["estimated_redemption_rate_bp"], 10000)
    high = rhu(gross * estimate["sensitivity_high_bp"], 10000)
    return {
        "outstanding_gross_ssp_cents": gross,
        "low_bp": estimate["sensitivity_low_bp"],
        "base_bp": estimate["estimated_redemption_rate_bp"],
        "high_bp": estimate["sensitivity_high_bp"],
        "low_required_liability_cents": low,
        "base_required_liability_cents": base,
        "high_required_liability_cents": high,
        "band_range_cents": high - low,
        "memo_narrative": estimate["memo_narrative"],
    }


# --- Period close rollforward (PRD §3.7) ------------------------------------

def approved_estimate_for_period(period_id):
    for estimate in db.rows(db.store.breakage_estimates):
        if estimate["period_id"] == period_id and estimate["state"] == "APPROVED":
            return estimate
    return None


def opening_liability_cents(period):
    """Step 1: the programme's latest already-closed sibling period."""
    best = None
    for sibling in db.program_periods(period["program_id"]):
        if sibling["id"] == period["id"]:
            continue
        if sibling["state"] not in CLOSED_PERIOD_STATES:
            continue
        if best is None:
            best = sibling
            continue
        key = (sibling["end_at"], sibling["created_at"], sibling["_seq"])
        best_key = (best["end_at"], best["created_at"], best["_seq"])
        if key > best_key:
            best = sibling
    if best is None:
        return 0
    return best["closing_liability_cents"]


def rollforward(period):
    """The eight strictly ordered steps. Persists nothing."""
    opening = opening_liability_cents(period)
    issuance = period["issuance_deferred_cents"]
    redemption = period["redemption_recognized_cents"]
    remeasurement = period["remeasurement_delta_cents"]
    expiry = period["expiry_released_cents"]
    pre_catchup = opening + issuance - redemption - remeasurement - expiry
    estimate = approved_estimate_for_period(period["id"])
    rate = estimate["estimated_redemption_rate_bp"] if estimate is not None else 0
    gross_at_close = program_outstanding_gross_ssp_cents(period["program_id"])
    required = rhu(gross_at_close * rate, 10000)
    catch_up = required - pre_catchup
    closing = pre_catchup + catch_up
    return {
        "opening_liability_cents": opening,
        "issuance_deferred_cents": issuance,
        "redemption_recognized_cents": redemption,
        "remeasurement_delta_cents": remeasurement,
        "expiry_released_cents": expiry,
        "pre_catchup_liability_cents": pre_catchup,
        "outstanding_gross_ssp_cents": gross_at_close,
        "required_liability_cents": required,
        "catch_up_adjustment_cents": catch_up,
        "closing_liability_cents": closing,
        "breakage_recognized_cents": -catch_up,
        "approved_estimate_rate_bp": rate,
    }


# --- Partner settlement measurement (PRD §3.5) ------------------------------

def settlement_measurement(agreement, period):
    lots = db.rows(
        db.store.point_lots,
        lambda l: l["partner_agreement_id"] == agreement["id"]
        and l["period_id"] == period["id"],
    )
    events = db.rows(
        db.store.redemption_events,
        lambda e: e["partner_agreement_id"] == agreement["id"]
        and e["period_id"] == period["id"]
        and e["state"] in ("ALLOCATED", "FULFILLED"),
    )
    issued_points = sum(l["points_issued"] for l in lots)
    redeemed_points = sum(e["points_requested"] for e in events)
    receivable = rhu(issued_points * agreement["issuance_rate_millicents_per_point"], 1000)
    payable = rhu(redeemed_points * agreement["redemption_rate_millicents_per_point"], 1000)
    carried_forward = agreement["deferred_below_minimum_cents"]
    basis = "NET" if agreement["net_settlement_enabled"] else "GROSS"
    if basis == "NET":
        candidate = receivable - payable + carried_forward
    else:
        candidate = receivable + carried_forward
    if candidate < agreement["min_invoice_cents"]:
        net_due = 0
        deferred = candidate
    else:
        net_due = candidate
        deferred = 0
    return {
        "settlement_basis": basis,
        "partner_issued_points": issued_points,
        "partner_redeemed_points": redeemed_points,
        "issuance_receivable_cents": receivable,
        "redemption_payable_cents": payable,
        "carried_forward_cents": carried_forward,
        "net_due_cents": net_due,
        "deferred_below_minimum_cents": deferred,
        "due_date": add_days(period["end_at"], agreement["settlement_lag_days"]),
    }


# --- Programme change order projection (PRD §3.9) ---------------------------

def change_order_projection(program, change_type, new_ssp, elasticity):
    baseline_rate = 10000 - program["current_breakage_rate_bp"]
    projected_rate = clamp(baseline_rate + elasticity, RATE_FLOOR_BP, RATE_CEIL_BP)
    lots = program_outstanding_lots(program["id"])
    baseline_gross = sum(lot_remaining_gross_ssp_cents(l) for l in lots)
    if change_type == "SSP_CHANGE":
        projected_ssp = new_ssp
    else:
        projected_ssp = program["ssp_millicents_per_point"]
    projected_gross = sum(
        rhu(l["points_remaining"] * projected_ssp, 1000) for l in lots
    )
    delta = rhu(projected_gross * projected_rate, 10000) - rhu(
        baseline_gross * baseline_rate, 10000
    )
    return {
        "baseline_redemption_rate_bp": baseline_rate,
        "projected_redemption_rate_bp": projected_rate,
        "baseline_outstanding_gross_ssp_cents": baseline_gross,
        "projected_outstanding_gross_ssp_cents": projected_gross,
        "projected_liability_delta_cents": delta,
    }
