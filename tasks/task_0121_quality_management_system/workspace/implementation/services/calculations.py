"""Calculation rules (PRD 2.5, 3.3, 3.6, 3.7, 3.4; scaffold 1.3).

All monetary/precision math uses Decimal with ROUND_HALF_UP (round-half-away-
from-zero). Never float for money.
"""
from decimal import Decimal, ROUND_HALF_UP


def _round_half_up(value, places=0):
    """Round half away from zero to the given number of decimal places."""
    q = Decimal(1).scaleb(-places)  # 10**-places
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# ncr_cost_of_quality (PRD 3.3 / scaffold 1.3)
# ---------------------------------------------------------------------------
LABOUR_RATE_CENTS_PER_HOUR = 6000
USE_AS_IS_CONCESSION_PCT = Decimal("0.30")
HANDLING_PCT = Decimal("0.10")
SEVERITY_WEIGHT = {
    "CRITICAL": Decimal("1.5"),
    "MAJOR": Decimal("1.0"),
    "MINOR": Decimal("0.5"),
}


def cost_of_quality(disposition, severity, defect_qty, unit_cost_cents, rework_hours):
    """Per-unit cost computed per line then summed (round-per-line THEN sum)."""
    # Per-unit labour figure: rework_hours * 6000, rounded half-up to whole cents.
    labour_cents_per_unit = _round_half_up(
        Decimal(str(rework_hours)) * Decimal(LABOUR_RATE_CENTS_PER_HOUR)
    )
    unit_cost = Decimal(unit_cost_cents)

    if disposition == "REWORK":
        unit_component = labour_cents_per_unit
    elif disposition == "SCRAP":
        unit_component = unit_cost
    elif disposition == "USE_AS_IS":
        unit_component = _round_half_up(unit_cost * USE_AS_IS_CONCESSION_PCT)
    elif disposition == "RETURN_TO_SUPPLIER":
        unit_component = _round_half_up(unit_cost * HANDLING_PCT)
    else:
        unit_component = Decimal(0)

    severity_multiplier = SEVERITY_WEIGHT[severity]
    per_line = _round_half_up(unit_component * severity_multiplier)
    total = per_line * Decimal(defect_qty)
    return int(total)


# ---------------------------------------------------------------------------
# supplier_quality_rating (PRD 3.7 / scaffold 1.3)
# ---------------------------------------------------------------------------
W_LOT = Decimal("0.6")
W_NCR = Decimal("0.4")
NCR_PENALTY = Decimal("0.10")
SCAR_PENALTY_STEP = Decimal("0.05")
SCAR_PENALTY_CAP = Decimal("0.20")
APPROVE_AT = Decimal("70.00")
PROBATION_AT = Decimal("50.00")


def supplier_quality_rating(lots_inspected, lots_rejected, ncrs_attributed, open_scar_count):
    """Return (quality_rating Decimal 2dp, approval_status)."""
    if lots_inspected == 0:
        lot_factor = Decimal("1.0")
    else:
        lot_factor = Decimal(1) - (Decimal(lots_rejected) / Decimal(lots_inspected))
        if lot_factor < 0:
            lot_factor = Decimal(0)

    ncr_factor = Decimal(1) - (Decimal(ncrs_attributed) * NCR_PENALTY)
    if ncr_factor < 0:
        ncr_factor = Decimal(0)

    scar_penalty = Decimal(open_scar_count) * SCAR_PENALTY_STEP
    if scar_penalty > SCAR_PENALTY_CAP:
        scar_penalty = SCAR_PENALTY_CAP

    base = (W_LOT * lot_factor) + (W_NCR * ncr_factor)
    raw = base - scar_penalty
    if raw < 0:
        raw = Decimal(0)

    rating = _round_half_up(raw * Decimal(100), 2)

    if rating >= APPROVE_AT:
        approval_status = "APPROVED"
    elif rating >= PROBATION_AT:
        approval_status = "PROBATION"
    else:
        approval_status = "DISQUALIFIED"
    return rating, approval_status


