"""Every calculation in PRD section 3, in exact decimal arithmetic.

Rounding discipline (PRD 2.6): no intermediate rounding anywhere; each formula
rounds exactly once, always round-half-up, at the point named below.
"""

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, localcontext

ZERO2 = Decimal("0.00")
ONE = Decimal(1)
HUNDRED = Decimal(100)

# PRD 3.8: per-unit payment-module surcharge, integer cents.
SURCHARGE_CENTS = {"NONE": 0, "COIN": 3500, "CARD": 12500, "MOBILE": 9000}

# PRD 3.1: capacity bands, inclusive at both ends.
CAPACITY_BANDS = {
    "ON_PREMISES": (20, 200),
    "VENDED": (20, 80),
    "INDUSTRIAL_TUNNEL": (150, 600),
}

# PRD 3.5: bearing preload acceptance window keyed on drum_alloy_grade.
PRELOAD_WINDOWS = {
    "AISI_304": (Decimal("18.00"), Decimal("32.00")),
    "AISI_316": (Decimal("20.00"), Decimal("34.00")),
    "DUPLEX_2205": (Decimal("24.00"), Decimal("40.00")),
}

# PRD 3.5: station chain. build_state -> station_type that may be logged next.
NEXT_STATION_FOR_STATE = {
    "ON_FLOOR": "DRUM_FAB",
    "DRUM_DONE": "BEARING_INSTALL",
    "BEARINGS_DONE": "CONTROL_INTEGRATION",
}
STATE_AFTER_PASS = {
    "ON_FLOOR": "DRUM_DONE",
    "DRUM_DONE": "BEARINGS_DONE",
    "BEARINGS_DONE": "QA_HOLD",
}
SCOPE_FOR_STATION_TYPE = {
    "DRUM_FAB": "DRUM_FAB",
    "BEARING_INSTALL": "BEARING_INSTALL",
    "CONTROL_INTEGRATION": "CONTROL_INTEGRATION",
}

# PRD 3.9: warranty multipliers.
DUTY_MULTIPLIER = {"LIGHT": Decimal("1.25"), "STANDARD": Decimal("1.00"),
                   "HEAVY": Decimal("0.70")}
LINE_FACTOR = {"ON_PREMISES": Decimal("1.00"), "VENDED": Decimal("0.85"),
               "INDUSTRIAL_TUNNEL": Decimal("1.30")}


def round_cents(value):
    """The single round-half-up step of a money formula."""
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


