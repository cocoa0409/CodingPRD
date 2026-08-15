"""Calculation rules and variety constants (PRD section 3, SCAFFOLD 1.3).

All computed mass/percentage values are rounded half-up to exactly two
decimal places and emitted as JSON numbers. Decimal arithmetic throughout.
"""

from decimal import ROUND_HALF_UP, Decimal

VARIETIES = ("CHEDDAR", "COLBY", "BRICK", "MUENSTER")
ADDITIVE_KINDS = ("CULTURE", "COAGULANT")
CHANNELS = ("PRIVATE_LABEL", "BRANDED")

# Variety-pinned constants ---------------------------------------------------
STEPS_REQUIRED = {"CHEDDAR": 8, "COLBY": 6, "BRICK": 5, "MUENSTER": 5}
MIN_AGE_DAYS = {"CHEDDAR": 60, "COLBY": 0, "BRICK": 30, "MUENSTER": 21}
TURN_INTERVAL_DAYS = {"CHEDDAR": 7, "COLBY": 5, "BRICK": 3, "MUENSTER": 3}
WHEEL_WEIGHT = {
    "CHEDDAR": Decimal("18.0"),
    "COLBY": Decimal("12.0"),
    "BRICK": Decimal("2.5"),
    "MUENSTER": Decimal("3.0"),
}
FAT_RECOVERY = {
    "CHEDDAR": Decimal("0.93"),
    "COLBY": Decimal("0.92"),
    "BRICK": Decimal("0.91"),
    "MUENSTER": Decimal("0.90"),
}
PROTEIN_RECOVERY = {
    "CHEDDAR": Decimal("0.78"),
    "COLBY": Decimal("0.77"),
    "BRICK": Decimal("0.76"),
    "MUENSTER": Decimal("0.75"),
}
OTHER_SOLIDS_FACTOR = Decimal("5.7")
TARGET_MOISTURE = {
    "CHEDDAR": Decimal("0.39"),
    "COLBY": Decimal("0.40"),
    "BRICK": Decimal("0.42"),
    "MUENSTER": Decimal("0.44"),
}

# Grading bands ---------------------------------------------------------------
VARIETY_MOISTURE_MAX = {
    "CHEDDAR": Decimal("39.0"),
    "COLBY": Decimal("40.0"),
    "BRICK": Decimal("44.0"),
    "MUENSTER": Decimal("46.0"),
}
VARIETY_MOISTURE_GRADE_A_MAX = {
    "CHEDDAR": Decimal("37.0"),
    "COLBY": Decimal("38.0"),
    "BRICK": Decimal("42.0"),
    "MUENSTER": Decimal("44.0"),
}
VARIETY_FDB_MIN = {
    "CHEDDAR": Decimal("50.0"),
    "COLBY": Decimal("50.0"),
    "BRICK": Decimal("50.0"),
    "MUENSTER": Decimal("48.0"),
}

# Aging-room environment band -------------------------------------------------
TEMP_MIN_C = Decimal("7.0")
TEMP_MAX_C = Decimal("13.0")
HUMIDITY_MIN_PCT = Decimal("80.0")
HUMIDITY_MAX_PCT = Decimal("90.0")

SCC_MAX = 400000
WASTE_TOLERANCE_PCT = Decimal("0.02")

_CENT = Decimal("0.01")


def D(x):
    """Exact decimal view of a JSON number."""
    return Decimal(str(x))


def round2(d):
    return d.quantize(_CENT, rounding=ROUND_HALF_UP)


def f2(d):
    """Round half-up to 2dp and return a JSON number."""
    return float(round2(d))


# --- yield accounting (PRD 3.5) ----------------------------------------------

def provisional_yield_pct(variety, liters_committed, fat_pct, protein_pct):
    liters = D(liters_committed)
    fat_kg = liters * D(fat_pct) / 100
    protein_kg = liters * D(protein_pct) / 100
    recovered_fat = fat_kg * FAT_RECOVERY[variety]
    recovered_protein = protein_kg * PROTEIN_RECOVERY[variety]
    solids = recovered_fat + recovered_protein + OTHER_SOLIDS_FACTOR * liters / 100
    cheese_kg = solids / (Decimal("1") - TARGET_MOISTURE[variety])
    return f2(cheese_kg / liters * 100)


def actual_yield_pct(green_weight_kg, liters_committed):
    return f2(D(green_weight_kg) / D(liters_committed) * 100)


# --- whey stream (PRD 3.5) -----------------------------------------------------

def whey_fields(total_whey_kg, valorized_kg):
    """Pinned order: disposed -> valorization rate, each rounded 2dp half-up."""
    total = D(total_whey_kg)
    valorized = D(valorized_kg)
    disposed = round2(total - valorized)
    if total == 0:
        rate = Decimal("0.00")
    else:
        rate = round2(valorized / total * 100)
    return float(disposed), float(rate)


# --- grade assignment (PRD 3.7) ------------------------------------------------

def assign_grade(variety, moisture_pct, fat_dry_basis_pct, body_score, flavor_score):
    """Top-down ladder; first matching rung wins. Boundaries are exact."""
    moisture = D(moisture_pct)
    fdb = D(fat_dry_basis_pct)
    if body_score <= 2 or flavor_score <= 2:
        return "CONDEMNED"
    if moisture > VARIETY_MOISTURE_MAX[variety]:
        return "DOWNGRADE"
    if fdb < VARIETY_FDB_MIN[variety]:
        return "DOWNGRADE"
    if (
        body_score >= 8
        and flavor_score >= 8
        and moisture <= VARIETY_MOISTURE_GRADE_A_MAX[variety]
    ):
        return "GRADE_A"
    return "GRADE_B"


# --- aging room posture (PRD 3.1) ------------------------------------------------

def derive_posture(room):
    """DEVIATION (environment) is checked before FULL (capacity); a
    DECOMMISSIONED room's posture is frozen and never re-derived."""
    if room["status"] == "DECOMMISSIONED":
        return room["posture"]
    temp = D(room["temp_c"])
    humidity = D(room["humidity_pct"])
    if temp < TEMP_MIN_C or temp > TEMP_MAX_C or humidity < HUMIDITY_MIN_PCT or humidity > HUMIDITY_MAX_PCT:
        return "DEVIATION"
    if room["wheels_present"] == room["capacity_wheels"]:
        return "FULL"
    return "AVAILABLE"


# --- aging projection (PRD 3.6) --------------------------------------------------

def age_days(entered_at_dt, now_dt):
    """Whole days, floored, never rounded up."""
    return int((now_dt - entered_at_dt).total_seconds() // 86400)


def turns_due(last_turned_dt, now_dt, variety):
    days_since_turn = int((now_dt - last_turned_dt).total_seconds() // 86400)
    return days_since_turn >= TURN_INTERVAL_DAYS[variety]


# --- cut-and-wrap reconciliation (PRD 3.8) ---------------------------------------

def cut_wrap_figures(variety, wheels_in, finished_case_weight_kg, trim_waste_kg):
    """Input weight is exact (integer wheels x exact wheel weight, no
    intermediate rounding); the gap derives from it. Stored figures are
    rounded 2dp half-up; comparisons elsewhere use the exact values."""
    input_exact = D(wheels_in) * WHEEL_WEIGHT[variety]
    gap_exact = input_exact - D(finished_case_weight_kg) - D(trim_waste_kg)
    return input_exact, gap_exact, f2(input_exact), f2(gap_exact)
