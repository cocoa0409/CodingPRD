"""Calculation rules (SCAFFOLD 1.3 / PRD 3.3-3.9).

Money is integer cents throughout; every multiplication rounds HALF UP to a
whole cent at exactly the point named in the rule.  Geometry rounds HALF UP to
one decimal place; diopter deltas round HALF UP to two decimal places before
comparison.
"""

from datetime import timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

# --- constants -------------------------------------------------------------

COATING_PRICE_CENTS = {
    "HARDCOAT": 2495,
    "AR_STANDARD": 5995,
    "AR_PREMIUM": 10995,
    "POLARIZED": 11995,
    "PHOTOCHROMIC": 13995,
}
COATING_CODES = ("HARDCOAT", "AR_STANDARD", "AR_PREMIUM", "PHOTOCHROMIC", "POLARIZED")

COSMETIC_DEFECT_CODES = (
    "MINOR_EDGE_CHIP",
    "DEEP_SCRATCH",
    "COATING_CRAZE",
    "INCLUSION",
    "POLISH_HAZE",
)

REMAKE_DEFECT_CODES = (
    "POWER_OUT_OF_TOL",
    "AXIS_OUT_OF_TOL",
    "PRISM_OUT_OF_TOL",
    "COSMETIC_DEFECT",
    "WRONG_MATERIAL",
    "WRONG_COATING",
    "WRONG_PD",
    "WRONG_FITTING_HEIGHT",
    "WRONG_FRAME",
    "PATIENT_NONADAPT",
    "RX_TRANSCRIPTION",
)

LAB_ATTRIBUTABLE_DEFECTS = (
    "POWER_OUT_OF_TOL",
    "AXIS_OUT_OF_TOL",
    "PRISM_OUT_OF_TOL",
    "COSMETIC_DEFECT",
    "WRONG_MATERIAL",
    "WRONG_COATING",
)
STORE_ATTRIBUTABLE_DEFECTS = (
    "WRONG_PD",
    "WRONG_FITTING_HEIGHT",
    "WRONG_FRAME",
    "PATIENT_NONADAPT",
    "RX_TRANSCRIPTION",
)
MIXED_DEFECT_LAB_SHARE_PCT = 50

FITTING_CROSS_ALLOWANCE_MM = Decimal("4.0")
SPECIALTY_ALLOWANCE_MM = Decimal("2.0")
CHUCK_ALLOWANCE_MM = Decimal("2.0")
MAX_BLANK_DIAMETER_MM = Decimal("85.0")

STOCK_SPHERE_ABS_MAX = Decimal("6.00")
STOCK_CYLINDER_ABS_MAX = Decimal("2.00")

BASE_TAT_HOURS = {"ECONOMY": 120, "STANDARD": 72, "PREMIUM": 48}
SURFACING_TAT_PENALTY_HOURS = 24
EXPEDITE_FACTOR = Decimal("0.5")
BACKORDER_EXTENSION_HOURS = 48

SURFACING_SURCHARGE_CENTS = 4500

REMAKE_WRITEOFF_PCT = {1: Decimal("0.25"), 2: Decimal("0.60")}
MAX_REMAKES_PER_ORDER = 2

AXIS_RELEVANCE_CYL_MIN = Decimal("0.25")
WARRANTY_DAYS = 90
BENEFIT_PERIOD_MONTHS = 12


# --- numeric helpers -------------------------------------------------------

def D(value):
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places=0):
    """Round HALF UP to `places` decimal places, returning a Decimal."""
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def cents(value):
    """Round HALF UP to a whole cent."""
    return int(rhu(value, 0))


def mm1(value):
    """Round HALF UP to one decimal place, returning a float."""
    return float(rhu(value, 1))


def dio2(value):
    """Round HALF UP to two decimal places, returning a float."""
    return float(rhu(value, 2))


