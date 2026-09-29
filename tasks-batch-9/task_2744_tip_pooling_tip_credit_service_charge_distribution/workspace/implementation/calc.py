"""Money and minute arithmetic: rounding, splits and the wage waterfall."""

from decimal import ROUND_HALF_UP, Decimal

FEDERAL_MIN_WAGE_CENTS = 725
FEDERAL_CASH_WAGE_FLOOR_CENTS = 213
TIPPED_EMPLOYEE_MONTHLY_THRESHOLD_CENTS = 3000
OT_THRESHOLD_MINUTES = 2400
SIDE_WORK_CONTINUOUS_LIMIT_MINUTES = 30
ALLOCATED_TIPS_THRESHOLD_NUM = 8
ALLOCATED_TIPS_THRESHOLD_DEN = 100


def rhu(numerator, denominator):
    """Exact rational division rounded half up to a whole cent/minute."""
    return int(
        (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
            Decimal(1), rounding=ROUND_HALF_UP
        )
    )


def bps_of(amount_cents, rate_bps):
    """Apply a basis-point rate to an amount, rounded half up."""
    return rhu(amount_cents * rate_bps, 10000)


def per_hour(rate_cents_per_hour, minutes):
    """Apply an hourly rate to a block of minutes, rounded half up."""
    return rhu(rate_cents_per_hour * minutes, 60)


# ---------------------------------------------------------------------------
# floor plus largest-remainder split
# ---------------------------------------------------------------------------

def largest_remainder(amount, items):
    """Split ``amount`` across ``items``.

    ``items`` is a list of (key, weight, tiebreak) tuples.  Returns a list of
    (key, share, won_remainder_cent) in the input order.  Base shares are
    floored; the leftover cents are handed out one each in descending weight
    then ascending tiebreak order.
    """
    total_weight = sum(weight for _, weight, _ in items)
    if not items or total_weight <= 0:
        return [(key, 0, False) for key, _, _ in items]

    bases = {}
    for key, weight, _ in items:
        bases[key] = amount * weight // total_weight
    leftover = amount - sum(bases.values())

    order = sorted(range(len(items)), key=lambda i: (-items[i][1], items[i][2]))
    winners = set()
    for index in order[:max(0, leftover)]:
        winners.add(items[index][0])

    result = []
    for key, _, _ in items:
        result.append((key, bases[key] + (1 if key in winners else 0), key in winners))
    return result


# ---------------------------------------------------------------------------
# side-work classification (POST /shifts/{id}/close)
# ---------------------------------------------------------------------------

def side_work_classification(shift, job_role, assignment, location):
    scheduled = shift["scheduled_minutes"]
    gated = (
        not location["tip_credit_enabled"]
        or job_role["tip_status"] == "NON_TIPPED"
        or assignment is None
        or assignment.get("tip_credit_notice_acknowledged_at") is None
        or assignment["tip_credit_notice_acknowledged_at"] > shift["start_at"]
    )
    if gated:
        return scheduled, 0
    pct_allowance = scheduled * 20 // 100
    excess_percentage = max(0, shift["side_work_minutes"] - pct_allowance)
    excess_continuous = max(
        0, shift["max_continuous_side_work_minutes"] - SIDE_WORK_CONTINUOUS_LIMIT_MINUTES
    )
    non_tip_credit = max(excess_percentage, excess_continuous)
    return non_tip_credit, scheduled - non_tip_credit


# ---------------------------------------------------------------------------
# the wage waterfall (S0 - S9)
# ---------------------------------------------------------------------------

