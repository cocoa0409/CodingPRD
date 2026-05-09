"""Calculation rules from SCAFFOLD §1.3 / PRD §3.

All monetary values are integer cents (no floats). Cold-chain temperatures
are integer celsius_tenths (degrees Celsius × 10). Vendor weighted score
is rounded half-up to one decimal place.
"""

from __future__ import annotations

import math
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from db import db, parse_iso

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Cold-chain
COLD_RANGE_LOW_TENTHS = 20
COLD_RANGE_HIGH_TENTHS = 80
CRITICAL_LOW_TENTHS = 0
CRITICAL_HIGH_TENTHS = 150
MILD_SEVERITY = 1
CRITICAL_SEVERITY = 5
COLD_CHAIN_DISPOSE_THRESHOLD = 30

# Vendor scoring
ALERT_DAYS = 30
GREEN_MULT = Decimal("1.0")
YELLOW_MULT = Decimal("1.5")
RED_MULT = Decimal("2.0")

# ADR
SERIOUS_DEADLINE_HOURS = 24
NON_SERIOUS_DEADLINE_DAYS = 15
GRACE_HOURS = 0
FOLLOW_UP_DAYS = 7

# Pharmacist review
MAX_REVISIONS = 2

# Prescription validity caps per control_category (server-side cap; PRD §3.4
# leaves these implicit but tests exercise the validity_days field directly).
VALIDITY_DAYS_CAP = {
    "NONE": 365,
    "PSYCHOTROPIC_II": 365,
    "PSYCHOTROPIC_I": 365,
    "NARCOTIC": 365,
    "TOXIC": 365,
}


# ---------------------------------------------------------------------------
# Order total
# ---------------------------------------------------------------------------


def order_total_cents(items: Iterable[dict]) -> int:
    """Sum qty * unit_price_cents over items. Pure integer arithmetic."""
    total = 0
    for line in items:
        qty = int(line["qty"])
        unit = int(line["unit_price_cents"])
        total += qty * unit
    return total


# ---------------------------------------------------------------------------
# Cold-chain excursion score (SCAFFOLD §1.3 cold_chain_excursion_score)
# ---------------------------------------------------------------------------


def _severity_for(celsius_tenths: int) -> int:
    if COLD_RANGE_LOW_TENTHS <= celsius_tenths <= COLD_RANGE_HIGH_TENTHS:
        return 0
    if celsius_tenths < CRITICAL_LOW_TENTHS or celsius_tenths > CRITICAL_HIGH_TENTHS:
        return CRITICAL_SEVERITY
    return MILD_SEVERITY


def excursion_score(readings: list[dict]) -> int:
    """Sort by recorded_at ASC; per-reading score = severity * window_minutes;
    sum after multiplication. Window for last reading = 1.

    Order is pinned: per-reading product first, THEN sum.
    """
    if not readings:
        return 0
    sorted_r = sorted(readings, key=lambda r: parse_iso(r["recorded_at"]))
    n = len(sorted_r)
    total = 0
    for i, r in enumerate(sorted_r):
        sev = _severity_for(int(r["celsius_tenths"]))
        if i < n - 1:
            delta = (
                parse_iso(sorted_r[i + 1]["recorded_at"]) - parse_iso(r["recorded_at"])
            ).total_seconds()
            window_minutes = max(1, math.ceil(delta / 60.0))
        else:
            window_minutes = 1
        total += sev * window_minutes
    return total


# ---------------------------------------------------------------------------
# ADR reporting deadline (forward-looking, anchored at original reported_at)
# ---------------------------------------------------------------------------


def reporting_deadline(reported_at_iso: str, severity: str):
    base = parse_iso(reported_at_iso)
    if severity == "SERIOUS":
        return base + _td(hours=SERIOUS_DEADLINE_HOURS)
    return base + _td(days=NON_SERIOUS_DEADLINE_DAYS)


def follow_up_due(submitted_at_iso: str):
    return parse_iso(submitted_at_iso) + _td(days=FOLLOW_UP_DAYS)


def _td(*, hours: int = 0, days: int = 0):
    import datetime as _dt

    return _dt.timedelta(hours=hours, days=days)


# ---------------------------------------------------------------------------
# Vendor qualification weighted score (SCAFFOLD §1.3 vendor_qualification_review_score)
# ---------------------------------------------------------------------------


def _component_score(days_remaining: int | None) -> int:
    if days_remaining is None:
        return 0  # +∞ sentinel — does not contribute
    if days_remaining >= 90:
        return 0
    if days_remaining >= 30:
        return 1
    if days_remaining >= 0:
        return 3
    return 5


def vendor_score(platform: dict, vendor: dict) -> dict:
    """Computes the weighted score and tier per SCAFFOLD §1.3.

    Returns dict with keys: l_days, p_days, c_days, raw_total, tier, weighted_score.
    """
    clock = parse_iso(platform["current_clock_iso"])
    l_exp = parse_iso(vendor["business_license_expires_at"])
    p_exp = parse_iso(vendor["drug_operation_permit_expires_at"])
    l_days = math.floor((l_exp - clock).total_seconds() / 86400)
    p_days = math.floor((p_exp - clock).total_seconds() / 86400)

    pharms = [
        ph for ph in db.pharmacists.values() if ph.get("platform_id") == platform["id"]
    ]
    if pharms:
        c_days = min(
            math.floor((parse_iso(ph["certificate_expires_at"]) - clock).total_seconds() / 86400)
            for ph in pharms
        )
    else:
        c_days = None  # +∞ sentinel

    raw_total = (
        _component_score(l_days)
        + _component_score(p_days)
        + _component_score(c_days)
    )

    if raw_total <= 1:
        tier = "GREEN"
        mult = GREEN_MULT
    elif raw_total <= 4:
        tier = "YELLOW"
        mult = YELLOW_MULT
    else:
        tier = "RED"
        mult = RED_MULT

    weighted = (Decimal(raw_total) * mult).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)

    return {
        "l_days": l_days,
        "p_days": p_days,
        "c_days": c_days,
        "raw_total": raw_total,
        "tier": tier,
        "weighted_score": weighted,
    }
