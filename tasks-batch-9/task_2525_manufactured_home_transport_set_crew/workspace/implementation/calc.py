"""Pure calculation rules and their constants (SCAFFOLD section 1.3 / PRD section 3)."""
from decimal import Decimal, ROUND_HALF_UP

# --- escort_requirement_matrix --------------------------------------------
OVERSIZE_WIDTH_IN = 192
SUPERLOAD_WIDTH_IN = 216
OVERHEIGHT_IN = 162
MAX_ESCORTS = 4
NIGHT_MOVE_ESCORT_BONUS = 1
PILOT_CAR_LEG_THRESHOLD = 3
STATE_ESCORT_BASE = {"AZ": 0, "NM": 1, "TX": 1, "OK": 1, "KS": 2, "CO": 2}

# --- permit_fee_assessment -------------------------------------------------
BASE_FEE_CENTS = 12000
WIDTH_FREE_ALLOWANCE_IN = 168
PER_INCH_OVER_WIDTH_CENTS = 250
PER_LEG_CENTS = 4500
ESCORT_SURCHARGE_CENTS = 7500
OVERHEIGHT_SURCHARGE_CENTS = 9000
SUPERLOAD_MULTIPLIER = Decimal("1.25")
PERMIT_VALID_DAYS = 5

# --- marriage_line_closure_score ------------------------------------------
MAX_GAP_IN = Decimal("0.25")
MAX_OFFSET_IN = Decimal("0.5")
GAP_WEIGHT = Decimal("1.0")
OFFSET_WEIGHT = Decimal("0.6")
SHIM_WEIGHT = Decimal("0.4")
CLOSURE_PASS_MAX_SCORE = Decimal("1.00")

# --- installation_invoice_total -------------------------------------------
SKIRTING_RATE_CENTS_PER_FT = 1850
STEPS_UNIT_CENTS = 42000
UTILITY_CROSSOVER_BASE_CENTS = 60000
PER_CROSSOVER_CENTS = 18000
TIER_3_MIN_CENTS = 300000
TIER_6_MIN_CENTS = 600000
TIER_10_MIN_CENTS = 900000

# --- damage_claim_allocation ----------------------------------------------
APPROVAL_HAIRCUT_PCT = Decimal("0.10")
CLAIM_CAP_CENTS = 2500000
STAGE_OWNER = {
    "PLANT_QC": "PLANT",
    "IN_TRANSIT": "HAULER",
    "AT_SET": "INSTALLER",
    "FINAL_INSPECTION": "INSTALLER",
}
DISCOVERED_STAGES = ["PLANT_QC", "IN_TRANSIT", "AT_SET", "FINAL_INSPECTION", "UNKNOWN"]

# --- party_chargeback_ledger ----------------------------------------------
HAULER_SUSPENSION_THRESHOLD_CENTS = 500000
PLANT_PROBATION_THRESHOLD_CENTS = 750000

# --- site_readiness_evaluation --------------------------------------------
MIN_PIERS_PER_SECTION = 6

# --- anchor_certification_evaluation --------------------------------------
MIN_TORQUE_FT_LB = Decimal("175")
REQUIRED_STRAPS_PER_ANCHOR = 1
STATE_EXTRA_ANCHORS = 4
MAX_ANCHOR_REVISIONS = 3
REQUIRED_ANCHORS_PER_ZONE = {"I": 8, "II": 12, "III": 16}
STATE_EXTRA_ANCHOR_STATES = ("KS", "CO")


