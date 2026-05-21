"""OfferingPeriod service: lifecycle, FMV capture, sweep helpers."""
from __future__ import annotations

from typing import Any, Dict, Optional

from core.errors import (
    APIError,
    err_fmv_before_period_end,
    err_grant_fmv_window,
    err_invalid_period_state,
    err_not_found,
    err_version_conflict,
)
from core.store import store
from core.utils import add_months, format_iso, lock, new_id, parse_iso
from services.timestamps import stamp_create, stamp_update


def get_offering_period_or_404(offering_period_id: str) -> dict:
    op = store.offering_periods.get(offering_period_id)
    if op is None:
        raise err_not_found(f"OfferingPeriod {offering_period_id} not found.")
    return op


def _create_offering_period_internal(
    *, plan: dict, sequence_number: int, start_date: str
) -> dict:
    """Internal helper — used by plan activation and the purchase batch rollover."""
    start_dt = parse_iso(start_date)
    end_dt = add_months(start_dt, plan["offering_period_months"])
    op = {
        "id": new_id(),
        "plan_id": plan["id"],
        "sequence_number": sequence_number,
        "start_date": format_iso(start_dt),
        "end_date": format_iso(end_dt),
        "grant_date_fmv_cents": None,
        "purchase_date_fmv_cents": None,
        "status": "OPEN",
    }
    stamp_create(op)
    store.offering_periods[op["id"]] = op
    return op


def record_grant_fmv(
    *, plan_id: str, offering_period_id: str, payload: Dict[str, Any]
) -> dict:
    with lock():
        from services.plan_service import get_plan_or_404

        plan = get_plan_or_404(plan_id)
        op = get_offering_period_or_404(offering_period_id)
        if op["plan_id"] != plan_id:
            raise err_not_found("OfferingPeriod does not belong to plan.")

        fmv = payload.get("grant_date_fmv_cents")
        if not isinstance(fmv, int) or isinstance(fmv, bool) or fmv <= 0:
            raise APIError(
                "ERR_GRANT_FMV_WINDOW",
                "grant_date_fmv_cents must be a positive integer.",
                409,
            )

        if op["grant_date_fmv_cents"] is not None:
            raise err_grant_fmv_window("grant_date_fmv_cents already set.")

        # Must be on the start_date day.
        current_time = parse_iso(store.clock["current_time"])
        start_dt = parse_iso(op["start_date"])
        if current_time.date() != start_dt.date():
            raise err_grant_fmv_window(
                "Current clock day must equal OfferingPeriod.start_date day."
            )

        op["grant_date_fmv_cents"] = fmv
        stamp_update(op)
    return op


def patch_purchase_fmv(
    *, offering_period_id: str, payload: Dict[str, Any]
) -> dict:
    with lock():
        op = get_offering_period_or_404(offering_period_id)
        if op["status"] not in ("OPEN", "CLOSED"):
            raise err_invalid_period_state(
                f"OfferingPeriod status is {op['status']}, cannot update FMV."
            )

        # Validate FMV value.
        fmv = payload.get("purchase_date_fmv_cents")
        if not isinstance(fmv, int) or isinstance(fmv, bool) or fmv <= 0:
            raise APIError(
                "ERR_FMV_BEFORE_PERIOD_END",
                "purchase_date_fmv_cents must be a positive integer.",
                422,
            )

        # Temporal check: clock must be >= end_date.
        current_time = parse_iso(store.clock["current_time"])
        end_dt = parse_iso(op["end_date"])
        if current_time < end_dt:
            raise err_fmv_before_period_end()

        # OCC check.
        if "version" in payload and payload["version"] != op["version"]:
            raise err_version_conflict()

        op["purchase_date_fmv_cents"] = fmv
        stamp_update(op)
    return op


def list_offering_periods_for_plan(
    plan_id: str, *, status_filter: Optional[str] = None
) -> list:
    # Caller is responsible for plan existence.
    items = store.list_offering_periods_for_plan(plan_id)
    if status_filter is not None:
        items = [op for op in items if op["status"] == status_filter]
    items.sort(key=lambda o: o["created_at"])
    return items
