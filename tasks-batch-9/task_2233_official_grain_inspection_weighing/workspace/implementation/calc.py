"""Pure calculations (SCAFFOLD §1.3 / PRD §2.6, §3.5–§3.8)."""

from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR, ROUND_CEILING

D = Decimal

OFFICIAL_MOISTURE_BASIS_PCT = D("13.0")
POUNDS_PER_BUSHEL = {"CORN": D(56), "SOYBEANS": D(60)}

FACTOR_KEYS = (
    "test_weight_lbs_per_bushel",
    "moisture_pct",
    "damaged_total_pct",
    "heat_damaged_pct",
    "foreign_material_pct",
)

CANONICAL_FACTOR_ORDER = (
    ("TEST_WEIGHT", "test_weight_lbs_per_bushel", "min_test_weight"),
    ("MOISTURE", "moisture_pct", "max_moisture"),
    ("DAMAGED_TOTAL", "damaged_total_pct", "max_damaged_total"),
    ("HEAT_DAMAGED", "heat_damaged_pct", "max_heat_damaged"),
    ("FOREIGN_MATERIAL", "foreign_material_pct", "max_foreign_material"),
)

COMMODITY_TABLES = {
    "CORN": [
        {"grade": "US_NO_1", "min_test_weight": D("56.0"), "max_moisture": D("14.0"),
         "max_damaged_total": D("3.0"), "max_heat_damaged": D("0.1"), "max_foreign_material": D("2.0")},
        {"grade": "US_NO_2", "min_test_weight": D("54.0"), "max_moisture": D("15.0"),
         "max_damaged_total": D("5.0"), "max_heat_damaged": D("0.2"), "max_foreign_material": D("3.0")},
        {"grade": "US_NO_3", "min_test_weight": D("52.0"), "max_moisture": D("17.5"),
         "max_damaged_total": D("7.0"), "max_heat_damaged": D("0.5"), "max_foreign_material": D("4.0")},
        {"grade": "US_NO_4", "min_test_weight": D("49.0"), "max_moisture": D("20.0"),
         "max_damaged_total": D("10.0"), "max_heat_damaged": D("1.0"), "max_foreign_material": D("5.0")},
        {"grade": "US_NO_5", "min_test_weight": D("46.0"), "max_moisture": D("23.0"),
         "max_damaged_total": D("15.0"), "max_heat_damaged": D("3.0"), "max_foreign_material": D("7.0")},
    ],
    "SOYBEANS": [
        {"grade": "US_NO_1", "min_test_weight": D("56.0"), "max_moisture": D("13.0"),
         "max_damaged_total": D("2.0"), "max_heat_damaged": D("0.2"), "max_foreign_material": D("1.0")},
        {"grade": "US_NO_2", "min_test_weight": D("54.0"), "max_moisture": D("14.0"),
         "max_damaged_total": D("3.0"), "max_heat_damaged": D("0.5"), "max_foreign_material": D("2.0")},
        {"grade": "US_NO_3", "min_test_weight": D("52.0"), "max_moisture": D("16.0"),
         "max_damaged_total": D("5.0"), "max_heat_damaged": D("1.0"), "max_foreign_material": D("3.0")},
        {"grade": "US_NO_4", "min_test_weight": D("49.0"), "max_moisture": D("18.0"),
         "max_damaged_total": D("8.0"), "max_heat_damaged": D("3.0"), "max_foreign_material": D("5.0")},
    ],
}


# --------------------------------------------------------------------------
# rounding primitives
# --------------------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    return D(str(value))


def round_half_up(value, places=0):
    quantum = D(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_FLOOR))


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


def num(value, places):
    """Render a Decimal as a JSON number with the given scale."""
    return float(round_half_up(value, places))


# --------------------------------------------------------------------------
# grade determination
# --------------------------------------------------------------------------

def _satisfies(rounded, grade):
    return (
        rounded["test_weight_lbs_per_bushel"] >= grade["min_test_weight"]
        and rounded["moisture_pct"] <= grade["max_moisture"]
        and rounded["damaged_total_pct"] <= grade["max_damaged_total"]
        and rounded["heat_damaged_pct"] <= grade["max_heat_damaged"]
        and rounded["foreign_material_pct"] <= grade["max_foreign_material"]
    )


