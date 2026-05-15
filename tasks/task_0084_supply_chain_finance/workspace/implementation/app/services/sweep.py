"""Overdue sweep + aging refresh (PRD §3.8).

Idempotent for the current clock instant: running the sweep twice at the same
clock value does not change state on the second invocation.
"""
from __future__ import annotations

from datetime import datetime

from ..calculations import aging_bucket_for_dpd, days_past_due
from ..clock import clock
from ..store import store
from ..utils import parse_iso_or_none


def run_sweep() -> None:
    now = clock.now()

    for schedule in list(store.repayment_schedules.values()):
        if schedule.get("status") in ("SETTLED", "WRITTEN_OFF"):
            continue
        scheduled_dt_str = schedule.get("scheduled_repayment_date")
        scheduled_dt = parse_iso_or_none(scheduled_dt_str)
        if scheduled_dt is None:
            continue
        outstanding = int(schedule.get("total_due_cents", 0)) - int(schedule.get("paid_cents", 0))
        if outstanding <= 0:
            continue
        if now <= scheduled_dt:
            continue

        # Transition to OVERDUE if not already
        if schedule.get("status") != "OVERDUE":
            schedule["status"] = "OVERDUE"
            store.stamp_update(schedule)

        # Open a collection case if none exists for this schedule
        existing_case = None
        for case in store.collection_cases.values():
            if case.get("schedule_id") == schedule["id"] and case.get("stage") not in (
                "CLOSED",
                "WRITTEN_OFF",
            ):
                existing_case = case
                break

        dpd = days_past_due(scheduled_dt, now)
        bucket = aging_bucket_for_dpd(dpd)

        if existing_case is None:
            case_payload = {
                "schedule_id": schedule["id"],
                "aging_bucket": bucket,
                "stage": "SOFT",
                "reminder_count": 0,
                "outstanding_cents": outstanding,
            }
            store.stamp_create(case_payload)
            store.collection_cases[case_payload["id"]] = case_payload
            store.append_audit(
                actor_role="system",
                actor_id="system",
                entity_type="CollectionCase",
                entity_id=case_payload["id"],
                action="REGISTER",
            )
        else:
            # Refresh bucket and outstanding
            changed = False
            if existing_case.get("aging_bucket") != bucket:
                existing_case["aging_bucket"] = bucket
                changed = True
            if existing_case.get("outstanding_cents") != outstanding:
                existing_case["outstanding_cents"] = outstanding
                changed = True
            if changed:
                store.stamp_update(existing_case)