# ---------------------------------------------------------------------------
# capa_effectiveness (PRD 3.4 / scaffold 1.3)
# ---------------------------------------------------------------------------
def provisional_effectiveness(total_containment_count, defect_qty):
    """min(1.0, total_containment / max(1, defect_qty)) rounded 2dp."""
    divisor = Decimal(max(1, defect_qty))
    value = Decimal(total_containment_count) / divisor
    if value > 1:
        value = Decimal(1)
    return _round_half_up(value, 2)


def final_effectiveness(recurred_defects, defect_qty):
    """1.0 - recurred / max(1, defect_qty), clamped [0,1], rounded 2dp."""
    divisor = Decimal(max(1, defect_qty))
    value = Decimal(1) - (Decimal(recurred_defects) / divisor)
    if value < 0:
        value = Decimal(0)
    if value > 1:
        value = Decimal(1)
    return _round_half_up(value, 2)


# ---------------------------------------------------------------------------
# aql_sampling (PRD 3.6 / scaffold 1.3)
# ---------------------------------------------------------------------------
# GII lot-size bands -> code letter.
_GII_BANDS = [
    (2, 8, "A"),
    (9, 15, "B"),
    (16, 25, "C"),
    (26, 50, "D"),
    (51, 90, "E"),
    (91, 150, "F"),
    (151, 280, "G"),
    (281, 500, "H"),
]
_LETTER_ORDER = ["A", "B", "C", "D", "E", "F", "G", "H"]

# Reduced single-sampling lookup: (code_letter, aql_column) -> {n, Ac}
_LOOKUP = {
    ("D", "1.0"): (8, 0), ("E", "1.0"): (13, 0), ("F", "1.0"): (20, 0),
    ("G", "1.0"): (32, 1), ("H", "1.0"): (50, 1),
    ("D", "2.5"): (8, 0), ("E", "2.5"): (13, 1), ("F", "2.5"): (20, 1),
    ("G", "2.5"): (32, 2), ("H", "2.5"): (50, 3),
    ("D", "4.0"): (8, 1), ("E", "4.0"): (13, 1), ("F", "4.0"): (20, 2),
    ("G", "4.0"): (32, 3), ("H", "4.0"): (50, 5),
}

# AQL columns tightest -> loosest.
_AQL_ORDER = ["1.0", "2.5", "4.0"]


def _code_letter_for(inspection_level, lot_size):
    base = None
    for low, high, letter in _GII_BANDS:
        if low <= lot_size <= high:
            base = letter
            break
    if base is None:
        # Out of the tabulated band; clamp to the nearest end.
        if lot_size < 2:
            base = "A"
        else:
            base = "H"
    idx = _LETTER_ORDER.index(base)
    if inspection_level == "GI":
        idx = max(0, idx - 1)
    elif inspection_level == "GIII":
        idx = min(len(_LETTER_ORDER) - 1, idx + 1)
    return _LETTER_ORDER[idx]


def _normalize_aql_column(aql_pct):
    """Map a numeric aql_pct to its lookup-column string key."""
    # Columns supported by the lookup are 1.0, 2.5, 4.0.
    d = Decimal(str(aql_pct)).normalize()
    if d == Decimal("1.0"):
        return "1.0"
    if d == Decimal("2.5"):
        return "2.5"
    if d == Decimal("4.0"):
        return "4.0"
    # Other permitted aql_pct values (0.65, 1.5, 6.5) have no column; fall back
    # to the string rendering so a missing-cell lookup surfaces clearly.
    return str(aql_pct)


def _next_tighter(column):
    idx = _AQL_ORDER.index(column)
    if idx == 0:
        return column  # 1.0 stays at 1.0
    return _AQL_ORDER[idx - 1]


def aql_sampling(inspection_level, lot_size, aql_pct, severity_mode):
    """Resolve (sample_size, acceptance_number, rejection_number)."""
    code_letter = _code_letter_for(inspection_level, lot_size)
    column = _normalize_aql_column(aql_pct)
    if severity_mode == "TIGHTENED":
        column = _next_tighter(column)
    cell = _LOOKUP[(code_letter, column)]
    sample_size, acceptance_number = cell
    rejection_number = acceptance_number + 1
    return sample_size, acceptance_number, rejection_number
