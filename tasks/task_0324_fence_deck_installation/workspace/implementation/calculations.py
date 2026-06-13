"""Calculation rules (PRD §2.7, §3.2-§3.8 / scaffold §1.3).

All monetary math uses decimal.Decimal with round-half-up to exactly 2 dp.
Rate-table/config values keep their input precision.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# ----- Constants (scaffold §1.3) -----------------------------------------
RATE_TABLE = {
    ("CEDAR", "PRIVACY"): Decimal("42.50"),
    ("CEDAR", "PICKET"): Decimal("31.00"),
    ("VINYL", "PRIVACY"): Decimal("55.75"),
    ("COMPOSITE", "DECK_STANDARD"): Decimal("38.25"),
    ("PT_PINE", "DECK_STANDARD"): Decimal("24.80"),
    ("ALUMINUM", "ORNAMENTAL"): Decimal("48.90"),
}
ACCESSORY_ADDER = {
    "NONE": Decimal("0.00"),
    "SINGLE_GATE": Decimal("285.00"),
    "DOUBLE_GATE": Decimal("540.00"),
    "STAIR_SET": Decimal("420.00"),
}
LABOR_RATE = {"FENCE": Decimal("9.50"), "DECK": Decimal("22.00")}
MOBILIZATION_FEE = Decimal("650.00")
SLOPE_THRESHOLD_PCT = Decimal("15")
SLOPE_MULTIPLIER = Decimal("1.12")
DEPOSIT_CAP = Decimal("10000.00")
DEFAULT_WASTE_FACTOR_PCT = Decimal("10")
DOCK_BUFFER_HOURS = 4

DRAW_PCT = [
    ("DEPOSIT", Decimal("0.20")),
    ("DELIVERY", Decimal("0.30")),
    ("FRAMING", Decimal("0.30")),
    ("FINAL", Decimal("0.20")),
]


def D(value):
    """Coerce an int/float/str/Decimal to Decimal safely (via str for floats)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return Decimal(value)


def r2(value):
    """Round half up to 2 decimal places."""
    return D(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ----- line_item_estimate ------------------------------------------------
def line_material_cost(material, style, quantity_units, accessory, grade_slope_pct):
    rate = RATE_TABLE[(material, style)]
    slope_mult = SLOPE_MULTIPLIER if D(grade_slope_pct) >= SLOPE_THRESHOLD_PCT else Decimal("1.00")
    adder = ACCESSORY_ADDER[accessory]
    return r2(rate * D(quantity_units) * slope_mult + adder)


# ----- estimate_rollup ---------------------------------------------------
def rollup(priced_lines, tax_rate_pct):
    """priced_lines: list of {work_type, quantity_units, line_material_cost}.

    Returns (material_subtotal, labor_subtotal, material_tax, contract_total),
    all Decimal rounded to 2dp. material_tax is rounded PER LINE then summed.
    """
    material_subtotal = r2(sum((D(l["line_material_cost"]) for l in priced_lines), Decimal("0")))
    labor_raw = sum((LABOR_RATE[l["work_type"]] * D(l["quantity_units"]) for l in priced_lines), Decimal("0"))
    labor_subtotal = r2(labor_raw) + MOBILIZATION_FEE
    tax_rate = D(tax_rate_pct) / Decimal("100")
    material_tax = sum((r2(D(l["line_material_cost"]) * tax_rate) for l in priced_lines), Decimal("0"))
    contract_total = r2(material_subtotal + labor_subtotal + material_tax)
    return material_subtotal, labor_subtotal, material_tax, contract_total


# ----- draw_schedule -----------------------------------------------------
def draw_schedule(contract_total):
    """Return ordered list of (milestone, pct, amount)."""
    ct = D(contract_total)
    result = []
    running = Decimal("0.00")
    for milestone, pct in DRAW_PCT[:-1]:
        amt = r2(ct * pct)
        if milestone == "DEPOSIT" and amt > DEPOSIT_CAP:
            amt = DEPOSIT_CAP
        running += amt
        result.append((milestone, pct, amt))
    final_pct = DRAW_PCT[-1][1]
    final_amt = r2(ct - running)
    result.append(("FINAL", final_pct, final_amt))
    return result


def draw_rebalance(contract_total, draw_rows):
    """Re-derive non-PAID, non-VOIDED draw amounts on a new contract_total.

    PAID draws keep their amount fixed. Returns {milestone: new_amount} for the
    milestones whose draw rows were re-derived. draw_rows: list of dicts with
    'milestone', 'status', 'amount'.
    """
    ct = D(contract_total)
    by_milestone = {d["milestone"]: d for d in draw_rows}
    locked = sum(
        (D(d["amount"]) for d in draw_rows if d["status"] == "PAID"),
        Decimal("0.00"),
    )
    updates = {}
    running = Decimal("0.00")  # tracks all allocations for milestones before FINAL
    for milestone, pct in DRAW_PCT[:-1]:
        row = by_milestone.get(milestone)
        if row is None:
            continue
        if row["status"] == "PAID":
            running += D(row["amount"])
            continue
        if row["status"] == "VOIDED":
            # Voided draws contribute nothing and are not re-derived.
            continue
        amt = r2(ct * pct)
        if milestone == "DEPOSIT" and amt > DEPOSIT_CAP:
            amt = DEPOSIT_CAP
        running += amt
        updates[milestone] = amt
    # FINAL absorbs the remainder unless it is itself PAID (or VOIDED).
    final_row = by_milestone.get("FINAL")
    if final_row is not None:
        if final_row["status"] == "PAID":
            pass  # locked, untouched
        elif final_row["status"] == "VOIDED":
            pass
        else:
            updates["FINAL"] = r2(ct - running)
    return updates


# ----- material_takeoff --------------------------------------------------
def ordered_units(measured_units, waste_factor_pct):
    factor = Decimal("1") + D(waste_factor_pct) / Decimal("100")
    raw = D(measured_units) * factor
    return int(math.ceil(raw))


# ----- interval helpers --------------------------------------------------
def crew_overlap(cand_start, cand_end, exist_start, exist_end):
    """Half-open [start, end) overlap test. Back-to-back is NOT a conflict."""
    return cand_start < exist_end and exist_start < cand_end


def dock_conflict(cand_start, cand_end, exist_start, exist_end, buffer_hours=DOCK_BUFFER_HOURS):
    """Closed-interval test with the candidate expanded by buffer on each side.

    The existing window is taken as its stored closed window without buffer.
    Touching endpoints conflict; any gap smaller than the buffer conflicts.
    """
    from datetime import timedelta

    buf = timedelta(hours=buffer_hours)
    cs = cand_start - buf
    ce = cand_end + buf
    return cs <= exist_end and exist_start <= ce
