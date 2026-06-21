"""Calculation engine (PRD §3.9, §3.12, §3.13, §3.14; SCAFFOLD §1.3).

All monetary quantities are integer cents. Per-line items are rounded half-up
to whole cents individually, then summed (PRD §2.9).
"""
from decimal import Decimal, ROUND_HALF_UP

from db import db

# --- Constants (SCAFFOLD §1.3) ---
OR_MINUTE_RATE_CENTS = 1200
ANESTHESIA_BASE_CENTS = {"LOCAL": 0, "MAC": 18000, "REGIONAL": 32000, "GENERAL": 55000}
ADD_ON_SURCHARGE_CENTS = 40000

# overrun tiered penalty
TIER1_MIN = 15
TIER2_MIN = 45
TIER1_RATE_CENTS = 800
TIER2_RATE_CENTS = 1500
TIER3_RATE_CENTS = 3000

# asc payment grouping
MULTI_PROC_REDUCTION_PCT = 50
OFFICE_BASED_FLOOR_CENTS = 9000

# coverage load
SOLO_COVERAGE_CAP_MIN = 480


def round_half_up_cents(value):
    """Round a Decimal/number half-up to a whole integer (cent)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_1dp(value):
    """Round half-up to one decimal place, returned as float."""
    return float(Decimal(value).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _case_implants(case_id):
    return [ci for ci in db.case_implants.values() if ci["surgical_case_id"] == case_id]


def estimated_case_cost(case, procedure):
    """PRD §3.9 — forward-looking estimate from planned inputs.

    Sums only RESERVED implant rows using planned_qty; per-line round then sum.
    """
    labor_cents = procedure["scheduled_minutes"] * OR_MINUTE_RATE_CENTS
    anesthesia_cents = ANESTHESIA_BASE_CENTS[procedure["anesthesia_class"]]
    implant_cents = 0
    for ci in _case_implants(case["id"]):
        if ci["status"] != "RESERVED":
            continue
        supply = db.supply_items[ci["supply_item_id"]]
        implant_cents += round_half_up_cents(
            Decimal(supply["unit_cost_cents"]) * Decimal(ci["planned_qty"])
        )
    add_on_surcharge = ADD_ON_SURCHARGE_CENTS if case["is_add_on"] else 0
    return labor_cents + anesthesia_cents + implant_cents + add_on_surcharge


def overrun_tiered_penalty(overrun_min):
    """PRD §3.12 / SCAFFOLD §1.3 — marginal banding penalty.

    Band1: minutes 1..15 @ 800; Band2: 16..45 @ 1500; Band3: >45 @ 3000.
    """
    if overrun_min <= 0:
        return 0
    b1 = min(overrun_min, TIER1_MIN)
    b2 = min(max(overrun_min - TIER1_MIN, 0), TIER2_MIN - TIER1_MIN)
    b3 = max(overrun_min - TIER2_MIN, 0)
    return b1 * TIER1_RATE_CENTS + b2 * TIER2_RATE_CENTS + b3 * TIER3_RATE_CENTS


def actual_case_cost(case, procedure):
    """PRD §3.12 — actual cost at completion using recorded inputs.

    Sums only CONSUMED implant rows using consumed_qty; adds overrun penalty.
    """
    labor_cents = case["actual_minutes"] * OR_MINUTE_RATE_CENTS
    anesthesia_cents = ANESTHESIA_BASE_CENTS[procedure["anesthesia_class"]]
    implant_cents = 0
    for ci in _case_implants(case["id"]):
        if ci["status"] != "CONSUMED":
            continue
        supply = db.supply_items[ci["supply_item_id"]]
        implant_cents += round_half_up_cents(
            Decimal(supply["unit_cost_cents"]) * Decimal(ci["consumed_qty"])
        )
    add_on_surcharge = ADD_ON_SURCHARGE_CENTS if case["is_add_on"] else 0
    overrun_min = max(0, case["actual_minutes"] - procedure["scheduled_minutes"])
    overrun_penalty = overrun_tiered_penalty(overrun_min)
    return labor_cents + anesthesia_cents + implant_cents + add_on_surcharge + overrun_penalty


def asc_payment_grouping(case, procedure):
    """PRD §3.13 — CMS ASC payment grouping in 4 mandatory ordered steps.

    Must be called when the case is already COMPLETED (so implants are CONSUMED
    and the case appears among same-patient/day completed cases for ranking).
    """
    # STEP 1: base
    base = procedure["cms_base_rate_cents"]

    # STEP 2: device offset (only for DEVICE_INTENSIVE)
    if procedure["cms_payment_indicator"] == "DEVICE_INTENSIVE":
        device_consumed_cents = 0
        for ci in _case_implants(case["id"]):
            if ci["status"] != "CONSUMED":
                continue
            supply = db.supply_items[ci["supply_item_id"]]
            if not supply["is_device"]:
                continue
            device_consumed_cents += round_half_up_cents(
                Decimal(supply["unit_cost_cents"]) * Decimal(ci["consumed_qty"])
            )
        offset = round_half_up_cents(
            Decimal(base) * (Decimal(procedure["device_offset_pct"]) / Decimal(100))
        )
        device_offset = min(offset, device_consumed_cents)
        grouped = base + device_offset
    else:
        grouped = base

    # STEP 3: multiple-procedure reduction.
    # 2nd or later non-cancelled COMPLETED case for the SAME patient on the SAME
    # service_date, ordered by (start_min ASC, created_at ASC).
    siblings = [
        c for c in db.surgical_cases.values()
        if c["patient_id"] == case["patient_id"]
        and c["surgical_day_id"] == case["surgical_day_id"]
        and c["case_status"] == "COMPLETED"
    ]
    siblings.sort(key=lambda c: (c["start_min"], c["_seq"]))
    rank = next((i for i, c in enumerate(siblings) if c["id"] == case["id"]), 0)
    if rank >= 1:
        grouped = round_half_up_cents(
            Decimal(grouped) * (Decimal(1) - Decimal(MULTI_PROC_REDUCTION_PCT) / Decimal(100))
        )

    # STEP 4: OFFICE_BASED floor
    if procedure["cms_payment_indicator"] == "OFFICE_BASED":
        if grouped < OFFICE_BASED_FLOOR_CENTS:
            grouped = OFFICE_BASED_FLOOR_CENTS

    return grouped


def _overlap_minutes(start_a, end_a, start_b, end_b):
    """Overlap of two half-open intervals [start,end)."""
    lo = max(start_a, start_b)
    hi = min(end_a, end_b)
    return max(0, hi - lo)


def day_utilization(day):
    """PRD §3.14 — prime-time utilization percentage for a SurgicalDay.

    CLOSED days are frozen (caller must guard); this only computes.
    """
    cases = [
        c for c in db.surgical_cases.values()
        if c["surgical_day_id"] == day["id"] and c["case_status"] != "CANCELLED"
    ]
    # Denominator: distinct ORs that hosted >=1 non-cancelled case.
    or_ids = set(c["operating_room_id"] for c in cases if c.get("operating_room_id"))
    prime_capacity_min = 0
    for or_id in or_ids:
        room = db.operating_rooms[or_id]
        prime_capacity_min += room["prime_time_end_min"] - room["prime_time_start_min"]

    used_min = 0
    for c in cases:
        room = db.operating_rooms[c["operating_room_id"]]
        if c["case_status"] == "COMPLETED" and c.get("actual_minutes"):
            footprint_end = c["start_min"] + c["actual_minutes"]
        else:
            footprint_end = c["end_min"]
        used_min += _overlap_minutes(
            c["start_min"], footprint_end,
            room["prime_time_start_min"], room["prime_time_end_min"],
        )

    if prime_capacity_min == 0:
        return 0.0
    return round_half_up_1dp(Decimal(100) * Decimal(used_min) / Decimal(prime_capacity_min))


def day_booked_minutes(day):
    """PRD §3.3 — sum of scheduled_minutes over non-cancelled cases."""
    return sum(
        c["scheduled_minutes"] for c in db.surgical_cases.values()
        if c["surgical_day_id"] == day["id"] and c["case_status"] != "CANCELLED"
    )


def recompute_day(day):
    """Recompute booked_minutes and utilization_pct unless the day is CLOSED (frozen)."""
    if day["posture"] == "CLOSED":
        return
    day["booked_minutes"] = day_booked_minutes(day)
    day["utilization_pct"] = day_utilization(day)


def coverage_load(anesthesiologist_id, service_date, basis):
    """PRD §3.14 — projected (default) or actual anesthesia coverage load.

    Cases assigned to this anesthesiologist on the given service_date whose
    case_status != CANCELLED.
    """
    day_ids = set(
        d["id"] for d in db.surgical_days.values()
        if d["service_date"] == service_date
    )
    cases = [
        c for c in db.surgical_cases.values()
        if c.get("anesthesiologist_id") == anesthesiologist_id
        and c["surgical_day_id"] in day_ids
        and c["case_status"] != "CANCELLED"
    ]
    if basis == "ACTUAL":
        cases.sort(key=lambda c: (c["start_min"], c["_seq"]))
        minutes = 0
        for c in cases:
            if c["case_status"] == "COMPLETED" and c.get("actual_minutes") is not None:
                minutes += c["actual_minutes"]
            else:
                minutes += c["scheduled_minutes"]
    else:
        minutes = sum(c["scheduled_minutes"] for c in cases)

    coverage_load_pct = round_half_up_1dp(
        Decimal(100) * Decimal(minutes) / Decimal(SOLO_COVERAGE_CAP_MIN)
    )
    return minutes, coverage_load_pct
