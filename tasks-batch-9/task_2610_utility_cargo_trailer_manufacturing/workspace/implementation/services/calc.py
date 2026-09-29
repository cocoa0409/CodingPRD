"""Calculation rules (SCAFFOLD 1.3 / PRD 3).

Every monetary computation runs on Decimal; round_half_up is the only rounding
used for money and 'floor to a 10 lb step' the only rounding used for the
certified GVWR.
"""
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

# --- constants, read from the scaffold's calculations table --------------------
TIRES_PER_AXLE = 2
UNBRAKED_AXLE_DERATE = Decimal("0.90")
GVWR_ROUND_STEP_LBS = 10

FRAME_TOL_MM = Decimal("3.0")
SQUARENESS_TOL_MM = Decimal("6.0")
NON_CRITICAL_MAX = 2
FRAME_SCRAP_THRESHOLD = 3

WIDE_BODY_WIDTH_IN = Decimal("80.0")
WIDE_BODY_CLEARANCE_LAMPS = 5
WIDE_BODY_SIDE_MARKERS = 4
BRAKE_REQUIRED_GVWR_LBS = 3000
ALL_AXLE_BRAKE_GVWR_LBS = 10000

ORDER_FREIGHT_FLAT_CENTS = 89500
FLOOR_PLAN_DRAW_PCT = Decimal("0.90")
TIER_1_MAX_YTD = 0
TIER_2_MAX_YTD = 1
TIER_2_PCT = Decimal("0.03")
TIER_3_PCT = Decimal("0.05")

PARTS_MARKUP_PCT = Decimal("0.30")
PART_FREIGHT_FLAT_CENTS = 4500
FREIGHT_WAIVER_CENTS = 50000
WARRANTY_DAYS = 730

VIN_WMI = "5XY"
VIN_PLANT_CODE = "P"
VIN_YEAR_CODE = {2026: "T", 2027: "V", 2028: "W", 2029: "X", 2030: "Y"}

FLAT_RATE_HOURS = {"AXLE": Decimal("3.5"), "BRAKE": Decimal("2.5"),
                   "LIGHTING": Decimal("1.5"), "FRAME": Decimal("6.0"),
                   "FLOORING": Decimal("4.0"), "COUPLER": Decimal("2.0")}
FLAT_RATE_UPLIFT = Decimal("1.25")

ROAD_TEST_MAX_STOP_FT = Decimal("40.0")
MIN_PAYLOAD_CAPACITY_LBS = 0
WARRANTY_GRACE_DAYS = 90


