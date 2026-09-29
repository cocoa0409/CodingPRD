"""Service months, watering compliance and warranty settlement (PRD 3.9, calcs 8-9)."""
import datetime
from decimal import Decimal

from helpers import logs_of_unit
from store import db
from util import floor_dec, q, q0
from services.constants import (
    CHEM_LEAD,
    HONORED_USAGE_CEILING,
    MONTH_DAYS,
    PRORATION_FULL_MULTIPLIER,
    PRORATION_FULL_RATIO,
    PRORATION_REDUCED_MULTIPLIER,
    WATERING_COMPLIANCE_FLOOR,
)

FULL_RATIO = Decimal("1.0000")


def months_in_service(unit, now):
    shipped_at = unit.get("shipped_at")
    if shipped_at is None:
        return 0
    elapsed = now - shipped_at
    if elapsed.total_seconds() <= 0:
        return 0
    return floor_dec(Decimal(str(elapsed.total_seconds())) / Decimal(MONTH_DAYS * 86400))


def cycle_count_from_logs(unit):
    total = 0
    for log in logs_of_unit(unit["id"]):
        if log.get("event_type") == "CYCLE_REPORT":
            total += log.get("cycles_delta") or 0
    return total


def watering_events_ok(unit, now):
    shipped_at = unit.get("shipped_at")
    count = 0
    for log in logs_of_unit(unit["id"]):
        if log.get("event_type") != "WATERING":
            continue
        if log.get("electrolyte_level_ok") is not True:
            continue
        performed = log.get("performed_at")
        if performed is None:
            continue
        if shipped_at is not None and performed < shipped_at:
            continue
        if performed > now:
            continue
        count += 1
    return count


def recompute_service_figures(unit, design, now=None):
    """Chemistry-conditional watering compliance plus the service month count."""
    now = now or db.now()
    months = months_in_service(unit, now)
    unit["months_in_service"] = months
    unit["cycle_count"] = cycle_count_from_logs(unit)
    if design.get("chemistry") != CHEM_LEAD:
        unit["watering_events_expected"] = 0
        unit["watering_events_ok"] = 0
        unit["watering_compliance_ratio"] = FULL_RATIO
        return unit
    expected = months * 1
    achieved = watering_events_ok(unit, now)
    unit["watering_events_expected"] = expected
    unit["watering_events_ok"] = achieved
    if expected == 0:
        unit["watering_compliance_ratio"] = FULL_RATIO
    else:
        ratio = Decimal(achieved) / Decimal(expected)
        unit["watering_compliance_ratio"] = q(min(Decimal("1.0"), ratio), 4)
    return unit


def cycle_usage_fraction(unit, design):
    rated = Decimal(design["rated_cycles"])
    return q(Decimal(unit.get("cycle_count", 0)) / rated, 4)


def combined_usage_fraction(unit, design):
    """The larger of the cycle fraction and the calendar fraction."""
    cycle = Decimal(unit.get("cycle_count", 0)) / Decimal(design["rated_cycles"])
    calendar = Decimal(unit.get("months_in_service", 0)) / Decimal(design["warranty_months"])
    return q(max(cycle, calendar), 4)


def settlement(unit, design, inspection_finding, usage):
    """Calculation 9: the first gate that fires decides everything."""
    if inspection_finding == "NO_DEFECT_FOUND":
        return "DENIED_NO_DEFECT", 0, "CLAIM_DENIED"
    if usage >= FULL_RATIO:
        return "DENIED_USAGE", 0, "CLAIM_DENIED"
    if design.get("chemistry") == CHEM_LEAD and unit["watering_compliance_ratio"] < WATERING_COMPLIANCE_FLOOR:
        return "DENIED_MAINTENANCE", 0, "CLAIM_DENIED"
    if usage <= HONORED_USAGE_CEILING:
        return "HONORED", int(unit["list_price_cents"]), "CLAIM_HONORED"
    multiplier = (
        PRORATION_FULL_MULTIPLIER
        if unit["watering_compliance_ratio"] >= PRORATION_FULL_RATIO
        else PRORATION_REDUCED_MULTIPLIER
    )
    credit = q0(Decimal(unit["list_price_cents"]) * (Decimal("1") - usage) * multiplier)
    return "PRORATED", credit, "CLAIM_PRORATED"
