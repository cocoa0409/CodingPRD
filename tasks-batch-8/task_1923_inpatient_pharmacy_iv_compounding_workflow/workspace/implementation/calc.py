"""Calculation rules (PRD Sections 3.2, 3.4, 3.5, 3.7).

All clinical quantities use Decimal at 2 decimal places, round-half-up.
Dose volumes follow the step ladder (round each component first, then sum).
"""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

import db


TWO_DP = Decimal("0.01")


def round2(value):
    return Decimal(value).quantize(TWO_DP, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Patient renal panel (Section 3.2)
# ---------------------------------------------------------------------------

def age_years(date_of_birth, clock_now):
    """Whole-year floor between DOB and the clock; birthday counts that day."""
    dob = date_of_birth.date() if hasattr(date_of_birth, "date") else date_of_birth
    today = clock_now.date()
    years = today.year - dob.year
    if (today.month, today.day) < (dob.month, dob.day):
        years -= 1
    return years


def height_inches(height_cm):
    return Decimal(str(height_cm)) / Decimal("2.54")


def ideal_body_weight(sex, height_cm):
    inches = height_inches(height_cm)
    base = Decimal("50") if sex == "M" else Decimal("45.5")
    return round2(base + Decimal("2.3") * (inches - Decimal("60")))


def body_mass_index(weight_kg, height_cm):
    meters = Decimal(str(height_cm)) / Decimal("100")
    return round2(Decimal(str(weight_kg)) / (meters * meters))


def adjusted_body_weight(sex, height_cm, weight_kg):
    ibw = ideal_body_weight(sex, height_cm)
    return round2(ibw + Decimal("0.4") * (Decimal(str(weight_kg)) - ibw))


def cockcroft_gault(age, weight_kg, sex, scr_mg_dl):
    factor = Decimal("0.85") if sex == "F" else Decimal("1.0")
    numer = Decimal(140 - age) * Decimal(str(weight_kg)) * factor
    denom = Decimal("72") * Decimal(str(scr_mg_dl))
    return round2(numer / denom)


def compute_patient_panel(patient, clock_now):
    """Compute the six derived panel values from current inputs + clock."""
    age = age_years(patient["date_of_birth"], clock_now)
    bmi = body_mass_index(patient["weight_kg"], patient["height_cm"])
    ibw = ideal_body_weight(patient["sex"], patient["height_cm"])
    obese = bmi >= Decimal("30")
    abw = adjusted_body_weight(patient["sex"], patient["height_cm"], patient["weight_kg"]) if obese else None
    crcl_ibw = cockcroft_gault(age, ibw, patient["sex"], patient["scr_mg_dl"])
    crcl_abw = cockcroft_gault(age, abw, patient["sex"], patient["scr_mg_dl"]) if obese else None
    return {
        "age_years": age,
        "bmi": bmi,
        "ibw_kg": ibw,
        "abw_kg": abw,
        "crcl_ibw_ml_min": crcl_ibw,
        "crcl_abw_ml_min": crcl_abw,
    }


# ---------------------------------------------------------------------------
# Renal dose adjustment (Section 3.4)
# ---------------------------------------------------------------------------

RENAL_TIER_FULL = Decimal("50")
RENAL_TIER_MID = Decimal("30")
RENAL_TIER_LOW = Decimal("10")


def renal_tier_factor(crcl):
    """Tier factor evaluated on the ROUNDED clearance."""
    if crcl >= RENAL_TIER_FULL:
        return Decimal("1.00")
    if crcl >= RENAL_TIER_MID:
        return Decimal("0.75")
    if crcl >= RENAL_TIER_LOW:
        return Decimal("0.50")
    return Decimal("0.25")


def renal_dose_adjustment(order, patient, drug, clock_now):
    """Returns (crcl_used_ml_min, renal_adjusted_dose_mg)."""
    age = age_years(patient["date_of_birth"], clock_now)
    ibw = ideal_body_weight(patient["sex"], patient["height_cm"])
    if drug["renal_dosing_policy"] == "ABW_WHEN_OBESE":
        bmi = body_mass_index(patient["weight_kg"], patient["height_cm"])
        if bmi >= Decimal("30"):
            weight_used = round2(ibw + Decimal("0.4") * (Decimal(str(patient["weight_kg"])) - ibw))
        else:
            weight_used = Decimal(str(patient["weight_kg"]))
    else:  # IBW policy
        weight_used = ibw
    crcl = cockcroft_gault(age, weight_used, patient["sex"], patient["scr_mg_dl"])
    factor = renal_tier_factor(crcl)
    adjusted = round2(Decimal(str(order["ordered_dose_mg"])) * factor)
    return crcl, adjusted


# ---------------------------------------------------------------------------
# Dose-rounding step ladder (Section 3.4)
# ---------------------------------------------------------------------------

def step_for(value):
    v = abs(Decimal(value))
    if v < Decimal("1"):
        return Decimal("0.1")
    if v <= Decimal("10"):
        return Decimal("0.5")
    return Decimal("1.0")


def round_to_step(value):
    v = Decimal(value)
    step = step_for(v)
    units = (v / step).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return units * step


def final_dose_ml(renal_adjusted_dose_mg, concentration_mg_per_ml):
    raw = Decimal(str(renal_adjusted_dose_mg)) / Decimal(str(concentration_mg_per_ml))
    return round_to_step(raw)


def substitution_equivalent_dose(ordered_dose_mg, protocol):
    raw = Decimal(str(ordered_dose_mg)) * Decimal(str(protocol["conversion_factor"]))
    stepped = round_to_step(raw)
    lo = Decimal(str(protocol["min_dose_mg"]))
    hi = Decimal(str(protocol["max_dose_mg"]))
    return max(lo, min(hi, stepped))


# ---------------------------------------------------------------------------
# Beyond-use dating (Section 3.5)
# ---------------------------------------------------------------------------

BUD_TABLE = {
    "LOW": {"ROOM": 48, "REFRIGERATED": 336, "FROZEN": 1080},
    "MEDIUM": {"ROOM": 30, "REFRIGERATED": 216, "FROZEN": 1080},
    "HIGH": {"ROOM": 24, "REFRIGERATED": 72, "FROZEN": 1080},
}
MAX_EXTENSION_HOURS = 720

STABILITY_FIELD = {
    "ROOM": "stability_hours_room",
    "REFRIGERATED": "stability_hours_refrigerated",
    "FROZEN": "stability_hours_frozen",
}


def beyond_use_hours(batch, drug, storage_condition):
    if (
        drug.get("has_stability_data")
        and batch.get("documents_stability_source")
        and drug.get(STABILITY_FIELD[storage_condition]) is not None
    ):
        return min(drug[STABILITY_FIELD[storage_condition]], MAX_EXTENSION_HOURS)
    return BUD_TABLE[batch["usp_risk_level"]][storage_condition]


# ---------------------------------------------------------------------------
# Batch yield, waste, and size tiers (Section 3.5)
# ---------------------------------------------------------------------------

TIER_SMALL_MAX = Decimal("25")
TIER_MEDIUM_MAX = Decimal("100")
TOLERANCE_PCT = {"SMALL": Decimal("60"), "MEDIUM": Decimal("30"), "LARGE": Decimal("10")}
MAX_REWORK = 2


def preparation_volume(prep):
    """Step-rounded demand volume of one preparation (round-then-sum part)."""
    order = db.orders[prep["order_id"]]
    drug = db.drugs[prep["drug_product_id"]]
    raw = Decimal(str(order["renal_adjusted_dose_mg"])) / Decimal(str(drug["concentration_mg_per_ml"]))
    return round_to_step(raw)


def batch_preparations(batch_id):
    preps = [p for p in db.preparations.values() if p["batch_id"] == batch_id]
    return sorted(preps, key=lambda p: (p["created_at"], p["_seq"]))


def batch_preparations_by_order(order_id):
    preps = [p for p in db.preparations.values() if p["order_id"] == order_id]
    return sorted(preps, key=lambda p: (p["created_at"], p["_seq"]))


def compute_demand_and_vials(batch):
    """demand_ml over preps in {PLANNED, COMPOUNDED}; vials from first drug."""
    preps = [p for p in batch_preparations(batch["id"]) if p["status"] in ("PLANNED", "COMPOUNDED")]
    demand = Decimal("0")
    for p in preps:
        demand += preparation_volume(p)
    first_drug = db.drugs[batch["_first_drug_id"]]
    vial = Decimal(str(first_drug["vial_size_ml"]))
    vials = int((demand / vial).to_integral_value(rounding=ROUND_CEILING)) if demand > 0 else 0
    return demand, vials


def compute_delivered(batch_id):
    total = Decimal("0")
    for p in batch_preparations(batch_id):
        if p["status"] in ("QA_PASSED", "DISPENSED") and p["prepared_volume_ml"] is not None:
            total += Decimal(str(p["prepared_volume_ml"]))
    return total


def size_tier(total_drawn_ml):
    t = Decimal(str(total_drawn_ml))
    if t < TIER_SMALL_MAX:
        return "SMALL"
    if t <= TIER_MEDIUM_MAX:
        return "MEDIUM"
    return "LARGE"


# ---------------------------------------------------------------------------
# Diversion risk score (Section 3.7)
# ---------------------------------------------------------------------------

WINDOW_DAYS = 30
VARIANCE_DIVISOR = Decimal("2")
W_VARIANCE = Decimal("10")
W_WASTE = Decimal("5")
W_AFTER_HOURS = Decimal("3")
C_II_MULTIPLIER = Decimal("1.5")
HARD_VARIANCE_TRIGGER = 10
ESCALATION_FLOOR = Decimal("80")
OPEN_CASE_THRESHOLD = Decimal("75")
WATCH_THRESHOLD = Decimal("50")


def diversion_risk_score(station_id, subject_staff_id, drug):
    """Returns (score, tier, window_event_count)."""
    now = db.now()
    window_start = now - timedelta(days=WINDOW_DAYS)
    schedule = drug["schedule"]

    window = []
    for ev in db.events.values():
        pocket = db.pockets[ev["pocket_id"]]
        if pocket["station_id"] != station_id:
            continue
        if ev["recorded_by_staff_id"] != subject_staff_id:
            continue
        if db.drugs[pocket["drug_product_id"]]["schedule"] != schedule:
            continue
        if not (window_start <= ev["occurred_at"] <= now):
            continue
        window.append(ev)

    v = Decimal("0")
    hard_trigger = False
    for ev in window:
        if ev["event_type"] == "COUNT":
            variance = abs(ev["observed_count_units"] - ev["expected_on_hand_after"])
            v += variance
            if variance >= HARD_VARIANCE_TRIGGER and schedule == "C_II":
                hard_trigger = True
    z = v / VARIANCE_DIVISOR

    w = 0
    for ev in window:
        if ev["event_type"] == "WASTE":
            pocket = db.pockets[ev["pocket_id"]]
            if db.drugs[pocket["drug_product_id"]]["schedule"] != "NON_CONTROLLED":
                w += 1

    a = 0
    for ev in window:
        hour = ev["occurred_at"].hour
        if hour < 6 or hour >= 22:
            a += 1

    raw = W_VARIANCE * z + W_WASTE * w + W_AFTER_HOURS * a
    if hard_trigger:
        raw = max(raw, ESCALATION_FLOOR)
    if schedule == "C_II":
        raw = raw * C_II_MULTIPLIER
    score = round2(raw)

    if score >= OPEN_CASE_THRESHOLD:
        tier = "OPEN_CASE"
    elif score >= WATCH_THRESHOLD:
        tier = "WATCH"
    else:
        tier = "CLEAR"
    return score, tier, len(window)
