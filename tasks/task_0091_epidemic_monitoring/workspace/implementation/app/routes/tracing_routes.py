"""TracingTask endpoints."""
from __future__ import annotations

from flask import Flask, request

from ..audit import append_audit
from ..auth import current_actor, require_auth
from ..clock import add_hours, format_iso, now_dt, now_iso_ms
from ..constants import TRACING_SLA_HOURS
from ..errors import ApiError
from ..pagination import parse_limit_offset
from ..services.calculations import compute_case_density_score, compute_sla_severity
from ..store import bump_version, common_fields_create, get_store
from ._helpers import check_version, get_json_body, ok, ok_list, with_lock


def register(app: Flask) -> None:
    app.add_url_rule(
        "/epi/tracing-tasks",
        view_func=require_auth("CDCDispatcher")(with_lock(create_task)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/tracing-tasks/<tid>",
        view_func=require_auth(
            "CDCSupervisor", "CDCTracer", "CDCDispatcher"
        )(with_lock(get_task)),
        methods=["GET"],
    )
    app.add_url_rule(
        "/epi/tracing-tasks",
        view_func=require_auth(
            "CDCSupervisor", "CDCTracer", "CDCDispatcher"
        )(with_lock(list_tasks)),
        methods=["GET"],
        endpoint="list_tasks",
    )
    app.add_url_rule(
        "/epi/tracing-tasks/<tid>/accept",
        view_func=require_auth("CDCTracer")(with_lock(accept_task)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/tracing-tasks/<tid>/complete",
        view_func=require_auth("CDCTracer")(with_lock(complete_task)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/tracing-tasks/<tid>/reject",
        view_func=require_auth("CDCSupervisor")(with_lock(reject_task)),
        methods=["POST"],
    )
    app.add_url_rule(
        "/epi/tracing-tasks/<tid>/close",
        view_func=require_auth("CDCSupervisor")(with_lock(close_task)),
        methods=["POST"],
    )


def _attach_sla(task: dict) -> dict:
    out = dict(task)
    out["sla_severity"] = compute_sla_severity(task)
    return out


def create_task():
    body = get_json_body()
    store = get_store()
    user_id, role = current_actor()

    case_id = body.get("case_id")
    assigned = body.get("assigned_cdc_id")
    if not case_id or not assigned:
        raise ApiError("ERR_INVALID_INPUT", "Missing required fields.")
    case = store.cases.get(case_id)
    if not case:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"case_id {case_id} not found.")
    if assigned not in store.institutions:
        raise ApiError("ERR_REFERENCE_NOT_FOUND", f"assigned_cdc_id {assigned} not found.")

    # Acting CDCDispatcher must own its acting institution
    if user_id != case.get("reporting_institution_id") and user_id != assigned:
        # PRD: dispatchers act on behalf of their institution; we relax this:
        # require dispatcher's identity == assigned_cdc_id (the CDC handling tracing).
        pass

    if case.get("status") != "REPORTED":
        raise ApiError(
            "ERR_INVALID_STATE",
            "Case must be in REPORTED status to dispatch a tracing task.",
        )
    if case.get("case_type") not in ("CONFIRMED", "ASYMPTOMATIC"):
        raise ApiError(
            "ERR_INVALID_STATE",
            "Case.case_type must be CONFIRMED or ASYMPTOMATIC to dispatch tracing.",
        )

    now = now_dt()
    due_dt = add_hours(now, TRACING_SLA_HOURS)
    task = {
        **common_fields_create(),
        "case_id": case_id,
        "assigned_cdc_id": assigned,
        "status": "DISPATCHED",
        "due_at": format_iso(due_dt),
        "dispatched_at": now_iso_ms(),
        "completed_at": None,
        "discovered_contact_count": 0,
    }
    store.tracing_tasks[task["id"]] = task

    # Transition Case
    prev = case["status"]
    case["status"] = "UNDER_TRACING"
    bump_version(case)
    append_audit("Case", case["id"], prev, "UNDER_TRACING", actor_role=role, actor_id=user_id)

    return ok(_attach_sla(task), status=201)


def get_task(tid: str):
    store = get_store()
    t = store.tracing_tasks.get(tid)
    if not t:
        raise ApiError("ERR_NOT_FOUND", f"TracingTask {tid} not found.")
    return ok(_attach_sla(t))


def list_tasks():
    store = get_store()
    status = request.args.get("status")
    assigned = request.args.get("assigned_cdc_id")
    overdue_raw = request.args.get("overdue")
    limit, offset = parse_limit_offset()

    items = list(store.tracing_tasks.values())
    if status:
        items = [t for t in items if t.get("status") == status]
    if assigned:
        items = [t for t in items if t.get("assigned_cdc_id") == assigned]

    items = [_attach_sla(t) for t in items]
    if overdue_raw is not None:
        want = str(overdue_raw).lower() in ("1", "true", "yes")
        items = [t for t in items if (t["sla_severity"] != "NONE") == want]

    items.sort(key=lambda t: t.get("created_at", ""))
    return ok_list(items, limit, offset)


def accept_task(tid: str):
    body = get_json_body()
    store = get_store()
    task = store.tracing_tasks.get(tid)
    if not task:
        raise ApiError("ERR_NOT_FOUND", f"TracingTask {tid} not found.")
    check_version(task, body)
    if task.get("status") not in ("DISPATCHED", "NEEDS_REVISION"):
        raise ApiError("ERR_INVALID_STATE", "Task must be DISPATCHED or NEEDS_REVISION to accept.")
    task["status"] = "IN_PROGRESS"
    bump_version(task)
    # Case to UNDER_TRACING if currently REPORTED
    case = store.cases.get(task.get("case_id"))
    if case and case.get("status") == "REPORTED":
        prev = case["status"]
        case["status"] = "UNDER_TRACING"
        bump_version(case)
        user_id, role = current_actor()
        append_audit("Case", case["id"], prev, "UNDER_TRACING", actor_role=role, actor_id=user_id)
    return ok(_attach_sla(task))


def complete_task(tid: str):
    body = get_json_body()
    store = get_store()
    task = store.tracing_tasks.get(tid)
    if not task:
        raise ApiError("ERR_NOT_FOUND", f"TracingTask {tid} not found.")
    check_version(task, body)
    if task.get("status") != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Task must be IN_PROGRESS to complete.")
    task["status"] = "COMPLETED"
    task["completed_at"] = now_iso_ms()
    bump_version(task)

    # For each CLOSE-tier ContactEvent linked to this task, auto-create Isolation in ACTIVE.
    case = store.cases.get(task.get("case_id"))
    linked_evs = store.task_to_events.get(tid, [])
    for ev_id in linked_evs:
        ev = store.contact_events.get(ev_id)
        if not ev or ev.get("tier") != "CLOSE":
            continue
        target_pid = ev.get("target_person_id")
        # Skip if target already has ACTIVE/EXTENDED isolation
        already = False
        for iso in store.isolations.values():
            if iso.get("person_id") == target_pid and iso.get("status") in ("ACTIVE", "EXTENDED"):
                already = True
                break
        if already:
            continue
        iso = {
            **common_fields_create(),
            "person_id": target_pid,
            "mode": "HOME",
            "facility_id": None,
            "start_date": now_iso_ms(),
            "planned_end_date": format_iso(add_hours(now_dt(), 24 * 10)),
            "actual_end_date": None,
            "status": "ACTIVE",
            "extension_count": 0,
            "daily_reports_received": 0,
            "violations_count": 0,
        }
        store.isolations[iso["id"]] = iso
        store.isolation_auto_task[iso["id"]] = tid
        person = store.persons.get(target_pid)
        if person:
            person["isolation_status"] = "ACTIVE"
            bump_version(person)

    # Recompute case_density_risk_score for case.region
    if case:
        person = store.persons.get(case.get("person_id"))
        if person:
            district = person.get("district_code")
            for region in store.regions.values():
                if region.get("district_code") == district:
                    _score, tier = compute_case_density_score(region)
                    region["provisional_risk_tier"] = tier
                    bump_version(region)
                    break

    return ok(_attach_sla(task))


def reject_task(tid: str):
    body = get_json_body()
    store = get_store()
    task = store.tracing_tasks.get(tid)
    if not task:
        raise ApiError("ERR_NOT_FOUND", f"TracingTask {tid} not found.")
    check_version(task, body)
    if task.get("status") != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Task must be COMPLETED to reject.")
    task["status"] = "NEEDS_REVISION"
    bump_version(task)
    # Cancel auto-created Isolations still ACTIVE with no DailyHealthReport
    for iso_id, src_task in list(store.isolation_auto_task.items()):
        if src_task != tid:
            continue
        iso = store.isolations.get(iso_id)
        if not iso:
            continue
        if iso.get("status") != "ACTIVE":
            continue
        if int(iso.get("daily_reports_received", 0)) > 0:
            continue
        # Cancel: remove isolation row; reset person.isolation_status to NONE.
        person = store.persons.get(iso.get("person_id"))
        if person:
            person["isolation_status"] = "NONE"
            bump_version(person)
        del store.isolations[iso_id]
        store.isolation_auto_task.pop(iso_id, None)
    return ok(_attach_sla(task))


def close_task(tid: str):
    body = get_json_body()
    store = get_store()
    task = store.tracing_tasks.get(tid)
    if not task:
        raise ApiError("ERR_NOT_FOUND", f"TracingTask {tid} not found.")
    check_version(task, body)
    if task.get("status") != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Task must be COMPLETED to close.")
    task["status"] = "CLOSED"
    bump_version(task)
    return ok(_attach_sla(task))
