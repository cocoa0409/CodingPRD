"""Every calculation named by PRD 2.6 / section 3 and SCAFFOLD 1.3.

All rounding is ROUND_HALF_UP unless a rule explicitly calls for ceiling or
floor.  Money is integral cents; per-piece money is carried at 4 decimal places
through step 9 of the quote.
"""

import math
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from errors import ApiError

PI = 3.141592653589793

SSE_UNPEENED_FACTOR = 0.20
SSE_PEENED_FACTOR = 0.30
SSU_FACTOR = 0.67
SSY_FACTOR = 0.45

LIFE_TIER_BREAKPOINTS = (1.300, 1.150, 1.050, 1.000)
LIFE_TIER_CYCLES = (10000000, 5000000, 1000000, 250000, 0)

END_COIL_ALLOWANCE_COILS = 2.0
TAIL_LENGTH_MM = {
    "CLOSED_GROUND": 0.0,
    "CLOSED_UNGROUND": 0.0,
    "OPEN": 0.0,
    "HOOK_EXTENSION": 15.0,
    "TORSION_LEG": 25.0,
}

SCRAP_ALLOWANCE_PCT = 0.03
SPC_MIN_SUBGROUP_SIZE = 3
CPK_SIGMA_MULTIPLIER = 3

LABOR_RATE_CENTS_PER_HOUR = 6500
SETUP_FEE_CENTS = 125000
TOOLING_AMORT_CAP_PCT = 0.25
VOLUME_TIER_BREAKPOINTS_CENTS = (50000, 250000, 1000000)
VOLUME_TIER_DISCOUNTS = (0.00, 0.03, 0.06, 0.09)

ACCELERATION_FACTOR = 1.5
MAX_SUBMISSION_ROUNDS = 3

SODERBERG_CLASSES = ("AUTOMOTIVE_SAFETY", "MEDICAL_IMPLANT")

APPLICATION_CLASSES = ("AUTOMOTIVE_SAFETY", "AUTOMOTIVE_NON_SAFETY",
                       "MEDICAL_IMPLANT", "MEDICAL_DEVICE", "INDUSTRIAL")
AMORTIZATION_METHODS = ("FORECAST_BASIS", "ACTUAL_BASIS")
WIRE_MATERIALS = ("MUSIC_WIRE_ASTM_A228", "CHROME_SILICON_A401",
                  "STAINLESS_302_A313", "ELGILOY_AMS5876", "TITANIUM_GR5")
COATINGS = ("NONE", "ZINC_PHOSPHATE", "PASSIVATED", "ELECTROPOLISHED", "PTFE")
FORM_TYPES = ("COMPRESSION", "EXTENSION", "TORSION")
END_TYPES = ("CLOSED_GROUND", "CLOSED_UNGROUND", "OPEN",
             "HOOK_EXTENSION", "TORSION_LEG")
CHAR_CODES = ("FREE_LENGTH", "SPRING_RATE", "OUTER_DIAMETER", "COIL_COUNT",
              "HOOK_POSITION", "LOAD_AT_HEIGHT")
RELEASE_STATUSES = ("DRAFT", "ENG_REVIEW", "PROTOTYPE_RELEASED",
                    "PRODUCTION_RELEASED", "REJECTED", "OBSOLETE")
AMORTIZATION_STATUSES = ("PENDING", "AMORTIZING", "FULLY_AMORTIZED",
                         "WRITTEN_OFF")
CERTIFICATION_STATUSES = ("UNCERTIFIED", "CERTIFIED", "REJECTED")
MACHINE_STATES = ("IDLE", "SETUP", "PRODUCTION")
SETUP_STATUSES = ("SCHEDULED", "ACTIVE", "RELEASED", "SUPERSEDED", "ABORTED")
PROCESS_STATUSES = ("FAI_PENDING", "RUNNING", "COMPLETE", "CANCELLED")
QUALITY_STATUSES = ("OPEN", "SPC_HOLD", "DISPOSITIONED_ACCEPT", "SCRAPPED")
FAI_DISPOSITIONS = ("PENDING", "ACCEPTED", "REJECTED")
HEAT_TREAT_STATES = ("NOT_STARTED", "IN_PROCESS", "COMPLETE")
RECORD_KINDS = ("FAI", "SPC")
CONTROL_STATES = ("IN_CONTROL", "OUT_OF_CONTROL")
BATCH_STATUSES = ("SCHEDULED", "RUNNING", "COMPLETE", "CANCELLED")
SUBMISSION_STATUSES = ("SUBMITTED", "INTERIM_APPROVED", "REVISION_REQUESTED",
                       "APPROVED", "REJECTED_FINAL")
