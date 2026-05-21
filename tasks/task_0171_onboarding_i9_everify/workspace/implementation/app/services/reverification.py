"""ReverificationEvent service: open, resolve, expire."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..audit import append_audit
from ..clock import format_datetime_ms, get_clock, parse_iso_datetime
from ..errors import err_not_found, err_validation
from ..store import get_store, new_id


_VALID_REASONS = {"WORK_AUTH_EXPIRY", "OPT_TO_OPT_STEM_EXTENSION", "REHIRE_WITHIN_3_YEARS"}


def open_reverification_event(
    *,
    employee: dict,
    triggering_form_id: str,
    reason: str,
    resolution_deadline: Optional[str],
    actor_role: str,
    actor_user_id: Optional[str],
) -> Dict[str, Any]:
    if reason not in _VALID_REASONS:
        raise err_validation("Invalid reverification reason.")
    store = get_store()
    clock = get_clock()
    now_iso = format_datetime_ms(clock.get())
    rid = new_id()
    row = {
        "id": rid,
        "employee_id": employee["id"],
        "triggering_form_id": triggering_form_id,
        "reason": reason,
        "new_form_id": None,
        "resolution_deadline": resolution_deadline,
        "resolved_at": None,
        "status": "OPEN",
        "created_at": now_iso,
        "_seq": store.next_seq(),
    }
    store.reverification_events[rid] = row
    append_audit(
        subject_employee_id=employee["id"],
        subject_entity="REVERIFICATION_EVENT",
        subject_entity_id=rid,
        action="REVERIFY_OPENED",
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
    return row


def list_reverification_events(emp_id: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
    store = get_store()
    if emp_id not in store.employees:
        raise err_not_found("Employee not found.")
    items = [r for r in store.reverification_events.values() if r["employee_id"] == emp_id]
    status = filters.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return items


def find_open_event_for_form(form_id: str) -> Optional[Dict[str, Any]]:
    store = get_store()
    for r in store.reverification_events.values():
        if r["triggering_form_id"] == form_id and r["status"] == "OPEN":
            return r
    return None


def resolve_event(event: Dict[str, Any], successor_form: Dict[str, Any], actor_role: str, actor_user_id: Optional[str]) -> None:
    event["resolved_at"] = successor_form["section2_completed_at"]
    event["new_form_id"] = successor_form["id"]
    event["status"] = "RESOLVED"
    append_audit(
        subject_employee_id=event["employee_id"],
        subject_entity="REVERIFICATION_EVENT",
        subject_entity_id=event["id"],
        action="REVERIFY_RESOLVED",
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )


def expire_event(event: Dict[str, Any], actor_role: str, actor_user_id: Optional[str]) -> None:
    event["status"] = "EXPIRED"
    append_audit(
        subject_employee_id=event["employee_id"],
        subject_entity="REVERIFICATION_EVENT",
        subject_entity_id=event["id"],
        action="REVERIFY_EXPIRED",
        actor_role=actor_role,
        actor_user_id=actor_user_id,
    )
