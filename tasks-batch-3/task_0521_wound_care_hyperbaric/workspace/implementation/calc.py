"""Calculation rules (PRD §3, SCAFFOLD calculations table)."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP


def _D(x):
    return Decimal(str(x))


def round_half_up(value, places):
    q = Decimal(1).scaleb(-places)  # e.g. places=2 -> 0.01
    return _D(value).quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(_D(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


# ---- wound_area ----
def wound_area(length_cm, width_cm):
    return float(round_half_up(_D(length_cm) * _D(width_cm), 2))


# ---- wound_severity_score ----
STAGE_POINTS = {"STAGE_1": 1, "STAGE_2": 2, "STAGE_3": 4, "STAGE_4": 8, "UNSTAGEABLE": 10}
TISSUE_BONUS = {"GRANULATION": 0, "EPITHELIAL": -1, "SLOUGH": 2, "NECROTIC": 4}


def wound_severity_score(stage, length_cm, width_cm, tissue_type, infected):
    area = _D(length_cm) * _D(width_cm)
    if area <= 4:
        area_mult = _D("1.0")
    elif area <= 16:
        area_mult = _D("1.5")
    else:
        area_mult = _D("2.0")
    raw = _D(STAGE_POINTS[stage]) * area_mult + (_D(5) if infected else _D(0)) + _D(TISSUE_BONUS[tissue_type])
    score = round_half_up_int(raw)
    return min(100, max(1, score))


# ---- supply_reimbursement (per-line round, then sum) ----
def supply_reimbursement(line_items):
    total = 0
    for li in line_items:
        line = _D(li["unit_price_cents"]) * _D(li["qty"]) * _D(li["coverage_rate"])
        total += round_half_up_int(line)
    return total


# ---- healing trajectory helpers ----
def _parse_dt(s):
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def actual_healing_pct(baseline_area, latest_area):
    if baseline_area == 0:
        return 0.0
    val = (_D(baseline_area) - _D(latest_area)) / _D(baseline_area) * _D(100)
    return float(round_half_up(val, 2))


def projected_healing_pct(prev_area, latest_area, days_between, baseline_area):
    if baseline_area == 0 or days_between <= 0:
        return 0.0
    weekly_rate = (_D(prev_area) - _D(latest_area)) / _D(days_between) * _D(7)
    val = weekly_rate / _D(baseline_area) * _D(100) * _D(4)
    return float(min(_D("100.0"), round_half_up(val, 2)))


# ---- hbo coverage cost ----
def hbo_coverage_cents(count, cap, rate):
    return min(count, cap) * rate