LOT_STATUSES = ("ALLOCATED", "PACKED", "SHIPPED", "QUARANTINED", "RETURNED")
PACKAGING_METHODS = ("BULK_BOX", "BAG_AND_TAG", "TANGLE_FREE_TRAY",
                     "INTERLEAVED_TUBE", "CLEANROOM_DOUBLE_BAG")
QUARANTINE_REASONS = ("SPC_HOLD_CASCADE", "INSPECTOR_ACTION")
DELIVERY_POSTURES = ("BLOCKED", "AT_RISK", "ON_TRACK")

PACKAGING_PERMITTED = {
    "MEDICAL_IMPLANT": ("CLEANROOM_DOUBLE_BAG", "INTERLEAVED_TUBE"),
    "MEDICAL_DEVICE": ("CLEANROOM_DOUBLE_BAG", "INTERLEAVED_TUBE"),
    "AUTOMOTIVE_SAFETY": ("TANGLE_FREE_TRAY", "INTERLEAVED_TUBE"),
    "AUTOMOTIVE_NON_SAFETY": ("TANGLE_FREE_TRAY", "INTERLEAVED_TUBE",
                              "BAG_AND_TAG"),
    "INDUSTRIAL": PACKAGING_METHODS,
}


# ---------------------------------------------------------------------------
# Rounding primitives
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def _exp(places):
    return Decimal(1).scaleb(-places)


def rhu(value, places):
    """Round half up to `places` decimals, returning a float."""
    return float(D(value).quantize(_exp(places), rounding=ROUND_HALF_UP))


def rhu_int(value):
    """Round half up to a whole unit, returning an int."""
    return int(D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def ceil_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_CEILING))


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


# ---------------------------------------------------------------------------
# Engineering stack (PRD 3.2)
# ---------------------------------------------------------------------------
def engineering(design, spec, program):
    """Return every computed engineering field of a design plus the unrounded
    intermediates the fatigue read exposes."""
    d = float(design["wire_diameter_mm"])
    od = float(design["outer_diameter_mm"])
    na = float(design["active_coils"])
    d_mean = od - d

    # --- spring rate
    g_mpa = float(spec["shear_modulus_gpa"]) * 1000.0
    spring_rate = rhu((g_mpa * d ** 4) / (8.0 * (d_mean ** 3) * na), 3)

    # --- corrected shear stress
    spring_index = d_mean / d
    wahl_denominator = 4.0 * spring_index - 3.0
    if abs(wahl_denominator) < 1e-12:
        raise ApiError("ERR_INVALID_REQUEST",
                       "The declared geometry produces a degenerate Wahl correction.")
    wahl = (4.0 * spring_index + 2.0) / wahl_denominator

    def tau(load):
        return wahl * (8.0 * float(load) * d_mean) / (PI * d ** 3)

    tau_max = tau(design["max_working_load_n"])
    tau_min = tau(design["min_working_load_n"])
    tau_alt = (tau_max - tau_min) / 2.0
    tau_mean = (tau_max + tau_min) / 2.0

    # --- fatigue
    tensile = float(spec["tensile_grade_mpa"])
    sse_factor = (SSE_PEENED_FACTOR if design.get("shot_peening_required")
                  else SSE_UNPEENED_FACTOR)
    sse = sse_factor * tensile
    ssu = SSU_FACTOR * tensile
    ssy = SSY_FACTOR * tensile
    den_goodman = tau_alt / sse + tau_mean / ssu
    den_soderberg = tau_alt / sse + tau_mean / ssy
    margin_goodman = rhu(1.0 / den_goodman, 3) if den_goodman > 0 else None
    margin_soderberg = rhu(1.0 / den_soderberg, 3) if den_soderberg > 0 else None
    criterion = ("SODERBERG" if program["application_class"] in SODERBERG_CLASSES
                 else "GOODMAN")
    margin = margin_soderberg if criterion == "SODERBERG" else margin_goodman

    # --- life tier
    life = predicted_life(margin)

    # --- wire mass per piece
    tail = TAIL_LENGTH_MM[design["end_type"]]
    length_mm = PI * d_mean * (na + END_COIL_ALLOWANCE_COILS) + 2.0 * tail
    area_m2 = PI * ((d / 2000.0) ** 2)
    mass = rhu((length_mm / 1000.0) * area_m2 * float(spec["density_kg_per_m3"]), 6)

    # --- tangle risk
    index = rhu(float(design["free_length_mm"]) / od, 3)
    tangle_class = "HIGH" if (index >= 4.000 or
                              design["end_type"] == "HOOK_EXTENSION") else "LOW"

    return {
        "spring_rate_n_per_mm": spring_rate,
        "shear_stress_max_mpa": rhu(tau_max, 2),
        "shear_stress_min_mpa": rhu(tau_min, 2),
        "stress_amplitude_mpa": rhu(tau_alt, 2),
        "mean_stress_mpa": rhu(tau_mean, 2),
        "fatigue_criterion": criterion,
        "fatigue_margin_ratio": margin,
        "predicted_fatigue_life_cycles": life,
        "wire_mass_per_piece_kg": mass,
        "tangle_risk_index": index,
        "tangle_risk_class": tangle_class,
        "_fatigue_margin_goodman": margin_goodman,
        "_fatigue_margin_soderberg": margin_soderberg,
        "_endurance_limit_mpa": rhu(sse, 2),
    }


