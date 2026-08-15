"""Calculation rules (SCAFFOLD §1.3 / PRD §2.4, §3). Integer arithmetic only."""

from util import ceil_div, round_half_up_div

# nesting_yield / provisional_quote standard sheet constants
STD_SHEET_W_CIN = 4000
STD_SHEET_H_CIN = 2800
STD_GUTTER_CIN = 25
STD_EDGE_MARGIN_CIN = 50
STD_GRIPPER_CIN = 75
OFFSET_SPOILAGE_NUM = 108
DIGITAL_SPOILAGE_NUM = 103
SPOILAGE_DEN = 100

# route_selection
DIGITAL_MAX_QTY = 2500

# tiered print pricing
MIN_BILLING_QTY = 1000
TIER_1_QTY = 2500
TIER_1_RATE_CENTS = 38
TIER_2_QTY = 5000
TIER_2_RATE_CENTS = 30
TIER_3_QTY = 10000
TIER_3_RATE_CENTS = 24
BASE_RATE_CENTS = 45

REFERENCE_SHEET_COST_CENTS = 320
RATE_PER_M = {"COAT": 950, "FOIL": 2650, "EMBOSS": 1775}
FINISH_OP_TO_CODE = {"COAT": "FINISH_COAT", "FOIL": "FINISH_FOIL", "EMBOSS": "FINISH_EMBOSS"}
FINISH_OP_ORDER = ("COAT", "FOIL", "EMBOSS")

MAKE_READY_OFFSET_CENTS = 180000
MAKE_READY_DIGITAL_CENTS = 25000
MAKE_READY_WAIVER_THRESHOLD_CENTS = 400000
MIN_ORDER_CENTS = 750000

KIT_LABOR_CENTS_PER_MIN = 150
KIT_FEE_PER_KIT_CENTS = 85

PALLET_W_CIN = 12192
PALLET_D_CIN = 10160
MAX_PALLET_HEIGHT_CIN = 15240
MAX_PALLET_WEIGHT_G = 680389


