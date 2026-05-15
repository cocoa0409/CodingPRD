"""Calculations: pricing, surcharge/refund, package discount, qualification
posture, and per-method test-result formulas.

All money arithmetic is performed in integer cents using `Decimal` rounding
half-up. Numeric results round half-up to 1 decimal place.
"""

import re
import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from services.time_util import today_utc, parse_iso


# ---------------------------------------------------------------------------
# Static reference tables (from SCAFFOLD calculations.test_item_pricing)
# ---------------------------------------------------------------------------

METHOD_TO_CATEGORY = {
    "COMPRESSION_STRENGTH": "CONCRETE",
    "TENSILE_STRENGTH": "STEEL_REBAR",
    "COMPACTION_DENSITY": "SOIL",
    "MARSHALL_STABILITY": "ASPHALT",
    "SETTING_TIME": "CEMENT",
}

BASE_FEE_CENTS = {
    "COMPRESSION_STRENGTH": 20000,
    "TENSILE_STRENGTH": 25000,
    "COMPACTION_DENSITY": 18000,
    "MARSHALL_STABILITY": 30000,
    "SETTING_TIME": 15000,
}

LOWER_BOUND = {
    "COMPRESSION_STRENGTH": Decimal("20.0"),
    "TENSILE_STRENGTH": Decimal("400.0"),
    "COMPACTION_DENSITY": Decimal("1.9"),
    "MARSHALL_STABILITY": Decimal("7.5"),
    "SETTING_TIME": Decimal("45.0"),
}

UPPER_BOUND = {
    "COMPRESSION_STRENGTH": Decimal("60.0"),
    "TENSILE_STRENGTH": Decimal("600.0"),
    "COMPACTION_DENSITY": Decimal("2.6"),
    "MARSHALL_STABILITY": Decimal("18.0"),
    "SETTING_TIME": Decimal("600.0"),
}

URGENT_SURCHARGE_RATE = Decimal("0.50")
REFUND_RATE_ON_ABNORMAL_AFTER_RETEST = Decimal("0.30")
PACKAGE_THRESHOLD_COUNT = 5
PACKAGE_DISCOUNT_RATE = Decimal("0.10")

MATERIAL3 = {
    "CONCRETE": "CON",
    "STEEL_REBAR": "STE",
    "SOIL": "SOI",
    "ASPHALT": "ASP",
    "CEMENT": "CEM",
}

TEMPLATE_CODES = {
    "COMPRESSION_STRENGTH": "TPL-COMPRESSION-V2",
    "TENSILE_STRENGTH": "TPL-TENSILE-V2",
    "COMPACTION_DENSITY": "TPL-COMPACTION-V2",
    "MARSHALL_STABILITY": "TPL-MARSHALL-V2",
    "SETTING_TIME": "TPL-SETTING-V2",
}


