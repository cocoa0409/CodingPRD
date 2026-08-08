"""Calculation rules (SCAFFOLD Table 1.3 / PRD section 3).

Money is always integer cents computed through decimal.Decimal with
ROUND_HALF_UP.  Panel slot weights are compared as integers-times-ten so that
4.5 <= 4.5 is exact.
"""
from decimal import Decimal, ROUND_HALF_UP

import constants as C
from store import db
from timeutil import add_days, day_diff, fmt_date, minute_of_day, weekday_name


# ---------------------------------------------------------------- money -----
def round_half_up(value):
    """value: Decimal -> int cents, half away from zero."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def discounted_rate_cents(base_rate_cents, discount_pct):
    return round_half_up(Decimal(base_rate_cents) * (Decimal(1) - Decimal(discount_pct)))


def prorated_cents(monthly_rate_cents, covered_days, days_in_cycle):
    return round_half_up(
        Decimal(monthly_rate_cents) * Decimal(covered_days) / Decimal(days_in_cycle)
    )


# ------------------------------------------------- (10) panel slot weights --
def tenths(weight):
    """Weight comparisons run on the value multiplied by ten, rounded to the
    nearest integer (SLOT_WEIGHT_DECIMAL_PLACES = 1)."""
    scaled = Decimal(str(weight)) * Decimal(10)
    return int(scaled.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_tenths(value):
    return round(value / 10.0, 1)


def child_age_days(child, on_date=None):
    on_date = on_date or db.today()
    return day_diff(on_date, child["date_of_birth"])


def slot_weight_for_age(age_days):
    if age_days < C.INFANT_SLOT_WEIGHT_MAX_AGE_DAYS:
        return C.INFANT_SLOT_WEIGHT
    if age_days < C.TODDLER_SLOT_WEIGHT_MAX_AGE_DAYS:
        return C.TODDLER_SLOT_WEIGHT
    return C.STANDARD_SLOT_WEIGHT


def child_slot_weight(child):
    return slot_weight_for_age(child_age_days(child))


def weighted_occupancy_tenths(physician_id):
    total = 0
    for m in db.memberships.values():
        if m["physician_id"] != physician_id:
            continue
        if m["status"] not in C.MEMBERSHIP_OCCUPYING_STATUSES:
            continue
        child = db.children.get(m["child_id"])
        if child is None:
            continue
        total += tenths(child_slot_weight(child))
    return total


def physician_occupancy(physician):
    occ_t = weighted_occupancy_tenths(physician["id"])
    cap_t = tenths(physician["panel_slot_cap"])
    avail_t = cap_t - occ_t
    if avail_t < 0:
        avail_t = 0
    return from_tenths(occ_t), from_tenths(avail_t)


# ------------------------------------------- (2)/(3) invoice construction ---
def covered_days_for(membership, cycle_start, cycle_end):
    from_date = max(membership["start_date"], cycle_start)
    cancel_date = membership.get("cancellation_effective_date")
    if cancel_date is None:
        to_date = cycle_end
    else:
        to_date = min(cancel_date, cycle_end)
    covered = day_diff(to_date, from_date) + 1
    if covered < 0:
        covered = 0
    return covered


def membership_in_cycle(membership, cycle_start):
    if membership["status"] in C.MEMBERSHIP_OCCUPYING_STATUSES:
        return True
    if membership["status"] == "CANCELLED":
        cd = membership.get("cancellation_effective_date")
        return cd is not None and cd >= cycle_start
    return False


def build_invoice_lines(family, cycle_start, cycle_end, days_in_cycle):
    """calculations.family_invoice_total — discount, prorate, round PER LINE,
    sum, then waterfall the family cap in the exact reverse of the line order."""
    rows = []
    for m in db.memberships.values():
        if m["family_id"] != family["id"]:
            continue
        if not membership_in_cycle(m, cycle_start):
            continue
        covered = covered_days_for(m, cycle_start, cycle_end)
        if covered <= 0:
            continue  # omitted from lines entirely
        plan = db.plans.get(m["plan_id"])
        base = plan["monthly_rate_cents"] if plan else 0
        discount = Decimal(str(m["discount_pct"]))
        monthly = discounted_rate_cents(base, discount)
        rows.append(
            {
                "_is_cancelled": 1 if m["status"] == "CANCELLED" else 0,
                "_seq": m["_seq"],
                "membership_id": m["id"],
                "child_id": m["child_id"],
                "enrollment_sequence": m["enrollment_sequence"],
                "base_rate_cents": base,
                "discount_pct": float(discount),
                "monthly_rate_cents": monthly,
                "covered_days": covered,
                "prorated_cents": prorated_cents(monthly, covered, days_in_cycle),
                "cap_adjustment_cents": 0,
                "line_total_cents": 0,
            }
        )

    rows.sort(key=lambda r: (r["_is_cancelled"], r["enrollment_sequence"], r["_seq"]))
    subtotal = sum(r["prorated_cents"] for r in rows)
    cap_adjustment = subtotal - family["family_monthly_cap_cents"]
    if cap_adjustment < 0:
        cap_adjustment = 0

    remaining = cap_adjustment
    for row in reversed(rows):
        take = min(remaining, row["prorated_cents"])
        row["cap_adjustment_cents"] = take
        row["line_total_cents"] = row["prorated_cents"] - take
        remaining -= take

    lines = []
    for row in rows:
        line = {k: v for k, v in row.items() if not k.startswith("_")}
        lines.append(line)
    return lines, subtotal, cap_adjustment, subtotal - cap_adjustment


# --------------------------------------------- (12) after-hours surcharge ---
def after_hours_verdict(started_at, plan):
    local_date = started_at.date()
    mod = minute_of_day(started_at)
    day_name = weekday_name(local_date)

    if day_name in C.WEEKEND_WEEKDAY_NAMES:
        after_hours, reason = True, "WEEKEND"
    elif fmt_date(local_date) in C.DECLARED_HOLIDAY_DATES:
        after_hours, reason = True, "HOLIDAY"
    elif mod >= C.AFTER_HOURS_EVENING_START_MINUTE:
        after_hours, reason = True, "WEEKDAY_EVENING"
    elif mod < C.AFTER_HOURS_MORNING_END_MINUTE:
        after_hours, reason = True, "WEEKDAY_EARLY_MORNING"
    else:
        after_hours, reason = False, None

    if not after_hours or (plan is not None and plan["after_hours_surcharge_waived"]):
        surcharge = 0
    else:
        surcharge = C.AFTER_HOURS_SURCHARGE_CENTS
    return after_hours, reason, surcharge


# ------------------------------------------------- (9) well-visit punctuality
def well_visit_punctuality(completed_date, window_open_date, window_close_date):
    if completed_date < window_open_date:
        return "EARLY"
    if completed_date <= window_close_date:
        return "ON_SCHEDULE"
    return "DELAYED"


# ------------------------------------------- (8) well-visit schedule shape --
def well_visit_rows_for(date_of_birth, start_date):
    out = []
    for milestone in C.WELL_VISIT_SCHEDULE:
        window_open = add_days(date_of_birth, milestone["window_open_offset_days"])
        window_close = add_days(date_of_birth, milestone["window_close_offset_days"])
        target = add_days(date_of_birth, milestone["target_age_days"])
        if window_close >= start_date:  # inclusive
            out.append(
                {
                    "milestone_code": milestone["milestone_code"],
                    "target_date": target,
                    "window_open_date": window_open,
                    "window_close_date": window_close,
                }
            )
    return out


# ---------------------------------- (7) immunization completeness for age ---
def immunization_complete_for_age(child):
    age_days = child_age_days(child)
    for vaccine_code, spec in C.VACCINE_SCHEDULE.items():
        required = 0
        for position in spec["positions"]:
            if position["min_age_days"] + C.IMMUNIZATION_DUE_LAG_DAYS <= age_days:
                required += 1
        have = 0
        for dose in db.doses.values():
            if (
                dose["child_id"] == child["id"]
                and dose["vaccine_code"] == vaccine_code
                and dose["validity"] == "VALID"
            ):
                have += 1
        if have < required:
            return False
    return True


# ------------------------------------------------ (13) membership year index
def membership_year_index(membership, on_date):
    return day_diff(on_date, membership["start_date"]) // C.MEMBERSHIP_YEAR_DAYS


# -------------------------------------- (5) service-line financial split ----
def insurance_split(billed_amount_cents, allowed_amount_cents, policy):
    remaining = policy["deductible_cents"] - policy["deductible_met_cents"]
    if remaining < 0:
        remaining = 0
    ded_applied = min(allowed_amount_cents, remaining)
    after_ded = allowed_amount_cents - ded_applied
    coinsurance = round_half_up(
        Decimal(after_ded) * Decimal(str(policy["coinsurance_rate"]))
    )
    plan_paid = after_ded - coinsurance
    patient_resp = ded_applied + coinsurance
    write_off = billed_amount_cents - allowed_amount_cents
    return {
        "allowed_amount_cents": allowed_amount_cents,
        "write_off_cents": write_off,
        "deductible_applied_cents": ded_applied,
        "coinsurance_cents": coinsurance,
        "plan_paid_cents": plan_paid,
        "patient_responsibility_cents": patient_resp,
        "membership_covered_cents": 0,
    }