def predicted_life(margin):
    if margin is None:
        return LIFE_TIER_CYCLES[-1]
    for i, breakpoint_ in enumerate(LIFE_TIER_BREAKPOINTS):
        if margin >= breakpoint_:
            return LIFE_TIER_CYCLES[i]
    return LIFE_TIER_CYCLES[-1]


# ---------------------------------------------------------------------------
# Wire mass ledger (PRD 3.7)
# ---------------------------------------------------------------------------
def wire_mass_required(mass_per_piece_kg, planned_pieces):
    """Pinned order: stored 6dp mass -> * pieces -> * (1 + scrap) -> round 3dp."""
    value = D(mass_per_piece_kg) * D(planned_pieces) * (Decimal(1) + D(SCRAP_ALLOWANCE_PCT))
    return rhu(value, 3)


def wire_consumed(mass_per_piece_kg, pieces):
    return rhu(D(mass_per_piece_kg) * D(pieces), 3)


def kg(value):
    return rhu(value, 3)


def kg_sum(*values):
    total = Decimal(0)
    for value in values:
        total += D(value)
    return rhu(total, 3)


# ---------------------------------------------------------------------------
# Capability statistics (PRD 3.7 / 3.8)
# ---------------------------------------------------------------------------
def _mean(values):
    return sum(values) / float(len(values))


def _sigma(values):
    n = len(values)
    if n < 2:
        return 0.0
    mu = _mean(values)
    return math.sqrt(sum((x - mu) ** 2 for x in values) / float(n - 1))


def _capability_index(values, lsl, usl):
    mu = _mean(values)
    sigma = _sigma(values)
    if sigma <= 0.0:
        return 999.999
    distance = min(float(usl) - mu, mu - float(lsl))
    return rhu(distance / (CPK_SIGMA_MULTIPLIER * sigma), 3)


