"""Cross-cutting workflow primitives — order/specimen/result/notification cascades."""
from __future__ import annotations

from typing import Any

from ..clock import now
from ..helpers import new_uuid
from ..store import store
from . import calculations as calc
from .audit import write_audit_event


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def bump(row: dict[str, Any]) -> None:
    """Mutation bookkeeping: updated_at = now(), version += 1 (when applicable)."""
    row["updated_at"] = now()
    if "version" in row:
        row["version"] += 1


def create_common_fields() -> dict[str, Any]:
    t = now()
    return {"id": new_uuid(), "created_at": t, "updated_at": t, "version": 1}


# ---------------------------------------------------------------------------
# LabOrder creation (used initially + by retest cloning)
# ---------------------------------------------------------------------------

def create_lab_order(
    patient_id: str,
    ordering_provider_id: str,
    panel_id: str,
    priority: str,
    *,
    parent_order_id: str | None = None,
    retest_count: int = 0,
) -> dict[str, Any]:
    row = {
        **create_common_fields(),
        "patient_id": patient_id,
        "ordering_provider_id": ordering_provider_id,
        "panel_id": panel_id,
        "priority": priority,
        "status": "ORDERED",
        "retest_count": retest_count,
        "parent_order_id": parent_order_id,
        "ordered_at": now(),
    }
    store().lab_orders[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# Retest issuance — used by 3 trigger paths.
# Returns (retest_row, new_order_row).
# ---------------------------------------------------------------------------

def issue_retest(
    original_order: dict[str, Any],
    reason: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    new_order = create_lab_order(
        patient_id=original_order["patient_id"],
        ordering_provider_id=original_order["ordering_provider_id"],
        panel_id=original_order["panel_id"],
        priority=original_order["priority"],
        parent_order_id=original_order["id"],
        retest_count=original_order.get("retest_count", 0) + 1,
    )
    retest = {
        **create_common_fields(),
        "lab_order_id": original_order["id"],
        "reason": reason,
        "new_lab_order_id": new_order["id"],
        "status": "ISSUED",
    }
    store().retest_requests[retest["id"]] = retest
    return retest, new_order


# ---------------------------------------------------------------------------
# CriticalNotification creation
# ---------------------------------------------------------------------------

def create_critical_notification(
    lab_result: dict[str, Any],
    lab_order: dict[str, Any],
    flags_subset: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Create a CriticalNotification at release/amend time.

    flags_subset, when provided (for amendment), narrows the notification scope
    to only the newly-critical analytes; not persisted as a separate field on
    the notification row but stored on a hidden side-key for ack read-back.
    """
    t = now()
    deadline = calc.ack_deadline_at(t, lab_order["priority"])
    row = {
        **create_common_fields(),
        "lab_result_id": lab_result["id"],
        "recipient_clinician_id": lab_order["ordering_provider_id"],
        "channel": "SMS",
        "attempt_count": 0,
        "first_sent_at": t,
        "ack_deadline_at": deadline,
        "status": "PENDING",
        # internal: which analytes this notification is scoped to (for HIGH read-back)
        "_scoped_analyte_codes": [
            f["analyte_code"] for f in (flags_subset if flags_subset is not None else lab_result["critical_flags"])
        ],
    }
    store().critical_notifications[row["id"]] = row
    return row


# ---------------------------------------------------------------------------
# History lookup for severity_score_final
# ---------------------------------------------------------------------------

def history_critical_count(
    patient_id: str,
    panel_id: str,
    exclude_result_id: str,
) -> int:
    s = store()
    # Find released results on same patient+panel, ordered by released_at DESC,
    # excluding the current result. Take latest 2; count how many had any critical flags.
    candidates: list[dict[str, Any]] = []
    for result in s.lab_results.values():
        if result["id"] == exclude_result_id:
            continue
        order = s.lab_orders.get(result["lab_order_id"])
        if not order:
            continue
        if order["patient_id"] != patient_id:
            continue
        if order["panel_id"] != panel_id:
            continue
        if result.get("released_at") is None:
            continue
        candidates.append(result)
    candidates.sort(key=lambda r: r["released_at"], reverse=True)
    take = candidates[: calc.HISTORY_LOOKBACK]
    return sum(1 for r in take if r.get("critical_flags"))
