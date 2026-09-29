"""Compliance sweep (PRD 3.10)."""
from datetime import timedelta
from decimal import Decimal

from db import clock_dt, clock_str, db, touch
from services.domain import (DRILL_COMPLIANCE_FLOOR, UTILIZATION_SWEEP_FLOOR,
                             get_practice, ordered)
from services.permit import sweep_expire, sweep_suspend, to_probation
from services.practice import refresh_permit_ratio, touch_practice
from services.scheduling import recompute_block
from timeutil import parse_date


def _permits(practice_id):
    rows = [p for p in db.permits.values()
            if practice_id is None or p["practice_id"] == practice_id]
    return ordered(rows)


def _blocks(practice_id):
    rows = [b for b in db.blocks.values()
            if practice_id is None or b["practice_id"] == practice_id]
    return ordered(rows)


def run_sweep(practice_id=None):
    now = clock_dt()
    permits_expired_ids = []
    permits_suspended_ids = []
    cases_cancelled = 0
    reservations_released = 0

    # Expiry pass first, so an expired permit is never also counted as newly on probation.
    for permit in _permits(practice_id):
        if permit["status"] not in ("ACTIVE", "PROBATION"):
            continue
        expires_at = permit.get("expires_at")
        if not expires_at:
            continue
        if now < parse_date(expires_at):
            continue
        practice = get_practice(permit["practice_id"])
        cancelled, released = sweep_expire(permit, practice)
        cases_cancelled += cancelled
        reservations_released += released
        permits_expired_ids.append(permit["id"])

    # Drill pass over the permits that survived the expiry pass.
    for permit in _permits(practice_id):
        if permit["status"] != "ACTIVE":
            continue
        ratio = refresh_permit_ratio(permit)
        if ratio < DRILL_COMPLIANCE_FLOOR:
            practice = get_practice(permit["practice_id"])
            to_probation(permit, practice, "DRILL_LAPSE")
            touch_practice(practice)

    # Probation windows that closed without an attestation escalate to SUSPENDED.
    for permit in _permits(practice_id):
        if permit["status"] != "PROBATION":
            continue
        deadline = permit.get("remediation_deadline_at")
        if not deadline:
            continue
        if not now > parse_date(deadline):
            continue
        practice = get_practice(permit["practice_id"])
        cancelled, released = sweep_suspend(permit, practice, "DRILL_LAPSE")
        cases_cancelled += cancelled
        reservations_released += released
        permits_suspended_ids.append(permit["id"])

    blocks_released = 0
    blocks_partially_released = 0
    for block in _blocks(practice_id):
        if block["status"] != "RESERVED":
            continue
        recompute_block(block)
        deadline = parse_date(block["block_start"]) - timedelta(
            hours=int(block.get("release_deadline_hours") or 0))
        if now < deadline:
            continue
        duration = int(block["block_duration_minutes"])
        committed = int(block["committed_minutes"])
        if committed == 0:
            block["status"] = "RELEASED"
            block["released_minutes"] = duration
            block["open_minutes"] = 0
            recompute_block(block)
            block["open_minutes"] = 0
            touch(block)
            blocks_released += 1
        elif Decimal(str(block["utilization_pct"])) < UTILIZATION_SWEEP_FLOOR:
            block["status"] = "PARTIALLY_RELEASED"
            block["released_minutes"] = int(block.get("released_minutes") or 0) + int(block["open_minutes"])
            block["open_minutes"] = 0
            recompute_block(block)
            block["open_minutes"] = 0
            touch(block)
            blocks_partially_released += 1

    return {
        "swept_at": clock_str(),
        "permits_expired": len(permits_expired_ids),
        "permits_suspended": len(permits_suspended_ids),
        "permits_expired_ids": permits_expired_ids,
        "permits_suspended_ids": permits_suspended_ids,
        "blocks_released": blocks_released,
        "blocks_partially_released": blocks_partially_released,
        "cases_cancelled": cases_cancelled,
        "reservations_released": reservations_released,
    }