def dec(value):
    """Exact Decimal from an int / float / str without binary-float noise."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_cents(value):
    return int(round_half_up(value, 0))


# ---------------------------------------------------------------------------
# escort_requirement_matrix
# ---------------------------------------------------------------------------
def escort_requirement_matrix(width_in, height_in, state_code, night_move, leg_count):
    width = dec(width_in)
    height = dec(height_in)
    if width >= SUPERLOAD_WIDTH_IN:
        permit_class = "SUPERLOAD"
    elif width >= OVERSIZE_WIDTH_IN:
        permit_class = "OVERSIZE"
    else:
        permit_class = "STANDARD"

    total = STATE_ESCORT_BASE.get(state_code, 0)
    if width >= OVERSIZE_WIDTH_IN:
        total += 1
    if width >= SUPERLOAD_WIDTH_IN:
        total += 1
    if height >= OVERHEIGHT_IN:
        total += 1
    if night_move:
        total += NIGHT_MOVE_ESCORT_BONUS
    escort_count_required = min(MAX_ESCORTS, total)

    pilot_car_required = bool(
        permit_class != "STANDARD"
        or leg_count >= PILOT_CAR_LEG_THRESHOLD
        or (state_code == "KS" and height >= OVERHEIGHT_IN)
    )
    return {
        "permit_class": permit_class,
        "escort_count_required": escort_count_required,
        "pilot_car_required": pilot_car_required,
    }


# ---------------------------------------------------------------------------
# permit_fee_assessment
# ---------------------------------------------------------------------------
def permit_fee_assessment(width_in, height_in, leg_count, escort_count, permit_class):
    width = dec(width_in)
    height = dec(height_in)
    width_excess = width - dec(WIDTH_FREE_ALLOWANCE_IN)
    if width_excess < 0:
        width_excess = Decimal(0)
    subtotal = (
        dec(BASE_FEE_CENTS)
        + width_excess * dec(PER_INCH_OVER_WIDTH_CENTS)
        + dec(leg_count) * dec(PER_LEG_CENTS)
        + dec(escort_count) * dec(ESCORT_SURCHARGE_CENTS)
    )
    if height >= OVERHEIGHT_IN:
        subtotal += dec(OVERHEIGHT_SURCHARGE_CENTS)
    multiplier = SUPERLOAD_MULTIPLIER if permit_class == "SUPERLOAD" else Decimal("1.0")
    return round_cents(subtotal * multiplier)


# ---------------------------------------------------------------------------
# marriage_line_closure_score
# ---------------------------------------------------------------------------
def joint_deviation_score(gap_in, vertical_offset_in, ridge_beam_shim_in):
    gap_excess = dec(gap_in) - MAX_GAP_IN
    if gap_excess < 0:
        gap_excess = Decimal(0)
    offset_excess = abs(dec(vertical_offset_in)) - MAX_OFFSET_IN
    if offset_excess < 0:
        offset_excess = Decimal(0)
    raw = (
        GAP_WEIGHT * gap_excess
        + OFFSET_WEIGHT * offset_excess
        + SHIM_WEIGHT * dec(ridge_beam_shim_in)
    )
    return round_half_up(raw, 2)


def closure_score_and_status(joint_rows):
    """``joint_rows`` are the set job's joints; per-joint scores are already rounded."""
    ordered = sorted(joint_rows, key=lambda r: r["joint_index"])
    if not ordered:
        return Decimal("0.00"), "NOT_APPLICABLE"
    total = Decimal("0")
    for row in ordered:
        total += dec(row["deviation_score"])
    score = round_half_up(total, 2)
    status = "PASS" if score <= CLOSURE_PASS_MAX_SCORE else "FAIL"
    return score, status


# ---------------------------------------------------------------------------
# installation_invoice_total
# ---------------------------------------------------------------------------
def skirting_fee(owner, skirting_linear_ft):
    if owner == "DEALER":
        return 0
    return round_cents(dec(skirting_linear_ft) * dec(SKIRTING_RATE_CENTS_PER_FT))


def steps_fee(owner, steps_count):
    if owner == "DEALER":
        return 0
    return int(steps_count) * STEPS_UNIT_CENTS


def crossover_fee(crossover_count):
    return UTILITY_CROSSOVER_BASE_CENTS + int(crossover_count) * PER_CROSSOVER_CENTS


def discount_pct_for(pre_discount_total_cents):
    if pre_discount_total_cents >= TIER_10_MIN_CENTS:
        return Decimal("0.10")
    if pre_discount_total_cents >= TIER_6_MIN_CENTS:
        return Decimal("0.06")
    if pre_discount_total_cents >= TIER_3_MIN_CENTS:
        return Decimal("0.03")
    return Decimal("0.00")


