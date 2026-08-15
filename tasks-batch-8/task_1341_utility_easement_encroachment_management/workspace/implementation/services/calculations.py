"""Calculation rules (SCAFFOLD 1.3 / PRD 2.6, 3.2-3.6). All money is integer
cents; rounding is half-up everywhere; scores use Decimal arithmetic."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from constants import (
    PERMIT_BASE_RATES,
    STRUCTURE_RETENTION_BUFFER_DAYS,
    TIER_WEIGHTS,
)
from util import parse_ts_stored, round_half_up_dp, round_half_up_int
import db


# ---------------------------------------------------------------------------
# base_compensation (offer creation):
#   base = round_half_up(offered_area_sqft * fair_market_value_per_sqft * 100)
# ---------------------------------------------------------------------------

def base_compensation_cents(offered_area_sqft: Decimal, fmv_per_sqft: Decimal) -> int:
    return round_half_up_int(offered_area_sqft * fmv_per_sqft * Decimal(100))


# ---------------------------------------------------------------------------
# severity_tier (encroachment create; re-derive on supersede)
# ---------------------------------------------------------------------------

def severity_tier(encroachment_type: str, area_sqft: Decimal, depth_ft: Decimal,
                  doc_width_ft: Decimal, case_area_sqft: Decimal) -> str:
    if doc_width_ft == 0 or case_area_sqft == 0:
        depth_ratio = Decimal(0)
        area_ratio = Decimal(0)
    else:
        depth_ratio = depth_ft / doc_width_ft
        area_ratio = area_sqft / case_area_sqft

    if encroachment_type == "UTILITY_CROSSING":
        base_score = Decimal(4)
    elif encroachment_type == "STRUCTURE":
        base_score = Decimal(3)
    elif encroachment_type in ("FENCE", "PAVEMENT"):
        base_score = Decimal(2)
    else:  # VEGETATION, OTHER
        base_score = Decimal(1)

    if area_ratio >= Decimal("0.25"):
        depth_multiplier = Decimal("2.0")
    elif area_ratio >= Decimal("0.10"):
        depth_multiplier = Decimal("1.5")
    else:
        depth_multiplier = Decimal("1.0")

    raw = base_score * (Decimal(1) + depth_ratio * depth_multiplier)
    raw = round_half_up_dp(raw, 3)  # score to 3 decimal places

    if raw >= Decimal("6.0"):
        return "CRITICAL"
    if raw >= Decimal("3.5"):
        return "SEVERE"
    if raw >= Decimal("1.8"):
        return "MODERATE"
    return "MINOR"


# ---------------------------------------------------------------------------
# encroachment_pressure_score (case-level; 2dp half-up)
# ---------------------------------------------------------------------------

def encroachment_pressure_score(case_id: str) -> float:
    from constants import ENCROACHMENT_TERMINAL

    now = db.get_clock_dt()
    total = Decimal(0)
    for enc in db.encroachments.values():
        if enc["case_id"] != case_id or enc["status"] in ENCROACHMENT_TERMINAL:
            continue
        weight = Decimal(TIER_WEIGHTS.get(enc.get("severity_tier") or "MINOR", 1))
        created = parse_ts_stored(enc.get("created_at"))
        age_seconds = max(0.0, (now - created).total_seconds()) if created else 0.0
        age_days = int(age_seconds // 86400)
        age_multiplier = Decimal(1) + Decimal(min(age_days, 90)) * Decimal("0.01")
        total += weight * age_multiplier
    return float(round_half_up_dp(total, 2))


# ---------------------------------------------------------------------------
# permit_fee (tiered; per-bracket rounding pinned)
# ---------------------------------------------------------------------------

def annual_fee_cents(permit_type: str, requested_area_sqft: Decimal) -> int:
    base = PERMIT_BASE_RATES[permit_type]
    area = requested_area_sqft
    if area <= 500:
        area_component = round_half_up_int(area * Decimal(12))
    elif area <= 2000:
        area_component = round_half_up_int(
            Decimal(500) * 12 + (area - Decimal(500)) * 8
        )
    else:
        area_component = round_half_up_int(
            Decimal(500) * 12 + Decimal(1500) * 8 + (area - Decimal(2000)) * 5
        )
    return base + area_component


# ---------------------------------------------------------------------------
# encumbrance_rank: among the case's RECORDED documents, sort by
# recording_date ASC, tie created_at ASC (never id); 1-based position.
# ---------------------------------------------------------------------------

def recompute_encumbrance_ranks(case_id: str) -> None:
    recorded = [
        d for d in db.documents.values()
        if d["case_id"] == case_id and d["status"] == "RECORDED"
    ]
    recorded.sort(key=lambda d: (d.get("recording_date") or "", d.get("created_at") or "", d.get("_seq", 0)))
    for position, doc in enumerate(recorded, start=1):
        if doc.get("encumbrance_rank") != position:
            doc["encumbrance_rank"] = position
            db.touch(doc)


# ---------------------------------------------------------------------------
# vegetation_excess_height (1dp half-up)
# ---------------------------------------------------------------------------

def excess_height_ft(zone: dict, observed_height_ft: Decimal, location: str) -> float:
    max_height = Decimal(str(zone["max_allowed_height_ft"]))
    wire_width = Decimal(str(zone["wire_zone_width_ft"]))
    if wire_width > 0 and location == "WIRE_ZONE":
        applicable_limit = max_height * Decimal("0.5")
    else:
        applicable_limit = max_height
    excess = observed_height_ft - applicable_limit
    if excess < 0:
        excess = Decimal(0)
    return float(round_half_up_dp(excess, 1))


# ---------------------------------------------------------------------------
# title_clearance_check
# ---------------------------------------------------------------------------

def title_cleared(case_id: str) -> bool:
    tasks = [t for t in db.title_tasks.values() if t["case_id"] == case_id]
    latest = None
    for task in tasks:
        if latest is None or (task["created_at"], task["_seq"]) > (latest["created_at"], latest["_seq"]):
            latest = task
    has_recorded = any(
        d["case_id"] == case_id and d["status"] == "RECORDED"
        for d in db.documents.values()
    )
    return bool(latest is not None and latest["status"] == "COMPLETED_CLEAN" and has_recorded)


# ---------------------------------------------------------------------------
# overlap_window_check (permit approval)
#   Half-open overlap; touching intervals (end == start) do NOT overlap.
#   STRUCTURE_RETENTION permits inflate their own window by 30 days per side.
#   Two APPROVED permits collide when their (possibly inflated) windows
#   overlap AND (same permit_type OR either side is STRUCTURE_RETENTION).
# ---------------------------------------------------------------------------

def _window(permit: dict) -> tuple:
    start = parse_ts_stored(permit["requested_start_date"])
    end = parse_ts_stored(permit["requested_end_date"])
    if permit["permit_type"] == "STRUCTURE_RETENTION":
        buffer = timedelta(days=STRUCTURE_RETENTION_BUFFER_DAYS)
        start = start - buffer
        end = end + buffer
    return start, end


def windows_overlap(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def permit_conflicts(new_permit: dict, other: dict) -> bool:
    if other["approval_status"] != "APPROVED":
        return False
    ns, ne = _window(new_permit)
    os_, oe = _window(other)
    if not windows_overlap(ns, ne, os_, oe):
        return False
    if new_permit["permit_type"] == other["permit_type"]:
        return True
    # Different types collide only when a STRUCTURE_RETENTION permit is
    # involved (its buffered maintenance window intersects the other's area).
    return (
        new_permit["permit_type"] == "STRUCTURE_RETENTION"
        or other["permit_type"] == "STRUCTURE_RETENTION"
    )
