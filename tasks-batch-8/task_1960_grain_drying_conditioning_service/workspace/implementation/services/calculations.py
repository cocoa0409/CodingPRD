"""Calculation rules (scaffold §1.3 / PRD §3). All Decimal, round-half-up,
no intermediate rounding, floors applied last (PRD §2.6)."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from db import current_date, parse_date, store, touch

LBS_PER_BUSHEL = {"CORN": 56, "SOYBEAN": 60, "WHEAT": 60}
BENCHMARK_PRICE_CENTS = {"CORN": 450, "SOYBEAN": 1050, "WHEAT": 620}
HANDLING_SHRINK_PCT = Decimal("0.5")
CLAIM_DEDUCTIBLE_CENTS = 2500
CLAIM_CAP_PCT = Decimal("0.40")
PREEXISTING_MOISTURE_PCT = Decimal("26.0")
PREEXISTING_FM_PCT = Decimal("8.0")
OUT_OF_SPEC_TOLERANCE_PCT = Decimal("0.5")
DRYER_INTAKE_LIMIT_PCT = Decimal("26.0")


def D(x):
    return Decimal(str(x))


def rhu_int(d):
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_2(d):
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- schedules

def find_schedule(commodity, on_date):
    """The schedule whose [effective_from, effective_to] window covers on_date."""
    for s in store.schedules.values():
        if s["commodity"] != commodity:
            continue
        if parse_date(s["effective_from"]) <= on_date <= parse_date(s["effective_to"]):
            return s
    return None


# ------------------------------------------------- provisional_shrink_estimate

def provisional_shrink_estimate(lot):
    """Runs at every certification. Returns (shrink_pct float full precision,
    provisional_dry_weight_lbs int)."""
    intake = D(lot["intake_moisture_pct"])
    target = D(lot["target_moisture_pct"])
    water_shrink_pct = (intake - target) / (Decimal("100") - target) * Decimal("100")
    shrink = water_shrink_pct + HANDLING_SHRINK_PCT
    dry = rhu_int(D(lot["wet_net_weight_lbs"]) * (Decimal("1") - shrink / Decimal("100")))
    return float(shrink), dry


# ---------------------------------------------------------------- drying_charge

def drying_charge(lot, schedule):
    """Tiered pricing; identical arithmetic in preview, confirm estimate, and
    invoice composition. Returns dict of computed figures."""
    bushels = D(lot["wet_net_weight_lbs"]) / D(LBS_PER_BUSHEL[lot["commodity"]])
    intake = D(lot["intake_moisture_pct"])
    target = D(lot["target_moisture_pct"])
    points_removed = max(Decimal("0"), intake - target)
    if intake <= D(schedule["t1_max_moisture_pct"]):
        rate = schedule["rate_t1_cents_per_pt_bu"]
    elif intake <= D(schedule["t2_max_moisture_pct"]):
        rate = schedule["rate_t2_cents_per_pt_bu"]
    else:
        rate = schedule["rate_t3_cents_per_pt_bu"]
    base = bushels * points_removed * D(rate)
    fm_applied = D(lot["foreign_material_pct"]) > D(schedule["fm_threshold_pct"])
    if fm_applied:
        base = base * (Decimal("1") + D(schedule["fm_surcharge_pct"]))
    charge = max(schedule["min_charge_cents"], rhu_int(base))
    return {
        "bushels": float(bushels),
        "points_removed": float(points_removed),
        "rate_cents_per_pt_bu": rate,
        "fm_surcharge_applied": fm_applied,
        "drying_charge_cents": charge,
    }


# ------------------------------------------------------ energy_passthrough_charge

def energy_passthrough_charge(run, lot, schedule, actual_end):
    """Metered or estimated variant; marginal tiers; round half up to cents.
    Returns (fuel_therms float, energy_charge_cents int)."""
    if run["energy_estimated"]:
        duration_seconds = Decimal(str((actual_end - run["_actual_start_dt"]).total_seconds()))
        duration_hours = duration_seconds / Decimal("3600")
        points_removed = D(lot["intake_moisture_pct"]) - D(run["discharge_moisture_pct"])
        fuel = (
            duration_hours
            * D(schedule["est_therms_per_hour"])
            * (Decimal("1") + D(schedule["est_point_factor"]) * points_removed)
        )
    else:
        fuel = D(run["meter_end_therms"]) - D(run["meter_start_therms"])
    t1_limit = D(schedule["energy_t1_limit_therms"])
    charge = rhu_int(
        min(fuel, t1_limit) * D(schedule["energy_t1_rate_cents_per_therm"])
        + max(Decimal("0"), fuel - t1_limit) * D(schedule["energy_t2_rate_cents_per_therm"])
    )
    return float(fuel), charge


# ---------------------------------------------------- final_weight_reconciliation

def final_weight_reconciliation(lot, scale_out_weight_lbs):
    """Returns (final_dry_weight_lbs, final_shrink_pct float, shrink_variance_lbs)."""
    wet_net = D(lot["wet_net_weight_lbs"])
    final_dry = scale_out_weight_lbs
    final_shrink = rhu_2((wet_net - D(final_dry)) / wet_net * Decimal("100"))
    variance = lot["provisional_dry_weight_lbs"] - final_dry
    return final_dry, float(final_shrink), variance


# ---------------------------------------------------------------- blend_quantities

def blend_required_low_lbs(high_lot, low_lot, target_moisture_pct):
    """Pearson square, rounded UP to whole lbs."""
    q_low = (
        D(high_lot["final_dry_weight_lbs"])
        * (D(high_lot["current_moisture_pct"]) - D(target_moisture_pct))
        / (D(target_moisture_pct) - D(low_lot["current_moisture_pct"]))
    )
    return int(q_low.to_integral_value(rounding=ROUND_CEILING))


def blend_result(high_lot, low_lot, required_low_lbs):
    """Returns (result_weight_lbs, result_moisture_pct float)."""
    weight = high_lot["final_dry_weight_lbs"] + required_low_lbs
    moisture = rhu_2(
        (
            D(high_lot["final_dry_weight_lbs"]) * D(high_lot["current_moisture_pct"])
            + D(required_low_lbs) * D(low_lot["current_moisture_pct"])
        )
        / D(weight)
    )
    return weight, float(moisture)


# ------------------------------------------------------- claim_liability_assessment

def claim_liability_assessment(claim, lot, run):
    """Returns (lot_value_cents, fault_multiplier float, assessed_liability_cents)."""
    bushels_final = rhu_2(D(lot["final_dry_weight_lbs"]) / D(LBS_PER_BUSHEL[lot["commodity"]]))
    lot_value = rhu_int(bushels_final * D(BENCHMARK_PRICE_CENTS[lot["commodity"]]))
    if (
        D(lot["intake_moisture_pct"]) > PREEXISTING_MOISTURE_PCT
        or D(lot["foreign_material_pct"]) > PREEXISTING_FM_PCT
    ):
        multiplier = Decimal("0.25")
    elif abs(D(run["discharge_moisture_pct"]) - D(lot["target_moisture_pct"])) > OUT_OF_SPEC_TOLERANCE_PCT:
        multiplier = Decimal("1.5")
    else:
        multiplier = Decimal("1.0")
    cap = rhu_int(CLAIM_CAP_PCT * D(lot_value))
    adjusted = rhu_int(max(Decimal("0"), D(claim["claimed_amount_cents"]) - D(CLAIM_DEDUCTIBLE_CENTS)) * multiplier)
    return lot_value, float(multiplier), min(cap, adjusted)


# ---------------------------------------------------------------- storage_accrual

def storage_baseline_bushels(lot):
    return float(rhu_2(D(lot["final_dry_weight_lbs"]) / D(LBS_PER_BUSHEL[lot["commodity"]])))


def storage_accrued_days(agreement, on_date=None):
    """Days in [start_date, min(closed_date, current_date)) — half-open."""
    if agreement["start_date"] is None:
        return 0
    start = parse_date(agreement["start_date"])
    end = parse_date(agreement["closed_date"]) if agreement["closed_date"] else (on_date or current_date())
    days = (end - start).days
    return max(0, days)


def storage_accrual_cents(agreement, accrued_days):
    cents = D(agreement["baseline_bushels"]) * D(agreement["daily_rate_cents_per_bu"]) * D(
        max(agreement["min_days"], accrued_days)
    )
    return rhu_int(cents)


# ---------------------------------------------------------- daily_capacity_commitment

def committed_bushels(unit_id, window_date):
    """CONFIRMED and CONSUMED tickets hold capacity for their (unit, date)."""
    standard = 0
    total = 0
    for t in store.tickets.values():
        if (
            t["unit_id"] == unit_id
            and t["window_date"] == window_date
            and t["status"] in ("CONFIRMED", "CONSUMED")
        ):
            total += t["requested_bushels"]
            if t["priority_class"] == "STANDARD":
                standard += t["requested_bushels"]
    return standard, total


# --------------------------------------------------------------- prepaid waterfall

def prepaid_waterfall(customer):
    """Auto-apply prepaid balance across the customer's ISSUED invoices,
    oldest issued_at ASC, ties by created_at ASC."""
    issued = [
        inv
        for inv in store.invoices.values()
        if inv["customer_id"] == customer["id"] and inv["status"] == "ISSUED"
    ]
    issued.sort(key=lambda i: (i["issued_at"] or "", i["created_at"], i["_seq"]))
    for inv in issued:
        if customer["prepaid_balance_cents"] <= 0:
            break
        applied = min(customer["prepaid_balance_cents"], inv["amount_due_cents"])
        if applied <= 0:
            continue
        inv["amount_due_cents"] -= applied
        customer["prepaid_balance_cents"] -= applied
        if inv["amount_due_cents"] == 0:
            inv["status"] = "PAID"
        touch(inv)