def installation_invoice_total(labor_base_cents, skirting_fee_cents, steps_fee_cents,
                              crossover_fee_cents):
    scope_subtotal = int(skirting_fee_cents) + int(steps_fee_cents)
    pre_discount_total = int(labor_base_cents) + scope_subtotal + int(crossover_fee_cents)
    pct = discount_pct_for(pre_discount_total)
    crossover_billed = 0 if pct > 0 else int(crossover_fee_cents)
    billable_base = int(labor_base_cents) + scope_subtotal + crossover_billed
    volume_discount = round_cents(dec(pre_discount_total) * pct)
    return billable_base - volume_discount


# ---------------------------------------------------------------------------
# damage_claim_allocation
# ---------------------------------------------------------------------------
PARTY_CODES = ("HAULER", "INSTALLER", "PLANT")


def approved_amount(claimed_amount_cents):
    return round_cents(dec(claimed_amount_cents) * (Decimal("1") - APPROVAL_HAIRCUT_PCT))


def stage_allocation(discovered_stage, approved):
    charges = {"PLANT": 0, "HAULER": 0, "INSTALLER": 0}
    owner = STAGE_OWNER.get(discovered_stage)
    if owner is None:
        return None
    charges[owner] = approved
    return charges


def evidence_allocation(points, approved):
    """floor + largest-remainder split, exact to the cent."""
    total_points = sum(points.values())
    base = {}
    numerator = {}
    for party in PARTY_CODES:
        pts = points[party]
        base[party] = (approved * pts) // total_points
        numerator[party] = (approved * pts) % total_points
    remainder = approved - sum(base.values())
    ranked = sorted(
        PARTY_CODES,
        key=lambda p: (-numerator[p], -points[p], p),
    )
    charges = dict(base)
    for index in range(remainder):
        charges[ranked[index]] += 1
    return charges


# ---------------------------------------------------------------------------
# site_readiness_evaluation
# ---------------------------------------------------------------------------
def site_readiness_evaluation(site, order, pad_pass, pier_plan_pass, utility_pass):
    pier_plan_effective = bool(pier_plan_pass) and site["pier_count"] >= (
        MIN_PIERS_PER_SECTION * order["section_count"]
    )
    utility_effective = (
        bool(utility_pass)
        and bool(site["utility_water"])
        and bool(site["utility_sewer"])
        and bool(site["utility_electric"])
    )
    count = 0
    if not pad_pass:
        count += 1
    if not pier_plan_effective:
        count += 1
    if not utility_effective:
        count += 1
    return count, ("READY" if count == 0 else "READINESS_FAILED")


# ---------------------------------------------------------------------------
# anchor_certification_evaluation
# ---------------------------------------------------------------------------
def required_anchors(order):
    per_zone = REQUIRED_ANCHORS_PER_ZONE.get(order["wind_zone"], 0)
    return per_zone * order["section_count"]


def anchor_certification_evaluation(cert, order):
    required = required_anchors(order)
    hud_pass = (
        cert["anchor_count"] >= required
        and dec(cert["avg_torque_ft_lb"]) >= MIN_TORQUE_FT_LB
        and cert["strap_count"] >= cert["anchor_count"] * REQUIRED_STRAPS_PER_ANCHOR
    )
    extra = (
        STATE_EXTRA_ANCHORS
        if order["destination_state"] in STATE_EXTRA_ANCHOR_STATES
        else 0
    )
    state_pass = cert["anchor_count"] >= (required + extra)
    return bool(hud_pass), bool(state_pass)


# ---------------------------------------------------------------------------
# escort_reserved_minutes / escort_window_conflict
# ---------------------------------------------------------------------------
def reservation_minutes(window_start, window_end):
    seconds = (window_end - window_start).total_seconds()
    return int(round_half_up(dec(seconds) / dec(60), 0))