def add_months(d, months):
    """Advance a date by whole calendar months, clamping the day-of-month."""
    total = (d.year * 12 + (d.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    day = d.day
    last = _last_day(year, month)
    if day > last:
        day = last
    return d.replace(year=year, month=month, day=day)


def _last_day(year, month):
    if month == 2:
        leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
        return 29 if leap else 28
    if month in (1, 3, 5, 7, 8, 10, 12):
        return 31
    return 30


# --- rx_expiration_window --------------------------------------------------

def expiration_instant(issued_on_date, validity_months):
    """issued_on advanced by validity_months calendar months, at midnight UTC."""
    from datetime import datetime, timezone

    target = add_months(issued_on_date, int(validity_months))
    return datetime(target.year, target.month, target.day, tzinfo=timezone.utc)


# --- frame_layout_geometry -------------------------------------------------

def frame_layout_geometry(a_mm, b_mm, ed_mm, dbl_mm, effective_fitting_height_mm,
                          mono_pd_od, mono_pd_os, design_type):
    frame_pd = D(a_mm) + D(dbl_mm)
    half = frame_pd / Decimal(2)
    dec_h_od = rhu(abs(half - D(mono_pd_od)), 1)
    dec_h_os = rhu(abs(half - D(mono_pd_os)), 1)
    dec_v = rhu(abs(D(effective_fitting_height_mm) - D(b_mm) / Decimal(2)), 1)

    def total(dec_h):
        if design_type == "SINGLE_VISION":
            return dec_h
        if design_type == "PROGRESSIVE":
            return max(dec_h, dec_v) + FITTING_CROSS_ALLOWANCE_MM
        return dec_h + dec_v + SPECIALTY_ALLOWANCE_MM

    blank_od = rhu(D(ed_mm) + Decimal(2) * total(dec_h_od) + CHUCK_ALLOWANCE_MM, 1)
    blank_os = rhu(D(ed_mm) + Decimal(2) * total(dec_h_os) + CHUCK_ALLOWANCE_MM, 1)
    required = max(blank_od, blank_os)
    status = "BLANK_TOO_SMALL" if required > MAX_BLANK_DIAMETER_MM else "COMPUTED"
    return {
        "decentration_h_od_mm": float(dec_h_od),
        "decentration_h_os_mm": float(dec_h_os),
        "decentration_v_mm": float(dec_v),
        "required_blank_diameter_mm": float(required),
        "layout_status": status,
    }


# --- lab_route_determination -----------------------------------------------

def determine_route(design, rx):
    if not design.get("stock_sku_available"):
        return "SURFACE_AND_EDGE"
    if design.get("design_type") == "SPECIALTY":
        return "SURFACE_AND_EDGE"
    max_sphere = max(abs(D(rx.get("sphere_od"))), abs(D(rx.get("sphere_os"))))
    if max_sphere > STOCK_SPHERE_ABS_MAX:
        return "SURFACE_AND_EDGE"
    max_cyl = max(abs(D(rx.get("cylinder_od"))), abs(D(rx.get("cylinder_os"))))
    if max_cyl > STOCK_CYLINDER_ABS_MAX:
        return "SURFACE_AND_EDGE"
    if D(rx.get("prism_diopter_od")) != Decimal("0") or D(rx.get("prism_diopter_os")) != Decimal("0"):
        return "SURFACE_AND_EDGE"
    return "STOCK_EDGE_ONLY"


# --- blank_lot_selection ---------------------------------------------------

def select_blank_lot(lots, lens_design_id, required_diameter, exclude_lot_id=None):
    candidates = []
    for lot in lots:
        if lot.get("lens_design_id") != lens_design_id:
            continue
        if lot.get("status") != "AVAILABLE":
            continue
        if lot.get("on_hand_qty", 0) <= 0:
            continue
        if D(lot.get("diameter_mm")) < D(required_diameter):
            continue
        if exclude_lot_id is not None and lot.get("id") == exclude_lot_id:
            continue
        candidates.append(lot)
    if not candidates:
        return None
    candidates.sort(key=lambda l: (D(l["diameter_mm"]), l["received_on"], l["_seq"]))
    return candidates[0]


# --- machine_bay_occupation_feasibility ------------------------------------

def machine_window_conflict(existing_ops, start, end, buffer_minutes):
    buf = timedelta(minutes=int(buffer_minutes or 0))
    for op in existing_ops:
        if start < op["window_end"] + buf and op["window_start"] < end + buf:
            return True
    return False


def bay_overlap_count(existing_ops, start, end):
    count = 0
    for op in existing_ops:
        if op["window_start"] <= end and start <= op["window_end"]:
            count += 1
    return count


# --- turnaround_and_expedite_fee ------------------------------------------

def expedite_rate(promised_tat_hours):
    if promised_tat_hours <= 24:
        return Decimal("0.30")
    if promised_tat_hours <= 48:
        return Decimal("0.20")
    if promised_tat_hours <= 72:
        return Decimal("0.12")
    return Decimal("0.00")


def turnaround(product_tier, expedite_requested, route, variant, lens_subtotal_cents):
    """variant is PROVISIONAL or ROUTE_ACTUAL."""
    nominal = BASE_TAT_HOURS[product_tier]
    if variant == "ROUTE_ACTUAL" and route == "SURFACE_AND_EDGE":
        nominal += SURFACING_TAT_PENALTY_HOURS
    if expedite_requested:
        promised = int((D(nominal) * EXPEDITE_FACTOR).to_integral_value(rounding=ROUND_CEILING))
    else:
        promised = nominal
    rate = expedite_rate(promised)
    fee = cents(D(lens_subtotal_cents) * rate) if expedite_requested else 0
    return promised, fee


# --- order_quote_and_patient_portion --------------------------------------

def coating_component_order(requested):
    return sorted(requested, key=lambda c: (-COATING_PRICE_CENTS.get(c, 0), c))


def build_components(order, design, route, variant):
    """Ordered component charge list: FRAME, LENS, then coatings by price DESC."""
    frame_charge = int(order.get("frame_retail_cents") or 0)
    lens_charge = int(design["retail_price_cents"])
    if variant == "FINAL" and route == "SURFACE_AND_EDGE":
        lens_charge += SURFACING_SURCHARGE_CENTS
    components = [("FRAME", "FRAME", frame_charge), ("LENS", "LENS", lens_charge)]
    for code in coating_component_order(order.get("requested_coatings") or []):
        components.append(("COATING", code, COATING_PRICE_CENTS.get(code, 0)))
    return components


def quote(order, design, route, variant):
    components = build_components(order, design, route, variant)
    frame_charge = components[0][2]
    lens_charge = components[1][2]
    coating_total = sum(c[2] for c in components[2:])
    lens_subtotal = lens_charge + coating_total
    tat_variant = "ROUTE_ACTUAL" if variant == "FINAL" else "PROVISIONAL"
    promised_tat, expedite_fee = turnaround(
        order["product_tier"], bool(order.get("expedite_requested")), route,
        tat_variant, lens_subtotal,
    )
    gross = frame_charge + lens_charge + coating_total + expedite_fee
    return {
        "components": components,
        "frame_charge_cents": frame_charge,
        "lens_charge_cents": lens_charge,
        "coating_total_cents": coating_total,
        "lens_subtotal_cents": lens_subtotal,
        "promised_tat_hours": promised_tat,
        "expedite_fee_cents": expedite_fee,
        "gross_charge_cents": gross,
    }


# --- benefit_application_waterfall ----------------------------------------

def benefit_waterfall(components, design, plan, expedite_fee_cents, apply_annual_cap,
                      benefit_used_excluding_this_order=0):
    """Self-pay (plan is None) runs the identical formula with every allowance
    and coinsurance_pct forced to 0, so the result is 0."""
    if plan is None:
        return 0

    coinsurance_pct = D(plan.get("coinsurance_pct"))
    coating_pool = int(plan.get("coating_allowance_cents") or 0)
    allowance_total = 0
    coinsurance_total = 0
    for kind, code, charge in components:
        if kind == "FRAME":
            allowance = int(plan.get("frame_allowance_cents") or 0)
        elif kind == "LENS":
            base = int(plan.get("lens_base_allowance_cents") or 0)
            copay = int(plan.get("progressive_copay_cents") or 0) if design.get("design_type") == "PROGRESSIVE" else 0
            allowance = max(0, base - copay)
        else:
            allowance = min(coating_pool, charge)
            coating_pool -= allowance
        allowance_total += allowance
        uncovered = max(0, charge - allowance)
        coinsurance_total += cents(D(uncovered) * coinsurance_pct)

    uncapped = allowance_total + coinsurance_total
    if plan.get("expedite_covered"):
        uncapped += int(expedite_fee_cents or 0)

    if not apply_annual_cap:
        return uncapped
    cap_remaining = max(0, int(plan.get("annual_benefit_cap_cents") or 0)
                        - int(benefit_used_excluding_this_order or 0))
    return min(uncapped, cap_remaining)


# --- inspection_delta_and_verdict -----------------------------------------

def inspection_deltas(measured_sphere, measured_cylinder, measured_axis, measured_prism,
                      rx_sphere, rx_cylinder, rx_axis, rx_prism):
    sphere_delta = rhu(abs(D(measured_sphere) - D(rx_sphere)), 2)
    cylinder_delta = rhu(abs(D(measured_cylinder) - D(rx_cylinder)), 2)
    prism_delta = rhu(abs(D(measured_prism) - D(rx_prism)), 2)
    raw = abs(int(measured_axis or 0) - int(rx_axis or 0))
    axis_delta = min(raw, 180 - raw)
    return sphere_delta, cylinder_delta, axis_delta, prism_delta


def inspection_verdict(sphere_delta, cylinder_delta, axis_delta, prism_delta,
                       rx_cylinder, cosmetic_defect_codes, standard):
    failed = []
    if sphere_delta > D(standard["sphere_tolerance_diopters"]):
        failed.append("SPHERE")
    if cylinder_delta > D(standard["cylinder_tolerance_diopters"]):
        failed.append("CYLINDER")
    if abs(D(rx_cylinder)) >= AXIS_RELEVANCE_CYL_MIN:
        if axis_delta > int(standard["axis_tolerance_degrees"]):
            failed.append("AXIS")
    if prism_delta > D(standard["prism_tolerance_pd"]):
        failed.append("PRISM")
    allowed = standard.get("allowed_cosmetic_defect_codes") or []
    for code in (cosmetic_defect_codes or []):
        if code not in allowed:
            failed.append("COSMETIC")
            break
    return failed, ("FAIL" if failed else "PASS")


# --- remake_responsibility_split ------------------------------------------

def process_audit_share(defect_codes):
    if all(c in LAB_ATTRIBUTABLE_DEFECTS for c in defect_codes):
        return 100
    if all(c in STORE_ATTRIBUTABLE_DEFECTS for c in defect_codes):
        return 0
    return MIXED_DEFECT_LAB_SHARE_PCT


def tolerance_delta_share(inspection, standard):
    pairs = (
        (D(inspection["sphere_delta"]), D(standard["sphere_tolerance_diopters"])),
        (D(inspection["cylinder_delta"]), D(standard["cylinder_tolerance_diopters"])),
        (D(inspection["axis_delta"]), D(standard["axis_tolerance_degrees"])),
        (D(inspection["prism_delta"]), D(standard["prism_tolerance_pd"])),
    )
    total = Decimal("0")
    for delta, tol in pairs:
        if tol == 0:
            ratio = Decimal("1")
        else:
            ratio = min(Decimal("1"), delta / tol)
        total += ratio
    return int(rhu(Decimal(100) * total / Decimal(4), 0))


def job_cost_basis_cents(design, order, route):
    basis = int(design["retail_price_cents"])
    if route == "SURFACE_AND_EDGE":
        basis += SURFACING_SURCHARGE_CENTS
    for code in (order.get("requested_coatings") or []):
        basis += COATING_PRICE_CENTS.get(code, 0)
    return basis


def responsibility_for(lab_share_pct):
    if lab_share_pct == 0:
        return "STORE"
    if lab_share_pct == 100:
        return "LAB"
    return "SPLIT"
