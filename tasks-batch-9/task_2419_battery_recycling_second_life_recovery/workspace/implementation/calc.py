"""Calculation rules -- SCAFFOLD `calculations` / `global_constants`, PRD sections 3.2 - 3.9."""

from datetime import timedelta
from decimal import Decimal as D

from core import ApiError, db, q0, q2, q3, q4

# --- global constants -------------------------------------------------------

SOC_PACKAGING_LIMIT_PCT = D("30.0")
CHEMISTRY_FAMILY_MAP = {
    "NMC622": "NICKEL_RICH",
    "NCA": "NICKEL_RICH",
    "LMO": "NICKEL_RICH",
    "LFP": "IRON_PHOSPHATE",
}
HYDROMET_ONLY_METALS = ("NI", "CO", "LI")

METALS = ("NI", "CO", "LI", "CU", "MN", "GRAPHITE")
CHEMISTRIES = ("NMC622", "NCA", "LMO", "LFP")
FAMILIES = ("NICKEL_RICH", "IRON_PHOSPHATE")

# --- module_second_life_score ----------------------------------------------

CYCLE_PENALTY_CAP_POINTS = D("20.0")
CYCLES_PER_POINT = D("200")
IMBALANCE_WEIGHT = D("0.80")
GRADE_A_FLOOR = D("80.0")
GRADE_B_FLOOR = D("70.0")
GRADE_C_FLOOR = D("60.0")

# --- quality_deduction_pct -------------------------------------------------

MISLABEL_PENALTY_PCT = D("0.04")
MOISTURE_FREE_PP = D("2.0")
MOISTURE_RATE_PER_PP = D("0.01")
MOISTURE_COMPONENT_CAP = D("0.06")
FOREIGN_FREE_PP = D("1.5")
FOREIGN_RATE_PER_PP = D("0.02")
FOREIGN_COMPONENT_CAP = D("0.05")
STRIKE_ESCALATION_THRESHOLD = 3
REPEAT_OFFENDER_MULTIPLIER = D("1.5")
TOTAL_DEDUCTION_CAP = D("0.20")

# --- feedstock_payable_value ----------------------------------------------

PAYABLE_METALS = ("NI", "CO", "LI", "CU")
PAYABLE_SHARE = {"NI": D("0.70"), "CO": D("0.70"), "LI": D("0.55"), "CU": D("0.40")}
NOMINAL_RECOVERY = {
    "NMC622": {"NI": D("0.95"), "CO": D("0.95"), "LI": D("0.80"), "CU": D("0.90")},
    "NCA": {"NI": D("0.95"), "CO": D("0.90"), "LI": D("0.80"), "CU": D("0.90")},
    "LMO": {"NI": D("0.00"), "CO": D("0.00"), "LI": D("0.75"), "CU": D("0.90")},
    "LFP": {"NI": D("0.00"), "CO": D("0.00"), "LI": D("0.75"), "CU": D("0.90")},
}
DECLARED_PCT_FIELD = {
    "NI": "declared_ni_pct",
    "CO": "declared_co_pct",
    "LI": "declared_li_pct",
    "CU": "declared_cu_pct",
}

# --- settlement_net_payable ------------------------------------------------

PROCESSING_FEE_TIERS = (
    (500000, D("0.12")),
    (2000000, D("0.09")),
    (None, D("0.06")),
)
HAZMAT_FLAT_CENTS = 2500
HAZMAT_PER_KG_CENTS = D("6")
HAZMAT_CAP_PCT = D("0.05")

# --- lot_mass_balance ------------------------------------------------------

MASS_BALANCE_FLOOR_PCT = D("97.00")
PASSPORT_MIN_CONTENT_PCT = D("35.00")

# --- assay_variance_pp -----------------------------------------------------

DISPUTE_TOLERANCE_PP = D("0.50")
SEVERE_VARIANCE_PP = D("2.00")
DISPUTE_ROUND_LIMIT = 3

# --- campaign_line_occupation ---------------------------------------------

DEFAULT_CHANGEOVER_BUFFER_HOURS = 6

# --- facility_capacity_projection -----------------------------------------

LOOKBACK_DAYS = 30
GROWTH_RATE_PER_DAY = D("0.004")


# ===========================================================================
# module_second_life_score
# ===========================================================================


def module_second_life_score(module, scoring_variant):
    if scoring_variant == "CONSERVATIVE":
        soh = module["min_cell_capacity_pct"]
    else:
        soh = module["mean_cell_capacity_pct"]
    cycle_penalty = D(module["cycle_count"]) / CYCLES_PER_POINT
    if cycle_penalty > CYCLE_PENALTY_CAP_POINTS:
        cycle_penalty = CYCLE_PENALTY_CAP_POINTS
    spread = module["mean_cell_capacity_pct"] - module["min_cell_capacity_pct"]
    imbalance_penalty = spread * IMBALANCE_WEIGHT
    return q2(soh - cycle_penalty - imbalance_penalty)


