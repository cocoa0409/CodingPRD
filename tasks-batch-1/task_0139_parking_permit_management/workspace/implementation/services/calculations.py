"""Calculation rules (scaffold §1.3 / PRD §3.6, §3.7, §3.8, §3.9).

All money is integer cents. round_half_up is applied only at multiplier steps;
ceil for hour/day block counts; floor for the PERCENT discount divide.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional

import db

MINUTES_PER_HOUR = 60
MINUTES_PER_DAY = 1440
PERCENT_BASE = 100


def round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def minutes_between(entry_iso: str, exit_iso: str) -> int:
    """Whole minutes between two UTC instants (truncated toward zero)."""
    a = db.parse_iso_dt(entry_iso)
    b = db.parse_iso_dt(exit_iso)
    delta = (b - a).total_seconds()
    return int(delta // 60)


# ---------------------------------------------------------------------------
# §3.6 transient_charge
# ---------------------------------------------------------------------------


def select_event_window(garage_id: str, entry_iso: str) -> Optional[Dict[str, Any]]:
    """Among the garage's PUBLISHED event-pricing windows, pick the single one
    whose half-open [window_start_utc, window_end_utc) contains entry_at_utc.
    If several qualify, choose the latest window_start_utc; break ties on the
    earliest created_at."""
    entry = db.parse_iso_dt(entry_iso)
    candidates = []
    for ev in db.event_pricing.values():
        if ev["garage_id"] != garage_id:
            continue
        if ev["status"] != "PUBLISHED":
            continue
        ws = db.parse_iso_dt(ev["window_start_utc"])
        we = db.parse_iso_dt(ev["window_end_utc"])
        if ws <= entry < we:
            candidates.append(ev)
    if not candidates:
        return None
    # Pick the latest window_start_utc; break ties on the earliest created_at
    # (smallest insertion _seq).
    best = None
    for ev in candidates:
        if best is None:
            best = ev
            continue
        bw = db.parse_iso_dt(best["window_start_utc"])
        ew = db.parse_iso_dt(ev["window_start_utc"])
        if ew > bw or (ew == bw and ev["_seq"] < best["_seq"]):
            best = ev
    return best


def transient_charge(session: Dict[str, Any], rate_plan: Dict[str, Any]) -> int:
    """Compute gross_charge_cents at exit for a TRANSIENT session (§3.6).

    PERMIT sessions are billed 0 by the caller; this function assumes TRANSIENT.
    """
    duration_min = minutes_between(session["entry_at_utc"], session["exit_at_utc"])

    grace = rate_plan.get("grace_minutes", 15)
    if duration_min <= grace:
        return 0

    # Each started hour is billed (ceil), measured from entry.
    billable_hours = math.ceil(duration_min / MINUTES_PER_HOUR)
    metered_cents = billable_hours * rate_plan["hourly_cents"]

    event = select_event_window(session["garage_id"], session["entry_at_utc"])
    if event is not None:
        metered_cents = round_half_up(Decimal(metered_cents) * Decimal(str(event["multiplier"])))

    # Daily cap (after the multiplier).
    cap_blocks = math.ceil(duration_min / MINUTES_PER_DAY)
    metered_cents = min(metered_cents, cap_blocks * rate_plan["daily_cap_cents"])

    gross = metered_cents
    if event is not None:
        gross = gross + event["flat_surcharge_cents"]
    return gross


# ---------------------------------------------------------------------------
# §3.7 validation_discount
# ---------------------------------------------------------------------------


def validation_discount(
    gross: int,
    validation: Dict[str, Any],
    merchant: Dict[str, Any],
    rate_plan: Dict[str, Any],
) -> Dict[str, int]:
    """Returns {applied_discount, net}. (§3.7)"""
    kind = validation["discount_kind"]
    value = validation["discount_value"]

    if kind == "FLAT_CENTS":
        raw_discount = value
    elif kind == "PERCENT":
        raw_discount = (gross * value) // PERCENT_BASE  # floor
    elif kind == "FREE_HOURS":
        raw_discount = value * rate_plan["hourly_cents"]
    else:
        raw_discount = 0

    applied_discount = min(raw_discount, gross, merchant["validation_budget_cents"])
    net = gross - applied_discount
    return {"applied_discount": applied_discount, "net": net}


# ---------------------------------------------------------------------------
# §3.9 citation_fine
# ---------------------------------------------------------------------------


def citation_fine(base_fine_cents: int, plate: str) -> Dict[str, int]:
    """Compute escalated amount_due_cents + prior_citation_count snapshot.

    prior_count = citations for the SAME plate with status IN {ISSUED, UPHELD}.
    """
    prior_count = sum(
        1
        for c in db.citations.values()
        if c["plate"] == plate and c["status"] in ("ISSUED", "UPHELD")
    )
    if prior_count == 0:
        mult = Decimal("1.00")
    elif prior_count == 1:
        mult = Decimal("1.50")
    elif prior_count == 2:
        mult = Decimal("2.00")
    else:
        mult = Decimal("3.00")
    amount_due = round_half_up(Decimal(base_fine_cents) * mult)
    return {"amount_due_cents": amount_due, "prior_citation_count": prior_count}


# ---------------------------------------------------------------------------
# §3.8 lpr_enforcement
# ---------------------------------------------------------------------------


def lpr_enforcement(garage_id: str, plate: str, zone_id: str) -> Dict[str, Any]:
    """Evaluate a plate read; returns {enforcement_outcome, matched_permit_id}."""
    # 1. OPEN session for (garage, plate)?
    for s in db.sessions.values():
        if s["garage_id"] == garage_id and s["plate"] == plate and s["status"] == "OPEN":
            return {"enforcement_outcome": "COMPLIANT", "matched_permit_id": None}

    now = db.clock_now()

    # 2. ACTIVE permit for plate in this zone?
    for p in db.permits.values():
        if p["plate"] == plate and p["zone_id"] == zone_id and p["status"] == "ACTIVE":
            vu = db.parse_iso_dt(p.get("valid_until_utc"))
            if vu is not None and now >= vu:
                return {
                    "enforcement_outcome": "VIOLATION_EXPIRED_PERMIT",
                    "matched_permit_id": p["id"],
                }
            return {"enforcement_outcome": "COMPLIANT", "matched_permit_id": p["id"]}

    # 3. ACTIVE permit for plate in a DIFFERENT zone of the same garage?
    for p in db.permits.values():
        if p["plate"] == plate and p["status"] == "ACTIVE" and p["zone_id"] != zone_id:
            z = db.zones.get(p["zone_id"])
            if z is not None and z["garage_id"] == garage_id:
                return {
                    "enforcement_outcome": "VIOLATION_WRONG_ZONE",
                    "matched_permit_id": p["id"],
                }

    # 4. No permit, no open session.
    return {"enforcement_outcome": "VIOLATION_NO_PERMIT", "matched_permit_id": None}