def _violates(rounded, grade, factor_key, limit_key):
    if factor_key == "test_weight_lbs_per_bushel":
        return rounded[factor_key] < grade[limit_key]
    return rounded[factor_key] > grade[limit_key]


def grade_determination(commodity, observed):
    """Return (rounded_factors, assigned_grade, limiting_factor)."""
    table = COMMODITY_TABLES[commodity]
    rounded = {key: round_half_up(observed[key], 1) for key in FACTOR_KEYS}

    index = None
    for position, grade in enumerate(table):
        if _satisfies(rounded, grade):
            index = position
            break

    if index == 0:
        assigned = table[0]["grade"]
        limiting = "NONE"
    else:
        if index is None:
            assigned = "SAMPLE_GRADE"
            better = table[-1]
        else:
            assigned = table[index]["grade"]
            better = table[index - 1]
        limiting = "NONE"
        for name, factor_key, limit_key in CANONICAL_FACTOR_ORDER:
            if _violates(rounded, better, factor_key, limit_key):
                limiting = name
                break

    rounded_out = {key: float(rounded[key]) for key in FACTOR_KEYS}
    return rounded_out, assigned, limiting


# --------------------------------------------------------------------------
# official net weight
# --------------------------------------------------------------------------

def official_net_weight(drafts, dockage_pct, commodity):
    rate = dec(dockage_pct)
    dockage_total = 0
    net_total = 0
    gross_net_total = 0
    for draft in drafts:
        gross_net = draft["gross_lbs"] - draft["tare_lbs"]
        gross_net_total += gross_net
        deduction = int(round_half_up(D(gross_net) * rate / D(100), 0))
        dockage_total += deduction
        net_total += gross_net - deduction
    aggregate_dockage = int(round_half_up(D(gross_net_total) * rate / D(100), 0))
    provisional = gross_net_total - aggregate_dockage
    net_bushels = round_half_up(D(net_total) / POUNDS_PER_BUSHEL[commodity], 2)
    return {
        "dockage_lbs": dockage_total,
        "net_lbs": net_total,
        "provisional_net_lbs": provisional,
        "rounding_variance_lbs": provisional - net_total,
        "net_bushels": float(net_bushels),
    }


# --------------------------------------------------------------------------
# protein basis conversion
# --------------------------------------------------------------------------

def protein_conversion(protein_pct_as_is, moisture_source_pct):
    as_is = dec(protein_pct_as_is)
    moisture = dec(moisture_source_pct)
    reported = round_half_up(
        as_is * (D(100) - OFFICIAL_MOISTURE_BASIS_PCT) / (D(100) - moisture), 2
    )
    adjustment = round_half_up(reported - as_is, 2)
    return float(reported), float(adjustment)


# --------------------------------------------------------------------------
# fee assessment
# --------------------------------------------------------------------------

CERTIFICATE_CLASSES = {
    "GRADE": ("GRADING",),
    "WEIGHT": ("WEIGHING",),
    "COMBINED": ("GRADING", "WEIGHING"),
    "EXPORT_CARGO": ("GRADING", "WEIGHING", "EXPORT_SUPERVISION"),
    "APPEAL_GRADE": (),
}

STANDARD_HOURS_START = 7
STANDARD_HOURS_END = 17


def applicable_classes(certificate_type, requested_services):
    classes = list(CERTIFICATE_CLASSES[certificate_type])
    if certificate_type == "APPEAL_GRADE":
        return classes
    if "PROTEIN" in requested_services and certificate_type != "WEIGHT":
        classes.append("PROTEIN")
    return classes


def is_overtime(issued_at):
    return not (STANDARD_HOURS_START <= issued_at.hour < STANDARD_HOURS_END)


def volume_tier_bp(pre_discount_cents):
    if pre_discount_cents >= 150000:
        return 1000
    if pre_discount_cents >= 50000:
        return 500
    return 0