def grade_for_score(score):
    if score >= GRADE_A_FLOOR:
        return "A"
    if score >= GRADE_B_FLOOR:
        return "B"
    if score >= GRADE_C_FLOOR:
        return "C"
    return "D"


DERIVED_DISPOSITION = {
    "A": "REFURBISH",
    "B": "SECOND_LIFE",
    "C": "SECOND_LIFE",
    "D": "MATERIAL_RECOVERY",
}

OVERRIDE_ALLOWED_GRADES = {
    "REFURBISH": ("A", "B"),
    "SECOND_LIFE": ("A", "B", "C"),
    "MATERIAL_RECOVERY": ("A", "B", "C", "D"),
}


# ===========================================================================
# quality_deduction_pct
# ===========================================================================


def quality_deduction_pct(intake, strike_count):
    total = D(0)
    identified = intake.get("identified_chemistry")
    if identified is not None and identified != intake["declared_chemistry"]:
        total += MISLABEL_PENALTY_PCT
    moisture_excess = intake["moisture_pct"] - MOISTURE_FREE_PP
    if moisture_excess < 0:
        moisture_excess = D(0)
    moisture_component = moisture_excess * MOISTURE_RATE_PER_PP
    if moisture_component > MOISTURE_COMPONENT_CAP:
        moisture_component = MOISTURE_COMPONENT_CAP
    total += moisture_component
    foreign_excess = intake["foreign_material_pct"] - FOREIGN_FREE_PP
    if foreign_excess < 0:
        foreign_excess = D(0)
    foreign_component = foreign_excess * FOREIGN_RATE_PER_PP
    if foreign_component > FOREIGN_COMPONENT_CAP:
        foreign_component = FOREIGN_COMPONENT_CAP
    total += foreign_component
    if strike_count >= STRIKE_ESCALATION_THRESHOLD:
        total = total * REPEAT_OFFENDER_MULTIPLIER
    if total > TOTAL_DEDUCTION_CAP:
        total = TOTAL_DEDUCTION_CAP
    return q4(total)


# ===========================================================================
# feedstock_payable_value
# ===========================================================================


def lookup_index_price(metal, price_date):
    """Newest quote effective at or before price_date (effective_date desc, created_at desc)."""
    candidates = [
        p
        for p in db.prices.values()
        if p["metal"] == metal and p["effective_date"] <= price_date
    ]
    if not candidates:
        return None
    candidates.sort(
        key=lambda p: (p["effective_date"], p["created_at"], p["_seq"]), reverse=True
    )
    return candidates[0]


def price_lines(contained_by_metal, factor_by_metal, price_date):
    """Per-metal payable line; each line is rounded to whole cents BEFORE the sum."""
    lines = []
    for metal in PAYABLE_METALS:
        contained = contained_by_metal[metal]
        factor = factor_by_metal[metal]
        share = PAYABLE_SHARE[metal]
        if contained * factor == 0:
            lines.append(
                {
                    "metal": metal,
                    "contained_kg": contained,
                    "unit_price_cents_per_kg": None,
                    "payable_share": share,
                    "line_cents": 0,
                }
            )
            continue
        quote = lookup_index_price(metal, price_date)
        if quote is None:
            raise ApiError("ERR_INDEX_PRICE_UNAVAILABLE")
        unit_price = quote["price_cents_per_kg"]
        line_cents = q0(contained * factor * D(unit_price) * share)
        lines.append(
            {
                "metal": metal,
                "contained_kg": contained,
                "unit_price_cents_per_kg": unit_price,
                "payable_share": share,
                "line_cents": line_cents,
            }
        )
    gross_cents = sum(line["line_cents"] for line in lines)
    return lines, gross_cents


def provisional_contained(intake):
    contained = {}
    for metal in PAYABLE_METALS:
        pct = intake[DECLARED_PCT_FIELD[metal]]
        contained[metal] = q3(intake["net_mass_kg"] * pct / D(100))
    return contained


def provisional_factors(intake):
    chemistry = intake.get("identified_chemistry") or intake["declared_chemistry"]
    table = NOMINAL_RECOVERY[chemistry]
    return {metal: table[metal] for metal in PAYABLE_METALS}


# ===========================================================================
# settlement_net_payable -- the mandatory seven-step waterfall
# ===========================================================================


def processing_fee_pct_for(gross_cents):
    for upper, pct in PROCESSING_FEE_TIERS:
        if upper is None or gross_cents < upper:
            return pct
    return PROCESSING_FEE_TIERS[-1][1]


def waterfall(gross_cents, intake, deduction_pct):
    fee_pct = processing_fee_pct_for(gross_cents)
    fee_cents = q0(D(gross_cents) * fee_pct)
    deduction_cents = q0(D(gross_cents) * deduction_pct)
    pre_surcharge = gross_cents - fee_cents - deduction_cents
    flat_candidate = HAZMAT_FLAT_CENTS + q0(intake["net_mass_kg"] * HAZMAT_PER_KG_CENTS)
    cap_candidate = q0(D(pre_surcharge) * HAZMAT_CAP_PCT)
    hazmat = flat_candidate if flat_candidate < cap_candidate else cap_candidate
    return {
        "processing_fee_pct": fee_pct,
        "processing_fee_cents": fee_cents,
        "quality_deduction_pct": deduction_pct,
        "quality_deduction_cents": deduction_cents,
        "pre_surcharge_net_cents": pre_surcharge,
        "hazmat_surcharge_cents": hazmat,
        "net_payable_cents": pre_surcharge - hazmat,
    }