def round2(value):
    return Decimal(value).quantize(ZERO2, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(Decimal(value).to_integral_value(rounding=ROUND_FLOOR))


# ---- quote_line_total (PRD 3.8) ---------------------------------------
def quote_line_total_cents(unit_price_cents, surcharge_cents, quantity,
                           line_discount_pct):
    with localcontext() as ctx:
        ctx.prec = 50
        per_unit = Decimal(unit_price_cents) + Decimal(surcharge_cents)
        extended = per_unit * Decimal(quantity)
        factor = ONE - (Decimal(line_discount_pct) / HUNDRED)
        return round_cents(extended * factor)


# ---- quote_money_rollup (PRD 3.8) -------------------------------------
def quote_rollup(lines, package_discount_pct, freight_cents):
    with localcontext() as ctx:
        ctx.prec = 50
        subtotal = sum(line["line_total_cents"] for line in lines)
        discount = round_cents(Decimal(subtotal) * Decimal(package_discount_pct) / HUNDRED)
        total = subtotal - discount + freight_cents
        return {
            "line_count": len(lines),
            "line_subtotal_cents": subtotal,
            "discount_cents": discount,
            "total_cents": total,
        }


# ---- financing_terms (PRD 3.8) ---------------------------------------
def origination_rate_pct(pre_fee_principal_cents):
    if pre_fee_principal_cents <= 5000000:
        return Decimal("2.50")
    if pre_fee_principal_cents <= 15000000:
        return Decimal("1.75")
    return Decimal("1.00")


def score_adjustment_bp(score):
    if score >= 760:
        return -250
    if score >= 700:
        return -100
    if score >= 640:
        return 0
    return 300


def base_apr_bp(financing_program):
    return 1450 if financing_program == "TERM_36" else 1690


def term_months(financing_program):
    return 36 if financing_program == "TERM_36" else 60


def apr_bp(financing_program, score, distributor_state):
    total = (base_apr_bp(financing_program)
             + score_adjustment_bp(score)
             + (150 if distributor_state == "PROBATION" else 0))
    return max(900, min(2400, total))


def principal_and_fee(total_cents, down_payment_cents):
    with localcontext() as ctx:
        ctx.prec = 50
        pre_fee = total_cents - down_payment_cents
        fee = round_cents(Decimal(pre_fee) * origination_rate_pct(pre_fee) / HUNDRED)
        return pre_fee, fee, pre_fee + fee


def monthly_payment_cents(financed_principal_cents, apr, program):
    with localcontext() as ctx:
        ctx.prec = 50
        months = term_months(program)
        rate = Decimal(apr) / Decimal(10000) / Decimal(12)
        denominator = ONE - (ONE + rate) ** (-months)
        return round_cents(Decimal(financed_principal_cents) * rate / denominator)


# ---- warranty_coverage (PRD 3.9) -------------------------------------
def effective_rated_cycles(rated_duty_cycles, duty_cycle_class, product_line):
    with localcontext() as ctx:
        ctx.prec = 50
        product = (Decimal(rated_duty_cycles)
                   * DUTY_MULTIPLIER[duty_cycle_class]
                   * LINE_FACTOR[product_line])
        return floor_int(product)


def settlement(unit_price_cents, warranty_months, in_service_months,
               failure_cycle_count, eff_cycles):
    """Returns (coverage_variant, covered_amount_cents)."""
    if in_service_months <= 12 and failure_cycle_count * 2 <= eff_cycles:
        return "FULL_REPLACEMENT", unit_price_cents
    with localcontext() as ctx:
        ctx.prec = 50
        cycle_ratio = (Decimal(eff_cycles - failure_cycle_count) / Decimal(eff_cycles))
        month_ratio = (Decimal(warranty_months - in_service_months)
                       / Decimal(warranty_months))
        ratio = cycle_ratio if cycle_ratio < month_ratio else month_ratio
        return "PRO_RATA", round_cents(Decimal(unit_price_cents) * ratio)


# ---- part_stock_projection (PRD 3.9) ---------------------------------
def project_stock_state(on_hand_qty, reorder_point_qty):
    if on_hand_qty == 0:
        return "BACKORDERED"
    if on_hand_qty <= reorder_point_qty:
        return "LOW"
    return "IN_STOCK"


# ---- station_occupation_window (PRD 3.5) -----------------------------
def labor_minutes(started_at, completed_at):
    seconds = (completed_at - started_at).total_seconds()
    return floor_int(Decimal(seconds) / Decimal(60))


# ---- model_first_pass_yield (PRD 3.6) --------------------------------
def first_pass_yield_pct(builds):
    terminal = [b for b in builds if b["build_state"] in ("ACCEPTED", "SCRAPPED")]
    if not terminal:
        return ZERO2
    first_pass = [b for b in terminal
                  if b["build_state"] == "ACCEPTED" and b["rework_count"] == 0]
    with localcontext() as ctx:
        ctx.prec = 50
        return round2(Decimal(len(first_pass)) * HUNDRED / Decimal(len(terminal)))


# ---- rebate_qualification (PRD 3.3) ----------------------------------
def rebate_qualification(model, dossier, programs):
    """Returns (qualified_program_codes sorted ASC, rebate_amount_cents)."""
    certified_date = dossier["certified_at"].date()
    qualifying = []
    for program in programs:
        if program["program_state"] != "ACTIVE":
            continue
        if model["product_line"] not in program["eligible_product_lines"]:
            continue
        if dossier["measured_water_gal_per_cwt"] > program["max_water_gal_per_cwt"]:
            continue
        if dossier["measured_kwh_per_cwt"] > program["max_kwh_per_cwt"]:
            continue
        if model["capacity_rating_lb"] < program["min_capacity_rating_lb"]:
            continue
        if not (program["effective_from"].date() <= certified_date
                <= program["effective_to"].date()):
            continue
        bonus_steps = (model["capacity_rating_lb"]
                       - program["min_capacity_rating_lb"]) // 10
        uncapped = (program["rebate_base_cents"]
                    + program["capacity_bonus_cents_per_10lb"] * bonus_steps)
        payable = min(uncapped, program["rebate_cap_cents"])
        qualifying.append((uncapped, payable, program))
    if not qualifying:
        return [], 0
    ranked = sorted(
        qualifying,
        key=lambda item: (-item[0], item[2]["effective_from"], item[2]["program_code"]),
    )
    codes = sorted(item[2]["program_code"] for item in qualifying)
    return codes, ranked[0][1]