def fee_assessment(schedules, certified_quantity_bushels, overtime_applied, fee_multiplier_bp):
    """`schedules` is the list of applicable ACTIVE FeeSchedule rows."""
    if not schedules:
        return 0
    thousands = ceil_int(dec(certified_quantity_bushels) / D(1000))
    base_sum = sum(s["base_fee_cents"] for s in schedules)
    rate_sum = sum(s["per_thousand_bushel_rate_cents"] for s in schedules)
    service_cents = base_sum + thousands * rate_sum
    if overtime_applied:
        max_bp = max(s["overtime_multiplier_bp"] for s in schedules)
        overtime_cents = int(round_half_up(D(service_cents) * D(max_bp) / D(10000), 0))
    else:
        overtime_cents = 0
    pre_discount = service_cents + overtime_cents
    tier_bp = volume_tier_bp(pre_discount)
    discount_cents = floor_int(D(pre_discount) * D(tier_bp) / D(10000))
    discounted = pre_discount - discount_cents
    adjustment = int(round_half_up(D(discounted) * D(fee_multiplier_bp - 10000) / D(10000), 0))
    floor_fee = max(s["minimum_fee_cents"] for s in schedules)
    return max(discounted + adjustment, floor_fee)


# --------------------------------------------------------------------------
# inspector performance score
# --------------------------------------------------------------------------

APPEAL_REVERSAL_WEIGHT = 18
CHECK_DEVIATION_WEIGHT = 10
LATE_CERTIFICATE_WEIGHT = 3
TRAINING_CREDIT_CAP = 12
TRAINING_HOURS_PER_CREDIT = 10
ACTIVATION_MINIMUM_SCORE = 80
AUTO_SUSPEND_BELOW = 70
LATE_CERTIFICATE_THRESHOLD_HOURS = 48
DEVIATION_COUNTING_THRESHOLD_PCT = D("0.25")


def performance_score(reversals, deviations, late_certificates, training_hours):
    credit = min(TRAINING_CREDIT_CAP, floor_int(dec(training_hours) / D(TRAINING_HOURS_PER_CREDIT)))
    raw = (
        100
        - APPEAL_REVERSAL_WEIGHT * reversals
        - CHECK_DEVIATION_WEIGHT * deviations
        - LATE_CERTIFICATE_WEIGHT * late_certificates
        + credit
    )
    return max(0, min(100, raw))


# --------------------------------------------------------------------------
# instrument comparison programme
# --------------------------------------------------------------------------

SINGLE_CHECK_TOLERANCE_PCT = D("0.50")
ROLLING_BIAS_OUT_OF_TOLERANCE_PCT = D("0.30")
ROLLING_BIAS_DRIFT_WATCH_PCT = D("0.15")
ROLLING_WINDOW_SIZE = 3
WITHDRAWAL_CONSECUTIVE_FAILURES = 3


def comparison_deviation(instrument_reading_pct, reference_value_pct):
    return round_half_up(dec(instrument_reading_pct) - dec(reference_value_pct), 2)


def rolling_bias(deviations):
    if not deviations:
        return None
    total = sum(dec(value) for value in deviations)
    return round_half_up(total / D(len(deviations)), 2)


def comparison_resolution(deviation_pct, bias_pct):
    deviation = abs(dec(deviation_pct))
    bias = abs(dec(bias_pct)) if bias_pct is not None else D(0)
    if deviation > SINGLE_CHECK_TOLERANCE_PCT or bias > ROLLING_BIAS_OUT_OF_TOLERANCE_PCT:
        return "OUT_OF_TOLERANCE"
    if bias > ROLLING_BIAS_DRIFT_WATCH_PCT:
        return "DRIFT_WATCH"
    return "APPROVED"


def counts_against_inspector(deviation_pct):
    return abs(dec(deviation_pct)) > DEVIATION_COUNTING_THRESHOLD_PCT


# --------------------------------------------------------------------------
# appeal panel
# --------------------------------------------------------------------------

PANEL_SIZES = {"REINSPECTION": 1, "APPEAL": 3, "BOARD_APPEAL": 5}
ROUND_NUMBERS = {"REINSPECTION": 1, "APPEAL": 2, "BOARD_APPEAL": 3}
FILING_WINDOW_DAYS = {"REINSPECTION": 5, "APPEAL": 10, "BOARD_APPEAL": 20}