def dec(value):
    """Exact Decimal for any JSON number without a binary-float detour."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_to_step(value, step):
    quotient = (dec(value) / Decimal(step)).to_integral_value(rounding=ROUND_FLOOR)
    return int(quotient) * step


def num(value):
    """Render a numeric so that whole values serialize as integers."""
    d = dec(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# --- gvwr_rating ---------------------------------------------------------------
def _capacities(model):
    axle = model["axle_count"] * model["axle_rating_lbs"]
    tire = model["axle_count"] * TIRES_PER_AXLE * model["tire_load_rating_lbs"]
    frame = model["frame_design_rated_lbs"]
    coupler = model["coupler_rating_lbs"]
    return axle, tire, frame, coupler


def provisional_gvwr(model):
    """Variant provisional_engineering_estimate: tires excluded, no derate."""
    axle, _tire, frame, coupler = _capacities(model)
    return min(axle, frame, coupler)


def certified_gvwr(model):
    """Variant certified_final: min over all four, then derate, then floor to 10."""
    axle, tire, frame, coupler = _capacities(model)
    raw = min(axle, tire, frame, coupler)
    if model["design_braked_axle_count"] < model["axle_count"]:
        derated = dec(raw) * UNBRAKED_AXLE_DERATE
    else:
        derated = dec(raw)
    return floor_to_step(derated, GVWR_ROUND_STEP_LBS)


# --- frame_dimensional_verdict -------------------------------------------------
def frame_verdict(model, measured_length_mm, measured_width_mm, diagonal_a_mm,
                  diagonal_b_mm, critical_count, non_critical_count):
    length_dev = abs(dec(measured_length_mm) - dec(model["nominal_length_mm"]))
    width_dev = abs(dec(measured_width_mm) - dec(model["nominal_width_mm"]))
    max_dev = max(length_dev, width_dev)
    squareness = abs(dec(diagonal_a_mm) - dec(diagonal_b_mm))

    reasons = []
    if critical_count > 0:
        reasons.append("CRITICAL_WELD_DEFECT")
    if max_dev > FRAME_TOL_MM:
        reasons.append("MAX_DEVIATION")
    if non_critical_count > NON_CRITICAL_MAX:
        reasons.append("NON_CRITICAL_WELD_DEFECT")
    if squareness > SQUARENESS_TOL_MM:
        reasons.append("SQUARENESS")
    reasons.sort()
    return {
        "length_deviation_mm": num(length_dev),
        "width_deviation_mm": num(width_dev),
        "max_deviation_mm": num(max_dev),
        "squareness_delta_mm": num(squareness),
        "result": "PASS" if not reasons else "FAIL",
        "failure_reasons": reasons,
    }


# --- regulatory_equipment_requirements ----------------------------------------
def lighting_ok(model, stop_tail_turn, clearance, side_marker, license_plate, reflex):
    if stop_tail_turn < 2:
        return False
    if license_plate < 1:
        return False
    if reflex < 4:
        return False
    if dec(model["overall_width_in"]) < WIDE_BODY_WIDTH_IN:
        return True
    return clearance >= WIDE_BODY_CLEARANCE_LAMPS and side_marker >= WIDE_BODY_SIDE_MARKERS


def brake_ok(model, unit_gvwr_lbs, installed_braked_axle_count, breakaway_kit_installed):
    ok = True
    if unit_gvwr_lbs is not None and unit_gvwr_lbs >= BRAKE_REQUIRED_GVWR_LBS:
        ok = installed_braked_axle_count >= 1 and breakaway_kit_installed is True
    if unit_gvwr_lbs is not None and unit_gvwr_lbs >= ALL_AXLE_BRAKE_GVWR_LBS:
        ok = ok and installed_braked_axle_count == model["axle_count"]
    return ok


# --- vin_assignment ------------------------------------------------------------
def build_vin(model, unit, vin_sequence, clock_year):
    braked = unit.get("installed_braked_axle_count") or 0
    brake_code = "E" if braked >= 1 else "N"
    year_char = VIN_YEAR_CODE.get(clock_year, "T")
    vin = (VIN_WMI
           + model["frame_design_code"]
           + str(model["axle_count"])
           + brake_code
           + "A"
           + "0"
           + year_char
           + VIN_PLANT_CODE
           + "%06d" % vin_sequence)
    return vin


def mco_number(vin_sequence):
    return "MCO-%06d" % vin_sequence


# --- order_invoice_and_draw ----------------------------------------------------
def invoice(model, option_lines, allocations_ytd_count, stocking_program):
    """The pinned seven-step order of PRD 3.8."""
    # 1
    options_total_cents = 0
    for line in option_lines:
        if line["status"] in ("PENDING", "COMPLETED"):
            options_total_cents += line["total_price_cents"]
    # 2
    invoice_subtotal_cents = model["base_dealer_price_cents"] + options_total_cents
    # 3 — the dealer's YTD count as observed BEFORE this allocation is counted
    n = allocations_ytd_count
    if n <= TIER_1_MAX_YTD:
        pct = Decimal("0.00")
    elif n <= TIER_2_MAX_YTD:
        pct = TIER_2_PCT
    else:
        pct = TIER_3_PCT
    # 4
    volume_discount_cents = round_half_up(dec(invoice_subtotal_cents) * pct)
    # 5 — freight is waived whenever any volume tier applies
    freight_cents = 0 if pct >= TIER_2_PCT else ORDER_FREIGHT_FLAT_CENTS
    # 6
    invoice_total_cents = invoice_subtotal_cents - volume_discount_cents + freight_cents
    # 7
    if stocking_program == "DEMO":
        floor_plan_draw_cents = 0
    else:
        floor_plan_draw_cents = round_half_up(dec(invoice_total_cents) * FLOOR_PLAN_DRAW_PCT)
    return {
        "invoice_subtotal_cents": invoice_subtotal_cents,
        "volume_discount_pct": num(pct) if pct == 0 else float(pct),
        "volume_discount_cents": volume_discount_cents,
        "freight_cents": freight_cents,
        "invoice_total_cents": invoice_total_cents,
        "floor_plan_draw_cents": floor_plan_draw_cents,
    }


# --- warranty flat-rate ceiling ------------------------------------------------
def flat_rate_ceiling(complaint_code):
    return FLAT_RATE_HOURS[complaint_code] * FLAT_RATE_UPLIFT


def labor_hours_within_ceiling(complaint_code, labor_hours):
    return dec(labor_hours) <= flat_rate_ceiling(complaint_code)


# --- warranty_reimbursement ----------------------------------------------------
def warranty_expiry(warranty_start_dt):
    from datetime import timedelta
    return warranty_start_dt + timedelta(days=WARRANTY_DAYS)


def days_past_expiry(warranty_start_dt, failure_dt):
    """Whole days from the expiry instant to the failure instant, fraction discarded."""
    expiry = warranty_expiry(warranty_start_dt)
    delta = failure_dt - expiry
    return math.floor(delta.total_seconds() / 86400.0)


def coverage_for(days_past):
    if days_past <= 0:
        return "IN_WARRANTY_FULL", Decimal("1.00")
    if days_past <= 30:
        return "GOODWILL_PRORATED", Decimal("0.75")
    if days_past <= 60:
        return "GOODWILL_PRORATED", Decimal("0.50")
    if days_past <= 90:
        return "GOODWILL_PRORATED", Decimal("0.25")
    return None, None


def reimbursement(part_lines, labor_hours, labor_rate_cents_per_hour,
                  warranty_start_dt, failure_dt):
    """Rounding order is pinned: per line first, coverage last."""
    parts_subtotal_cents = 0
    for line in part_lines:
        marked_up = round_half_up(dec(line["unit_cost_cents"]) * (Decimal("1") + PARTS_MARKUP_PCT))
        parts_subtotal_cents += marked_up * line["quantity"]

    labor_cents = round_half_up(dec(labor_hours) * dec(labor_rate_cents_per_hour))

    if parts_subtotal_cents == 0:
        freight_cents = 0
    elif parts_subtotal_cents >= FREIGHT_WAIVER_CENTS:
        freight_cents = 0
    else:
        freight_cents = PART_FREIGHT_FLAT_CENTS

    gross_cents = labor_cents + parts_subtotal_cents + freight_cents

    days_past = days_past_expiry(warranty_start_dt, failure_dt)
    variant, factor = coverage_for(days_past)
    if variant is None:
        return None
    total = round_half_up(dec(gross_cents) * factor)
    return {
        "coverage_variant": variant,
        "coverage_factor": float(factor),
        "labor_cents": labor_cents,
        "parts_subtotal_cents": parts_subtotal_cents,
        "freight_cents": freight_cents,
        "reimbursement_total_cents": total,
    }


# --- jig / lane geometry -------------------------------------------------------
def whole_minutes(start_dt, end_dt):
    return int((end_dt - start_dt).total_seconds() // 60)
