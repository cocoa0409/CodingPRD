"""Forward-looking budget projection for a TravelApplication."""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import Decimal

from db import STORE
from errors import APIError, ERR_NO_ACTIVE_STANDARD
from services.standards import find_active_standard
from utils import CLOCK, DECLARED_HOLIDAYS, parse_ts, round_money


def _intersects_holiday(start_at, end_at) -> bool:
    """True if any calendar day in [start_at.date(), end_at.date()] is a declared holiday."""
    s = start_at.date()
    e = end_at.date()
    d = s
    while d <= e:
        if d.isoformat() in DECLARED_HOLIDAYS:
            return True
        d = d + timedelta(days=1)
    return False


def _planned_window_has_holiday(app) -> bool:
    ps = parse_ts(app["planned_start"])
    pe = parse_ts(app["planned_end"])
    return _intersects_holiday(ps, pe)


def project(app: dict) -> dict:
    """Forward projection using the CURRENTLY ACTIVE ExpenseStandard."""
    applicant = STORE.employees.get(app["applicant_id"])
    if not applicant:
        return {
            "application_id": app["id"],
            "projected_reimbursable": 0.0,
            "segments": [],
        }
    level = applicant["employee_level"]
    # For OVERSEAS travel_scope, city_tier lookup is OVERSEAS; else use destination_tier
    tier = "OVERSEAS" if app["travel_scope"] == "OVERSEAS" else app["destination_tier"]
    standard = find_active_standard(CLOCK.now(), city_tier=tier, employee_level=level)
    if standard is None:
        raise APIError(ERR_NO_ACTIVE_STANDARD,
                        f"No active ExpenseStandard for ({tier}, {level})",
                        422)
    holiday_mult = standard.get("holiday_multiplier") or Decimal("1.00")
    planned_holiday = _planned_window_has_holiday(app)

    seg_outputs = []
    total = Decimal("0.00")
    segments = [s for s in STORE.itinerary_segments.values()
                if s["application_id"] == app["id"] and s["status"] == "ACTIVE"]
    segments.sort(key=lambda s: s["created_at"])
    for seg in segments:
        s_at = parse_ts(seg["start_at"])
        e_at = parse_ts(seg["end_at"])
        seg_cost = seg["cost"]
        if seg["segment_type"] == "HOTEL":
            unit = standard["lodging_daily_cap"]
            delta_seconds = (e_at - s_at).total_seconds()
            nights = max(int(delta_seconds // 86400), 0)
            multiplier = Decimal(nights)
        else:
            unit = standard["transportation_daily_cap"]
            delta_seconds = (e_at - s_at).total_seconds()
            hours = delta_seconds / 3600.0
            days = math.ceil(hours / 24.0)
            multiplier = Decimal(days)
        if planned_holiday:
            unit_eff = unit * holiday_mult
        else:
            unit_eff = unit
        item_cap = unit_eff * multiplier
        item_cap = round_money(item_cap)
        contrib = min(seg_cost, item_cap)
        contrib = round_money(contrib)
        total += contrib
        seg_outputs.append({
            "segment_id": seg["id"],
            "segment_type": seg["segment_type"],
            "cost": float(seg_cost),
            "item_cap": float(item_cap),
            "projected_contribution": float(contrib),
        })

    total = round_money(total)
    return {
        "application_id": app["id"],
        "standard_version": standard["version"],
        "projected_reimbursable": float(total),
        "segments": seg_outputs,
    }
