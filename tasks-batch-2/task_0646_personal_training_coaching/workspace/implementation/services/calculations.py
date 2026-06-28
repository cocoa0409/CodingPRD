"""Pure calculation rules (scaffold §1.3, PRD §3.3/§3.4/§3.6/§3.7).

All money/integer rounding uses round-half-up. Floats are used for intermediate
real-valued math (BMR/TDEE, ratios) but every persisted/returned numeric value
is produced via round_half_up to a whole integer, per PRD §2.8.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

# --- Constants (scaffold §1.3) ---
NO_SHOW_CUTOFF_SECONDS = 86400      # exactly 24 hours; boundary >= (free) vs < (fee)
NO_SHOW_FEE_PCT = Decimal("0.50")
NO_SHOW_STRIKE_LIMIT = 3            # strike 2 -> ALLOWED, strike 3 -> SUSPENDED (>=)
TRAINER_BUFFER_SECONDS = 900        # 15-minute pad between a trainer's sessions
TAX_PCT = Decimal("0.0875")
MONTHLY_CYCLE_DAYS = 30

ACTIVITY_MULT = {"SEDENTARY": Decimal("1.2"), "MODERATE": Decimal("1.55"), "ACTIVE": Decimal("1.725")}
# goal -> (protein_frac, carb_frac, fat_frac) of calories
SPLIT = {
    "FAT_LOSS": (Decimal("0.40"), Decimal("0.30"), Decimal("0.30")),
    "MAINTENANCE": (Decimal("0.30"), Decimal("0.40"), Decimal("0.30")),
    "MUSCLE_GAIN": (Decimal("0.30"), Decimal("0.45"), Decimal("0.25")),
}
GOAL_CAL_MULT = {
    "FAT_LOSS": Decimal("0.80"),     # tdee * (1 - 0.20)
    "MAINTENANCE": Decimal("1.00"),
    "MUSCLE_GAIN": Decimal("1.10"),  # tdee * (1 + 0.10)
}

W_WORKOUT = Decimal("0.50")
W_NUTRITION = Decimal("0.30")
W_HABIT = Decimal("0.20")


def round_half_up(value):
    """Round a numeric (int/float/Decimal/str) to the nearest whole integer,
    half rounding upward."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def per_session_value_cents(price_cents, total_sessions):
    """round_half_up(price_cents / total_sessions) — scaffold §1.3."""
    return round_half_up(Decimal(price_cents) / Decimal(total_sessions))


def no_show_fee_cents(billing_model, per_session_value):
    """Fee for NO_SHOW / LATE_CANCELLED. SESSION_PACK -> 50% of per-session value
    (round_half_up); ONLINE_SUBSCRIPTION -> 0."""
    if billing_model == "SESSION_PACK":
        return round_half_up(Decimal(per_session_value) * NO_SHOW_FEE_PCT)
    return 0


def invoice_breakdown(line_items):
    """package_invoice_total — round per line, THEN sum, THEN tax once.

    Each line: { list_price_cents, discount_pct }.
    """
    subtotal = 0
    for line in line_items:
        list_price = Decimal(line["list_price_cents"])
        discount = Decimal(str(line["discount_pct"]))
        line_net = round_half_up(list_price * (Decimal(1) - discount))
        subtotal += line_net
    tax = round_half_up(Decimal(subtotal) * TAX_PCT)
    total = subtotal + tax
    return {"subtotal_cents": subtotal, "tax_cents": tax, "invoice_total_cents": total}


def subscription_refund_cents(monthly_fee_cents, cycle_start_utc, current_clock_utc):
    """Mid-cycle subscription proration refund (scaffold §1.3 / PRD §3.7).

    cycle_days = 30; elapsed = floor((now - cycle_start)/86400);
    remaining = clamp(cycle_days - elapsed, 0, cycle_days);
    refund = round_half_up(monthly_fee_cents * remaining / cycle_days).
    """
    cycle_days = MONTHLY_CYCLE_DAYS
    elapsed_seconds = (current_clock_utc - cycle_start_utc).total_seconds()
    elapsed_days = math.floor(elapsed_seconds / 86400)
    remaining_days = cycle_days - elapsed_days
    if remaining_days < 0:
        remaining_days = 0
    elif remaining_days > cycle_days:
        remaining_days = cycle_days
    refund = round_half_up(Decimal(monthly_fee_cents) * Decimal(remaining_days) / Decimal(cycle_days))
    return refund


def macro_targets(sex, height_cm, age, weight_kg, goal, activity_level):
    """Mifflin-St Jeor BMR -> TDEE -> target_calories -> macro split.

    Pinned order: (1) bmr, (2) tdee, (3) target_calories, (4) macro split.
    Returns (target_calories, protein_g, carb_g, fat_g) — all integers.
    """
    w = Decimal(str(weight_kg))
    h = Decimal(str(height_cm))
    a = Decimal(age)
    if sex == "MALE":
        bmr = Decimal(10) * w + Decimal("6.25") * h - Decimal(5) * a + Decimal(5)
    else:  # FEMALE
        bmr = Decimal(10) * w + Decimal("6.25") * h - Decimal(5) * a - Decimal(161)
    tdee = bmr * ACTIVITY_MULT[activity_level]
    target_calories = round_half_up(tdee * GOAL_CAL_MULT[goal])
    pp, cp, fp = SPLIT[goal]
    tc = Decimal(target_calories)
    protein_g = round_half_up(tc * pp / Decimal(4))
    carb_g = round_half_up(tc * cp / Decimal(4))
    fat_g = round_half_up(tc * fp / Decimal(9))
    return target_calories, protein_g, carb_g, fat_g


def adherence_score(window_start, window_end, planned_workouts_per_week,
                    habit_checks_target, habit_logs):
    """Weighted adherence score over a half-open window (scaffold §1.3 / PRD §3.6).

    habit_logs: iterable of dicts with keys 'kind' and 'logged_at' (datetime),
    already filtered to the engagement. The function applies the window filter.
    Round once at the very end.
    """
    window_seconds = (window_end - window_start).total_seconds()
    window_days = math.ceil(window_seconds / 86400)
    if window_days <= 0:
        window_days = 1  # defensive; validation guarantees window_end > window_start

    # planned_workouts kept at full rational precision (no early rounding)
    planned_workouts = Decimal(planned_workouts_per_week) * (Decimal(window_days) / Decimal(7))

    completed_workouts = 0
    nutrition_dates = set()
    habit_checks = 0
    for log in habit_logs:
        la = log["logged_at"]
        if not (window_start <= la < window_end):
            continue
        kind = log["kind"]
        if kind == "WORKOUT_COMPLETED":
            completed_workouts += 1
        elif kind == "NUTRITION_LOGGED":
            # logged_at is tz-aware UTC; distinct UTC calendar dates.
            nutrition_dates.add(la.date())
        elif kind == "HABIT_CHECK":
            habit_checks += 1

    # workout_ratio = min(1, completed / planned)
    if planned_workouts > 0:
        workout_ratio = min(Decimal(1), Decimal(completed_workouts) / planned_workouts)
    else:
        workout_ratio = Decimal(0)
    nutrition_ratio = min(Decimal(1), Decimal(len(nutrition_dates)) / Decimal(window_days))
    if habit_checks_target > 0:
        habit_ratio = min(Decimal(1), Decimal(habit_checks) / Decimal(habit_checks_target))
    else:
        habit_ratio = Decimal(0)

    blended = W_WORKOUT * workout_ratio + W_NUTRITION * nutrition_ratio + W_HABIT * habit_ratio
    return round_half_up(Decimal(100) * blended)