# ===========================================================================
# lot_mass_balance
# ===========================================================================


def lot_outputs(lot_id):
    rows = [o for o in db.outputs.values() if o["lot_id"] == lot_id]
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def lot_recovered_mass(lot_id):
    total = D(0)
    for output in lot_outputs(lot_id):
        total += output["recovered_mass_kg"]
    return q3(total)


def lot_mass_balance(lot, residue_mass_kg):
    recovered = lot_recovered_mass(lot["id"])
    accounted = q3(recovered + residue_mass_kg)
    charged = lot["charged_mass_kg"]
    unaccounted = q3(charged - accounted)
    if charged == 0:
        mass_balance = q2(0)
        recycled_content = q2(0)
    else:
        mass_balance = q2(accounted / charged * D(100))
        recycled_content = q2(recovered / charged * D(100))
    return {
        "recovered_mass_kg": recovered,
        "accounted_mass_kg": accounted,
        "unaccounted_mass_kg": unaccounted,
        "mass_balance_pct": mass_balance,
        "recycled_content_pct": recycled_content,
    }


# ===========================================================================
# assay_variance_pp
# ===========================================================================


def assay_variance_pp(intake, lines):
    largest = None
    net = intake["net_mass_kg"]
    for line in lines:
        metal = line["metal"]
        if metal not in PAYABLE_METALS:
            continue
        if net == 0:
            final_pct = D(0)
        else:
            final_pct = line["contained_kg"] / net * D(100)
        declared = intake[DECLARED_PCT_FIELD[metal]]
        variance = q2(abs(declared - final_pct))
        if largest is None or variance > largest:
            largest = variance
    return largest


# ===========================================================================
# campaign_line_occupation
# ===========================================================================


def hours_between(later, earlier):
    delta = later - earlier
    seconds = D(delta.days) * D(86400) + D(delta.seconds) + D(delta.microseconds) / D(1000000)
    return seconds / D(3600)


def intervals_overlap(cand_start, cand_end, inc_start, inc_end):
    return cand_start < inc_end and inc_start < cand_end


# ===========================================================================
# permit_daily_bucket_usage
# ===========================================================================


def permit_daily_bucket(allotment_id, event_date):
    bucket = event_date.date()
    total = D(0)
    for event in db.events.values():
        if event["allotment_id"] != allotment_id:
            continue
        if event["status"] != "POSTED":
            continue
        if event["event_date"].date() != bucket:
            continue
        total += event["mass_kg"]
    return q3(total)


def permit_consumed(allotment_id):
    total = D(0)
    for event in db.events.values():
        if event["allotment_id"] == allotment_id and event["status"] == "POSTED":
            total += event["mass_kg"]
    return q3(total)


# ===========================================================================
# facility_capacity_projection
# ===========================================================================

PROJECTION_CUSTODY_STATES = (
    "RECEIVED",
    "IDENTIFIED",
    "DISCHARGED",
    "PACKAGED",
    "RELEASED",
)


def facility_capacity_projection(facility, horizon_days):
    now = db.now()
    window_start = now - timedelta(days=LOOKBACK_DAYS)
    total = D(0)
    for intake in db.intakes.values():
        if intake["facility_id"] != facility["id"]:
            continue
        if intake["custody_state"] not in PROJECTION_CUSTODY_STATES:
            continue
        received = intake["received_at"]
        if received < window_start or received > now:
            continue
        total += intake["net_mass_kg"]
    baseline = q3(total / D(LOOKBACK_DAYS))
    mech = facility["mech_capacity_kg_per_day"]
    daily = []
    for day in range(1, horizon_days + 1):
        daily.append(q3(baseline * (D(1) + GROWTH_RATE_PER_DAY * D(day))))
    projected_total = q3(sum(daily, D(0)))
    first_deficit_day = None
    for index, value in enumerate(daily, start=1):
        if value > mech:
            first_deficit_day = index
            break
    if first_deficit_day is None:
        first_deficit_date = None
        deficit_kg = q3(0)
    else:
        first_deficit_date = now + timedelta(days=first_deficit_day)
        deficit_kg = q3(daily[first_deficit_day - 1] - mech)
    return {
        "baseline_kg_per_day": baseline,
        "horizon_days": horizon_days,
        "projected_input_kg": projected_total,
        "mech_capacity_kg_per_day": mech,
        "hydro_capacity_kg_per_day": facility["hydro_capacity_kg_per_day"],
        "first_deficit_day": first_deficit_day,
        "first_deficit_date": first_deficit_date,
        "deficit_kg": deficit_kg,
    }
