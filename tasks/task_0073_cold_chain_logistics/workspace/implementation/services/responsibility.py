"""Responsibility split advisory calculation."""

from __future__ import annotations

from decimal import Decimal

from clock import clock, parse_iso8601
from db import db
from services.precision import round_half_up_2


PARTIES = ("SHIPPER", "CARRIER", "CONSIGNEE")
# Tie-break order for remainder allocation: CARRIER > CONSIGNEE > SHIPPER
# (higher means picked first when shares are tied)
TIE_BREAK_RANK = {"CARRIER": 0, "CONSIGNEE": 1, "SHIPPER": 2}


def _principal_to_party(task: dict, principal_id: str) -> str | None:
    """Map a HandoverRecord's party-id to one of SHIPPER/CARRIER/CONSIGNEE.
    The driver acts on behalf of the carrier, so a driver_id resolves to CARRIER.
    """
    if principal_id is None:
        return None
    if principal_id == task.get("shipper_id"):
        return "SHIPPER"
    if principal_id == task.get("carrier_id"):
        return "CARRIER"
    if principal_id == task.get("consignee_id"):
        return "CONSIGNEE"
    # A driver acts on behalf of the carrier
    driver_id = task.get("driver_id")
    if driver_id is not None and principal_id == driver_id:
        return "CARRIER"
    # Check Driver rows for the id (driver_id may not be set, but principal could be a driver row id)
    drv = db.drivers.get(principal_id)
    if drv is not None:
        return "CARRIER"
    return None


def _build_custody_segments(task: dict):
    """Build per-party time-in-custody segments from the handover chain.

    Segments are [(party, start_dt, end_dt), ...]. Initial party is SHIPPER; each
    handover at time t closes the current segment at t and opens a new one held by
    the receiving party. End of final segment is current_clock if task is still
    running, or the closed_at / latest known time. We use a far-future sentinel
    so overlap math is straightforward.
    """
    handovers = db.handovers_for_task(task["id"])
    planned_start = parse_iso8601(task["planned_start_at"])
    if task.get("closed_at"):
        last_end = parse_iso8601(task["closed_at"])
    else:
        last_end = max(clock.now(), parse_iso8601(task["planned_end_at"]) or clock.now())

    segments = []
    current_party = "SHIPPER"
    current_start = planned_start
    for h in handovers:
        boundary = parse_iso8601(h["handed_over_at"])
        if boundary is None:
            continue
        segments.append((current_party, current_start, boundary))
        # The party receiving the cargo holds custody from this moment forward
        next_party = _principal_to_party(task, h.get("to_party_id"))
        if next_party is None:
            next_party = current_party
        current_party = next_party
        current_start = boundary
    segments.append((current_party, current_start, last_end))
    return segments


def _overlap_seconds(a_start, a_end, b_start, b_end) -> Decimal:
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return Decimal("0")
    start = max(a_start, b_start)
    end = min(a_end, b_end)
    if end <= start:
        return Decimal("0")
    return Decimal(str((end - start).total_seconds()))


def compute_advisory(decision: dict) -> dict:
    """Compute advisory_split per the configured split_method.
    Returns dict { 'shipper_pct': float, 'carrier_pct': float, 'consignee_pct': float }
    summing to 1.00 exactly (after remainder allocation).
    """
    task = db.tasks.get(decision["task_id"])
    assessment = db.assessments.get(decision["assessment_id"])
    if task is None or assessment is None:
        return {"shipper_pct": 0.0, "carrier_pct": 0.0, "consignee_pct": 0.0}

    evidence_alert_ids = assessment.get("evidence_alert_ids", [])
    evidence_alerts = [db.alerts.get(aid) for aid in evidence_alert_ids if db.alerts.exists(aid)]
    segments = _build_custody_segments(task)

    weights = {p: Decimal("0") for p in PARTIES}

    method = decision["split_method"]
    if method == "DURATION_WEIGHTED":
        for a in evidence_alerts:
            opened_at = parse_iso8601(a["opened_at"])
            resolved_at = parse_iso8601(a.get("resolved_at")) if a.get("resolved_at") else clock.now()
            for party, seg_start, seg_end in segments:
                if party not in weights:
                    continue
                weights[party] += _overlap_seconds(opened_at, resolved_at, seg_start, seg_end)
    elif method == "SEVERITY_WEIGHTED":
        for a in evidence_alerts:
            opened_at = parse_iso8601(a["opened_at"])
            peak = Decimal(str(a.get("peak_deviation_celsius", 0) or 0))
            # Attribute to the party whose segment covers opened_at
            attributed = None
            for party, seg_start, seg_end in segments:
                if seg_start is None or seg_end is None:
                    continue
                if seg_start <= opened_at < seg_end:
                    attributed = party
                    break
            if attributed is None and segments:
                # Fallback to last segment's party (defensive)
                attributed = segments[-1][0]
            if attributed in weights:
                weights[attributed] += peak

    total = sum(weights.values())
    if total <= 0:
        # No evidence/no weight — split evenly
        return {"shipper_pct": 0.34, "carrier_pct": 0.33, "consignee_pct": 0.33}

    raw_pct = {p: (weights[p] / total) for p in PARTIES}
    rounded = {p: round_half_up_2(raw_pct[p]) for p in PARTIES}

    # Allocate any remainder cents (each pct is 0.01 granularity over total of 1.00 = 100 cents)
    total_cents = sum(int(rounded[p] * 100) for p in PARTIES)
    remainder = 100 - total_cents
    if remainder != 0:
        # Sort parties by pre-round share descending; ties broken alphabetically
        # (CARRIER > CONSIGNEE > SHIPPER => CARRIER picked first when tied)
        sorted_parties = sorted(
            PARTIES,
            key=lambda p: (-raw_pct[p], TIE_BREAK_RANK[p]),
        )
        # Apply +1/-1 cents to the top party until balanced
        if remainder > 0:
            target = sorted_parties[0]
            rounded[target] = rounded[target] + Decimal("0.01") * remainder
        else:
            # Remove cents from top party
            target = sorted_parties[0]
            rounded[target] = rounded[target] + Decimal("0.01") * remainder

    return {
        "shipper_pct": float(rounded["SHIPPER"]),
        "carrier_pct": float(rounded["CARRIER"]),
        "consignee_pct": float(rounded["CONSIGNEE"]),
    }


def attach_advisory(decision: dict):
    """Compute advisory_split and store on decision."""
    advisory = compute_advisory(decision)
    decision["advisory_split"] = advisory
    return decision
