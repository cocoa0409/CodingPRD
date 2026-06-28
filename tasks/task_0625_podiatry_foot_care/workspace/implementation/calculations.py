"""Calculation rules (PRD §3, SCAFFOLD §1.3). All money in integer cents.

Rounding is round-half-up where (and only where) the PRD invokes it: the payer
portion of a covered charge (§3.5) and each lab-order line (§3.7). The patient
remainder is the exact integer difference, not independently rounded (§2.8).
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

ROUTINE_KINDS = ("ROUTINE_NAIL_DEBRIDEMENT", "ROUTINE_CALLUS_PARING")

# Recall cadence by diabetic-foot risk category (PRD §3.10).
RECALL_INTERVAL_BY_CATEGORY = {0: 365, 1: 180, 2: 90, 3: 30}


def round_half_up(value):
    """Round a Decimal/number to the nearest whole cent, ties going up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def diabetic_foot_risk_category(patient):
    """Derived IWGDF-style category 0..3, highest applicable wins (PRD §3.2).

    if prior:                          3
    elif lops and (pad or deformity):  2
    elif lops:                         1
    else:                              0
    """
    lops = bool(patient.get("has_loss_protective_sensation"))
    pad = bool(patient.get("has_peripheral_arterial_disease"))
    deformity = bool(patient.get("has_foot_deformity"))
    prior = bool(patient.get("has_prior_ulcer_or_amputation"))
    if prior:
        return 3
    if lops and (pad or deformity):
        return 2
    if lops:
        return 1
    return 0


def _parse_iso_date(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def add_days(iso_date_str, days):
    """anchor_date advanced by `days` whole calendar days; returns ISO date str."""
    from datetime import timedelta
    base = _parse_iso_date(iso_date_str)
    result = base + timedelta(days=days)
    return result.isoformat()


def day_gap(later_iso, earlier_iso):
    """Whole calendar days from earlier to later (later - earlier)."""
    return (_parse_iso_date(later_iso) - _parse_iso_date(earlier_iso)).days


def is_routine(procedure_kind):
    return procedure_kind in ROUTINE_KINDS


def procedure_coverage_decision(procedure, patient, practice):
    """Decide coverage for a single procedure at coding time (PRD §3.4)."""
    if not procedure["is_routine"]:
        return "COVERED"  # wound debridement / nail avulsion always coverable
    if not patient.get("has_diabetes_mellitus"):
        return "DENIED_NO_QUALIFYING_DX"
    last = patient.get("last_covered_routine_care_date")
    if last is None:
        return "COVERED"  # no prior covered routine care -> eligible
    gap = day_gap(procedure["service_date"], last)
    if gap >= practice["routine_care_min_interval_days"]:
        return "COVERED"  # boundary inclusive
    return "DENIED_FREQUENCY"


def charge_split(billed_cents, fee_cap_cents, coverage_decision, fee_split_pct):
    """Split one line into (medicare_pays_cents, patient_resp_cents) (PRD §3.5).

    allowed = min(billed, cap).
    COVERED: medicare = round_half_up(allowed * pct); patient = allowed - medicare.
    DENIED_*: medicare = 0; patient = full billed (uncapped).
    """
    if coverage_decision == "COVERED":
        allowed = min(billed_cents, fee_cap_cents)
        medicare = round_half_up(Decimal(allowed) * Decimal(str(fee_split_pct)))
        patient = allowed - medicare
        return medicare, patient
    # DENIED_FREQUENCY or DENIED_NO_QUALIFYING_DX
    return 0, billed_cents


def lab_order_total(line_items):
    """Per-line round-then-sum (PRD §3.7).

    raw_line = unit_price_cents * quantity * (1 - discount_pct)
    line_cents = round_half_up(raw_line); total = sum of line_cents.
    """
    total = 0
    for item in line_items:
        unit_price = Decimal(str(item["unit_price_cents"]))
        quantity = Decimal(str(item["quantity"]))
        discount = Decimal(str(item["discount_pct"]))
        raw_line = unit_price * quantity * (Decimal(1) - discount)
        total += round_half_up(raw_line)
    return total


def recall_interval_days(category):
    return RECALL_INTERVAL_BY_CATEGORY[category]