def capability(measurements, characteristic, pooled=None):
    """Compute one InspectionRecord's statistics.

    `pooled` is the full pooled sample (every measurement of every SPC record of
    the same run and characteristic including this one) or None for an FAI row.
    """
    lsl = float(characteristic["lsl"])
    usl = float(characteristic["usl"])
    n = len(measurements)
    mean_unrounded = _mean(measurements)
    sigma_unrounded = _sigma(measurements)
    cpk = _capability_index(measurements, lsl, usl)
    ppk = None if pooled is None else _capability_index(pooled, lsl, usl)
    out_of_control = (cpk < float(characteristic["cpk_floor"]) or
                      any(x > usl or x < lsl for x in measurements))
    return {
        "subgroup_size": n,
        "mean_value": rhu(mean_unrounded, 4),
        "sigma_value": rhu(sigma_unrounded, 6),
        "cpk_value": cpk,
        "ppk_value": ppk,
        "control_state": "OUT_OF_CONTROL" if out_of_control else "IN_CONTROL",
    }


# ---------------------------------------------------------------------------
# Quoting (PRD 3.11, eleven pinned steps)
# ---------------------------------------------------------------------------
def volume_discount(subtotal_cents):
    if subtotal_cents < VOLUME_TIER_BREAKPOINTS_CENTS[0]:
        return VOLUME_TIER_DISCOUNTS[0]
    if subtotal_cents < VOLUME_TIER_BREAKPOINTS_CENTS[1]:
        return VOLUME_TIER_DISCOUNTS[1]
    if subtotal_cents < VOLUME_TIER_BREAKPOINTS_CENTS[2]:
        return VOLUME_TIER_DISCOUNTS[2]
    return VOLUME_TIER_DISCOUNTS[3]


def quote(design, spec, tooling, quoted_qty):
    # 1
    material_pp = D(design["wire_mass_per_piece_kg"]) * D(spec["cost_per_kg_cents"])
    material_pp = D(rhu(material_pp, 4))
    # 2
    labor_pp = (D(design["cycle_seconds_per_piece"]) / D(3600)) * D(LABOR_RATE_CENTS_PER_HOUR)
    labor_pp = D(rhu(labor_pp, 4))
    # 3
    base_unit = D(rhu(material_pp + labor_pp, 4))
    # 4
    subtotal = rhu_int(base_unit * D(quoted_qty))
    # 5
    discount = volume_discount(subtotal)
    # 6
    discounted_unit = D(rhu(base_unit * (Decimal(1) - D(discount)), 4))
    # 7
    unamortized = tooling["unamortized_cents"] if tooling else 0
    amort_raw = ceil_int(D(unamortized) / D(quoted_qty))
    # 8
    amort_cap = floor_int(D(TOOLING_AMORT_CAP_PCT) * discounted_unit)
    # 9
    amort_pp = min(amort_raw, amort_cap)
    # 10
    unit_price = rhu_int(discounted_unit + D(amort_pp))
    # 11
    total = unit_price * quoted_qty + SETUP_FEE_CENTS
    return {
        "quoted_qty": quoted_qty,
        "quoted_pre_discount_subtotal_cents": subtotal,
        "quoted_volume_discount_pct": discount,
        "quoted_tooling_amort_per_piece_cents": amort_pp,
        "quoted_unit_price_cents": unit_price,
        "quoted_total_cents": total,
    }


# ---------------------------------------------------------------------------
# Tooling amortization recovery (PRD 3.4)
# ---------------------------------------------------------------------------
def forecast_recovery(piece_count, amort_per_piece_cents, unamortized_cents):
    if amort_per_piece_cents is None:
        amort_per_piece_cents = 0
    return min(piece_count * amort_per_piece_cents, unamortized_cents)


def actual_recovery(piece_count, unamortized_cents, open_commitment_pieces):
    basis = open_commitment_pieces if open_commitment_pieces > 0 else 1
    raw = ceil_int(D(unamortized_cents) * D(ACCELERATION_FACTOR) * D(piece_count) / D(basis))
    return min(raw, unamortized_cents)


def recovery(program, tooling, piece_count, open_commitment_pieces):
    if program["amortization_method"] == "FORECAST_BASIS":
        return forecast_recovery(piece_count, tooling.get("amort_per_piece_cents"),
                                 tooling["unamortized_cents"])
    return actual_recovery(piece_count, tooling["unamortized_cents"],
                           open_commitment_pieces)


def amort_per_piece(original_cost_cents, basis_pieces):
    basis = basis_pieces if basis_pieces and basis_pieces > 0 else 1
    return ceil_int(D(original_cost_cents) / D(basis))