def nesting_yield(sheet_w, sheet_h, gutter, edge_margin, gripper,
                  blank_w, blank_h, grain_rotation_allowed):
    """Returns (ups, orientation). ups == 0 means the blank fits in no permitted orientation."""
    usable_w = sheet_w - 2 * edge_margin
    usable_h = sheet_h - edge_margin - gripper

    cols_a = max(0, usable_w // (blank_w + gutter))
    rows_a = max(0, usable_h // (blank_h + gutter))
    ups_a = cols_a * rows_a

    cols_b = max(0, usable_w // (blank_h + gutter))
    rows_b = max(0, usable_h // (blank_w + gutter))
    ups_b = cols_b * rows_b

    if not grain_rotation_allowed:
        return ups_a, "NORMAL"
    if ups_a >= ups_b:
        return ups_a, "NORMAL"
    return ups_b, "ROTATED"


def sheet_counts(ups, blank_w, blank_h, sheet_w, sheet_h, quantity_ordered, route_type):
    """net_sheets, gross_sheets (theoretical spoilage uplift), layout_yield_milli_pct."""
    net = ceil_div(quantity_ordered, ups)
    num = OFFSET_SPOILAGE_NUM if route_type == "OFFSET" else DIGITAL_SPOILAGE_NUM
    gross = ceil_div(net * num, SPOILAGE_DEN)
    layout_yield = (ups * blank_w * blank_h * 100000) // (sheet_w * sheet_h)
    return net, gross, layout_yield


def route_selection(finish_foil, finish_emboss, quantity_ordered):
    if finish_foil or finish_emboss:
        return "OFFSET"
    if quantity_ordered <= DIGITAL_MAX_QTY:
        return "DIGITAL"
    return "OFFSET"


def tier_rate_cents(billable_quantity):
    if billable_quantity >= TIER_3_QTY:
        return TIER_3_RATE_CENTS
    if billable_quantity >= TIER_2_QTY:
        return TIER_2_RATE_CENTS
    if billable_quantity >= TIER_1_QTY:
        return TIER_1_RATE_CENTS
    return BASE_RATE_CENTS


def finish_line_cents(cartons, op):
    """Per-line round_half_up(cartons * RATE_PER_M[op] / 1000)."""
    return round_half_up_div(cartons * RATE_PER_M[op], 1000)


def make_ready(route_type, print_line_cents):
    """Returns (waived, line_cents). Waiver decided from print line alone."""
    waived = route_type == "OFFSET" and print_line_cents >= MAKE_READY_WAIVER_THRESHOLD_CENTS
    if waived:
        return True, 0
    return False, (MAKE_READY_OFFSET_CENTS if route_type == "OFFSET" else MAKE_READY_DIGITAL_CENTS)


def _apply_minimum_recovery(lines):
    """lines: list of {"code", "amount_cents"} (each already rounded). Returns totals."""
    subtotal = sum(line["amount_cents"] for line in lines)
    minimum_recovery = max(0, MIN_ORDER_CENTS - subtotal)
    return subtotal, minimum_recovery, subtotal + minimum_recovery


def provisional_quote(job):
    """Forward-looking quote at job creation. Returns (quote_dict or None if ups == 0).

    quote_dict keys: lines, subtotal_cents, make_ready_waived,
    make_ready_line_cents, minimum_recovery_cents, total_cents.
    """
    qty = job["quantity_ordered"]
    billable = max(qty, MIN_BILLING_QTY)
    print_line = billable * tier_rate_cents(billable)

    ups, _orientation = nesting_yield(
        STD_SHEET_W_CIN, STD_SHEET_H_CIN, STD_GUTTER_CIN,
        STD_EDGE_MARGIN_CIN, STD_GRIPPER_CIN,
        job["blank_w_cin"], job["blank_h_cin"], job["grain_rotation_allowed"],
    )
    if ups == 0:
        return None
    _net, gross, _yield = sheet_counts(
        ups, job["blank_w_cin"], job["blank_h_cin"],
        STD_SHEET_W_CIN, STD_SHEET_H_CIN, qty, job["route_type"],
    )
    board_line = gross * REFERENCE_SHEET_COST_CENTS

    lines = [
        {"code": "PRINT", "amount_cents": print_line},
        {"code": "BOARD", "amount_cents": board_line},
    ]
    if job["finish_coat"]:
        lines.append({"code": "FINISH_COAT", "amount_cents": finish_line_cents(qty, "COAT")})
    if job["finish_foil"]:
        lines.append({"code": "FINISH_FOIL", "amount_cents": finish_line_cents(qty, "FOIL")})
    if job["finish_emboss"]:
        lines.append({"code": "FINISH_EMBOSS", "amount_cents": finish_line_cents(qty, "EMBOSS")})

    waived, mr_line = make_ready(job["route_type"], print_line)
    lines.append({"code": "MAKE_READY", "amount_cents": mr_line})

    subtotal, recovery, total = _apply_minimum_recovery(lines)
    return {
        "lines": lines,
        "subtotal_cents": subtotal,
        "make_ready_waived": waived,
        "make_ready_line_cents": mr_line,
        "minimum_recovery_cents": recovery,
        "total_cents": total,
    }


def final_settlement(job, stock, finishing_bookings, kit_orders):
    """Settlement at invoice finalize. Only COMPLETED bookings/kit orders contribute.

    Rounding order pin: every line rounded half-up individually, then summed.
    """
    qty = job["quantity_ordered"]
    billable = max(qty, MIN_BILLING_QTY)
    print_line = billable * tier_rate_cents(billable)
    good_cartons = job["good_sheets_actual"] * (job["locked_ups"] or 0)

    board_line = job["sheets_consumed_actual"] * stock["unit_cost_cents"]

    lines = [
        {"code": "PRINT", "amount_cents": print_line},
        {"code": "BOARD", "amount_cents": board_line},
    ]
    for op in FINISH_OP_ORDER:
        completed = any(
            fb["job_id"] == job["id"] and fb["operation"] == op and fb["status"] == "COMPLETED"
            for fb in finishing_bookings
        )
        if completed:
            lines.append({
                "code": FINISH_OP_TO_CODE[op],
                "amount_cents": finish_line_cents(good_cartons, op),
            })

    completed_kits = [k for k in kit_orders if k["job_id"] == job["id"] and k["status"] == "COMPLETED"]
    completed_kits.sort(key=lambda k: (k["created_at"], k["_seq"]))
    for kit in completed_kits:
        amount = (kit["labor_minutes_actual"] * KIT_LABOR_CENTS_PER_MIN
                  + kit["kits_completed"] * KIT_FEE_PER_KIT_CENTS)
        lines.append({"code": "KITTING", "amount_cents": amount})

    waived, mr_line = make_ready(job["route_type"], print_line)
    lines.append({"code": "MAKE_READY", "amount_cents": mr_line})

    subtotal, recovery, total = _apply_minimum_recovery(lines)
    return {
        "lines": lines,
        "subtotal_cents": subtotal,
        "make_ready_waived": waived,
        "make_ready_line_cents": mr_line,
        "minimum_recovery_cents": recovery,
        "total_cents": total,
    }


def retail_compliance_verdict(orientation, case_w, case_h, case_d, case_weight_g,
                              cases_per_layer, layers, case_count):
    """COMPLIANT iff footprint, height, weight, and exact count all pass (inclusive <=)."""
    if orientation == "LENGTHWISE":
        footprint_ok = (cases_per_layer * case_w <= PALLET_W_CIN) and (case_d <= PALLET_D_CIN)
    else:  # WIDTHWISE
        footprint_ok = (cases_per_layer * case_d <= PALLET_W_CIN) and (case_w <= PALLET_D_CIN)
    height_ok = layers * case_h <= MAX_PALLET_HEIGHT_CIN
    weight_ok = case_count * case_weight_g <= MAX_PALLET_WEIGHT_G
    count_ok = case_count == cases_per_layer * layers
    if footprint_ok and height_ok and weight_ok and count_ok:
        return "COMPLIANT"
    return "NON_COMPLIANT"