def wage_common(location, employee, shifts, tips_by_shift, service_charge_wages):
    """Steps S0 to S5, shared by both variants.

    ``shifts`` are the employee's CLOSED shifts of the period; ``tips_by_shift``
    maps shift id to the net pool allocation credited to that shift.
    """
    out = {}
    declared_total = sum(
        s["declared_cash_tips_cents"] + s["declared_charged_tips_cents"] for s in shifts
    )
    has_eligible_minutes = any(s["tip_credit_eligible_minutes"] > 0 for s in shifts)
    qualified = (
        bool(location["tip_credit_enabled"])
        and has_eligible_minutes
        and (employee["monthly_tip_baseline_cents"] + declared_total)
        >= TIPPED_EMPLOYEE_MONTHLY_THRESHOLD_CENTS
    )
    out["tipped_employee_qualified"] = qualified

    total_minutes = sum(s["scheduled_minutes"] for s in shifts)
    eligible_minutes = (
        sum(s["tip_credit_eligible_minutes"] for s in shifts) if qualified else 0
    )
    out["total_minutes"] = total_minutes
    out["tip_credit_eligible_minutes"] = eligible_minutes
    out["non_tip_credit_minutes"] = total_minutes - eligible_minutes
    out["overtime_minutes"] = max(0, total_minutes - OT_THRESHOLD_MINUTES)
    out["regular_minutes"] = total_minutes - out["overtime_minutes"]

    amw = location["applicable_min_wage_cents"]
    out["straight_cash_cents"] = per_hour(
        location["cash_wage_cents"], eligible_minutes
    ) + per_hour(amw, out["non_tip_credit_minutes"])

    out["service_charge_wages_cents"] = service_charge_wages

    if total_minutes > 0:
        out["regular_rate_cents_per_hour"] = rhu(
            (out["straight_cash_cents"] + service_charge_wages) * 60, total_minutes
        )
    else:
        out["regular_rate_cents_per_hour"] = 0

    out["overtime_premium_cents"] = rhu(
        out["regular_rate_cents_per_hour"] * out["overtime_minutes"], 120
    )

    retained = sum(s["retained_tips_cents"] for s in shifts)
    pool_tips = sum(tips_by_shift.get(s["id"], 0) for s in shifts)
    out["retained_tips_cents"] = retained
    out["pool_tips_cents"] = pool_tips
    out["tips_available_cents"] = retained + pool_tips
    out["reported_tips_cents"] = retained + pool_tips
    return out


def _obligation(amw, regular_minutes, overtime_minutes):
    return per_hour(amw, regular_minutes) + rhu(3 * amw * overtime_minutes, 120)


def wage_weekly_aggregate(location, base):
    """Steps S6 to S8 run once across the whole workweek."""
    amw = location["applicable_min_wage_cents"]
    obligation = _obligation(amw, base["regular_minutes"], base["overtime_minutes"])
    max_credit = per_hour(
        location["max_tip_credit_per_hour_cents"], base["tip_credit_eligible_minutes"]
    )
    residual = (
        obligation
        - base["straight_cash_cents"]
        - base["service_charge_wages_cents"]
        - base["overtime_premium_cents"]
    )
    credit = max(0, min(max_credit, base["tips_available_cents"], residual))
    if not base["tipped_employee_qualified"]:
        credit = 0
    topup = max(0, residual - credit)
    return {
        "minimum_wage_obligation_cents": obligation,
        "tip_credit_cents": credit,
        "topup_cents": topup,
    }


def wage_per_shift(location, base, shifts, tips_by_shift):
    """Steps S6 to S8 run separately for each CLOSED shift.

    ``shifts`` must already be ordered by (business_date ASC, created_at ASC).
    The period-level service-charge wages and overtime premium are subtracted
    from the residual of the earliest shift alone.  Returns the summed credit,
    the summed top-up and the per-shift credit map.
    """
    amw = location["applicable_min_wage_cents"]
    qualified = base["tipped_employee_qualified"]
    period_level = base["service_charge_wages_cents"] + base["overtime_premium_cents"]

    total_credit = 0
    total_topup = 0
    per_shift_credit = {}
    for index, shift in enumerate(shifts):
        minutes = shift["scheduled_minutes"]
        eligible = shift["tip_credit_eligible_minutes"] if qualified else 0
        non_eligible = minutes - eligible
        overtime = max(0, minutes - OT_THRESHOLD_MINUTES)
        regular = minutes - overtime

        straight = per_hour(location["cash_wage_cents"], eligible) + per_hour(
            amw, non_eligible
        )
        obligation = _obligation(amw, regular, overtime)
        max_credit = per_hour(location["max_tip_credit_per_hour_cents"], eligible)
        tips = shift["retained_tips_cents"] + tips_by_shift.get(shift["id"], 0)

        residual = obligation - straight
        if index == 0:
            residual -= period_level
        credit = max(0, min(max_credit, tips, residual))
        if not qualified:
            credit = 0
        topup = max(0, residual - credit)

        per_shift_credit[shift["id"]] = credit
        total_credit += credit
        total_topup += topup
    return total_credit, total_topup, per_shift_credit


def allocated_tips_threshold(gross_receipts_cents):
    return rhu(
        ALLOCATED_TIPS_THRESHOLD_NUM * gross_receipts_cents,
        ALLOCATED_TIPS_THRESHOLD_DEN,
    )