def round_half_up_cents(value: Decimal) -> int:
    """Round a Decimal cents value half-up to nearest integer cents."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_one_decimal(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Qualification posture (SCAFFOLD calculations.tester_qualification_posture)
# ---------------------------------------------------------------------------

EXPIRING_WINDOW_DAYS = 30


def _parse_date(s):
    """Accept ISO date or datetime string; return date."""
    if s is None:
        return None
    if hasattr(s, "year") and not hasattr(s, "hour"):
        return s
    if isinstance(s, str):
        try:
            return parse_iso(s).date()
        except ValueError:
            # Could be plain YYYY-MM-DD
            try:
                from datetime import datetime as _dt
                return _dt.fromisoformat(s).date()
            except Exception:
                raise
    return None


def compute_qualification_posture(qualifications):
    """Return one of QUALIFIED | EXPIRING_SOON | LAPSED."""
    today = today_utc()
    in_effect = []
    for q in qualifications or []:
        vf = _parse_date(q.get("valid_from"))
        vt = _parse_date(q.get("valid_to"))
        if vf is None or vt is None:
            continue
        if vf <= today <= vt:
            in_effect.append(q)
    if not in_effect:
        return "LAPSED"
    for q in in_effect:
        vt = _parse_date(q.get("valid_to"))
        if (vt - today).days <= EXPIRING_WINDOW_DAYS:
            return "EXPIRING_SOON"
    return "QUALIFIED"


def tester_has_category_in_effect(tester, category):
    today = today_utc()
    for q in tester.get("qualifications", []) or []:
        if q.get("material_category") != category:
            continue
        vf = _parse_date(q.get("valid_from"))
        vt = _parse_date(q.get("valid_to"))
        if vf is None or vt is None:
            continue
        if vf <= today <= vt:
            return True
    return False


# ---------------------------------------------------------------------------
# Test-result calculation (SCAFFOLD calculations.test_result_calculation)
# ---------------------------------------------------------------------------

def _parse_compression_area_mm2(specification: str) -> Decimal:
    """For COMPRESSION_STRENGTH: parse cube edge length from specs like
    'C30 cube 150mm' -> 150 * 150 = 22500.
    Falls back to a default if not parseable, but raises ValueError if no
    plausible dimension found.
    """
    if not specification:
        raise ValueError("specification required")
    m = re.search(r"(\d+(?:\.\d+)?)\s*mm", specification)
    if not m:
        # Try last integer in the string
        ints = re.findall(r"(\d+(?:\.\d+)?)", specification)
        if not ints:
            raise ValueError("no dimension in specification")
        edge = Decimal(ints[-1])
    else:
        edge = Decimal(m.group(1))
    return edge * edge


def _parse_tensile_area_mm2(specification: str) -> Decimal:
    """For TENSILE_STRENGTH on rebar like 'HRB400 D16' — diameter 16mm,
    area = pi/4 * d^2.
    """
    if not specification:
        raise ValueError("specification required")
    m = re.search(r"[Dd](\d+(?:\.\d+)?)", specification)
    if not m:
        m = re.search(r"(\d+(?:\.\d+)?)\s*mm", specification)
    if not m:
        ints = re.findall(r"(\d+(?:\.\d+)?)", specification)
        if not ints:
            raise ValueError("no diameter in specification")
        diameter = Decimal(ints[-1])
    else:
        diameter = Decimal(m.group(1))
    pi = Decimal("3.141592653589793")
    return (pi / Decimal(4)) * (diameter * diameter)


def compute_test_result(test_method, raw_data, specification):
    """Return (calculated_result_as_float, abnormal_flag_bool)."""
    rd = raw_data or {}

    def _to_dec(x):
        return Decimal(str(x))

    if test_method == "COMPRESSION_STRENGTH":
        peak = _to_dec(rd.get("peak_load_kn", 0))
        area = _parse_compression_area_mm2(specification)
        # MPa = kN * 1000 / mm^2
        mpa = (peak * Decimal(1000)) / area
        result = round_half_up_one_decimal(mpa)
    elif test_method == "TENSILE_STRENGTH":
        peak = _to_dec(rd.get("peak_load_kn", 0))
        area = _parse_tensile_area_mm2(specification)
        mpa = (peak * Decimal(1000)) / area
        result = round_half_up_one_decimal(mpa)
    elif test_method == "COMPACTION_DENSITY":
        # density g/cm^3 — raw_data may carry density directly or mass/volume
        if "density_g_cm3" in rd:
            result = round_half_up_one_decimal(_to_dec(rd["density_g_cm3"]))
        else:
            mass = _to_dec(rd.get("mass_g", 0))
            volume = _to_dec(rd.get("volume_cm3", 1))
            result = round_half_up_one_decimal(mass / volume)
    elif test_method == "MARSHALL_STABILITY":
        # Stability in kN
        if "stability_kn" in rd:
            result = round_half_up_one_decimal(_to_dec(rd["stability_kn"]))
        else:
            result = round_half_up_one_decimal(_to_dec(rd.get("peak_load_kn", 0)))
    elif test_method == "SETTING_TIME":
        # Setting time in minutes
        if "setting_time_minutes" in rd:
            result = round_half_up_one_decimal(_to_dec(rd["setting_time_minutes"]))
        else:
            result = round_half_up_one_decimal(_to_dec(rd.get("time_minutes", 0)))
    else:
        raise ValueError(f"Unknown test_method {test_method}")

    lower = LOWER_BOUND[test_method]
    upper = UPPER_BOUND[test_method]
    abnormal = (result < lower) or (result > upper)
    # Convert to plain float for JSON serialisation (1-decimal).
    return float(result), abnormal


# ---------------------------------------------------------------------------
# Sample code minting (SCAFFOLD entities.Sample.sample_code)
# ---------------------------------------------------------------------------

def material_prefix(material_category: str) -> str:
    return MATERIAL3.get(material_category, material_category[:3].upper())


# ---------------------------------------------------------------------------
# Invoice pricing (SCAFFOLD calculations.invoice_total)
# ---------------------------------------------------------------------------

def compute_line_item(task, final_record_abnormal):
    """Compute base_fee_cents, surcharge_cents, refund_cents for one task.

    `final_record_abnormal` reflects whether the final non-superseded
    TestRecord on the task has abnormal_flag == true.
    """
    method = task["test_method"]
    base_fee = BASE_FEE_CENTS[method]
    if task.get("urgent"):
        surcharge = round_half_up_cents(Decimal(base_fee) * URGENT_SURCHARGE_RATE)
    else:
        surcharge = 0
    if task.get("retest_count", 0) == 1 and final_record_abnormal:
        refund = round_half_up_cents(Decimal(base_fee) * REFUND_RATE_ON_ABNORMAL_AFTER_RETEST)
    else:
        refund = 0
    return {
        "task_id": task["id"],
        "base_fee_cents": base_fee,
        "surcharge_cents": surcharge,
        "refund_cents": refund,
    }


def compute_invoice_totals(line_items, client_contract_id, client_deposit_balance):
    """Run aggregate + package + deposit pricing.

    Returns a dict with keys:
      subtotal_cents, surcharge_total_cents, refund_total_cents,
      package_discount_cents, deposit_applied_cents, total_due_cents.
    """
    subtotal = sum(li["base_fee_cents"] for li in line_items)
    surcharge_total = sum(li["surcharge_cents"] for li in line_items)
    refund_total = sum(li["refund_cents"] for li in line_items)
    gross = subtotal + surcharge_total - refund_total

    if len(line_items) >= PACKAGE_THRESHOLD_COUNT or client_contract_id:
        package_discount = round_half_up_cents(Decimal(gross) * PACKAGE_DISCOUNT_RATE)
    else:
        package_discount = 0

    pre_deposit_total = gross - package_discount
    deposit_applied = min(client_deposit_balance, pre_deposit_total)
    if deposit_applied < 0:
        deposit_applied = 0
    total_due = pre_deposit_total - deposit_applied

    return {
        "subtotal_cents": subtotal,
        "surcharge_total_cents": surcharge_total,
        "refund_total_cents": refund_total,
        "package_discount_cents": package_discount,
        "deposit_applied_cents": deposit_applied,
        "total_due_cents": total_due,
    }


# ---------------------------------------------------------------------------
# Instrument usage accrual (SCAFFOLD calculations.instrument_usage_log)
# ---------------------------------------------------------------------------

def booking_duration_minutes_ceil(slot_start, slot_end):
    """Return ceiling of (slot_end - slot_start) in seconds, expressed in
    whole minutes."""
    start = parse_iso(slot_start) if isinstance(slot_start, str) else slot_start
    end = parse_iso(slot_end) if isinstance(slot_end, str) else slot_end
    delta_seconds = (end - start).total_seconds()
    if delta_seconds <= 0:
        return 0
    return int(math.ceil(delta_seconds / 60.0))
