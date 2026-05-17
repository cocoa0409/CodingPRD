"""Calculation rules from SCAFFOLD §1.3."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable

from .constants import (
    BAND_WIDTH_MIN,
    EVAL_SURCHARGE,
    MIN_TIMED_MIN,
    RATE_PT_DPT_CENTS,
    RATE_PTA_CENTS,
)


# ---- 8-Minute Rule ---------------------------------------------------------

def billed_units_eight_minute_rule(timed_minutes: int) -> int:
    if timed_minutes < MIN_TIMED_MIN:
        return 0
    return ((timed_minutes - MIN_TIMED_MIN) // BAND_WIDTH_MIN) + 1


# ---- Visit charge ----------------------------------------------------------

def rate_for_credential(credential: str) -> int:
    return RATE_PTA_CENTS if credential == "PTA" else RATE_PT_DPT_CENTS


def visit_charge_cents(units_billed: int, credential: str, eval_complexity_in_window: str | None) -> int:
    raw = units_billed * rate_for_credential(credential)
    if eval_complexity_in_window is not None:
        raw += EVAL_SURCHARGE[eval_complexity_in_window]
    return raw


# ---- Capped POC projection -------------------------------------------------

def capped_poc_projection(planned_visit_count: int, planned_units_per_visit: int, eval_complexity: str) -> int:
    planned_units_total = planned_visit_count * planned_units_per_visit
    projection = planned_units_total * RATE_PT_DPT_CENTS
    projection += EVAL_SURCHARGE[eval_complexity]
    return projection


# ---- MIPS quality score ----------------------------------------------------

MEASURE_CODES = ["Q126_PAIN_ASSESSMENT", "Q127_FUNCTIONAL_STATUS", "Q128_FALL_RISK_SCREEN"]


def mips_quality_score(mips_rows: Iterable[dict[str, Any]]) -> float:
    rows = list(mips_rows)
    per_measure_rates: list[Decimal] = []
    for code in MEASURE_CODES:
        applicable = [r for r in rows if r["measure_code"] == code and r["exception_reason"] == "NONE"]
        if not applicable:
            continue
        met = [r for r in applicable if r["numerator_met"] is True]
        rate = Decimal(len(met)) / Decimal(len(applicable))
        per_measure_rates.append(rate)
    if not per_measure_rates:
        return 0.00
    total = sum(per_measure_rates, Decimal(0))
    avg = total / Decimal(len(per_measure_rates)) * Decimal(100)
    quantized = avg.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(quantized)
