from flask import Blueprint, g, request

from clock import clock
from db import store
from errors import err
from middleware import require_roles
from response import success
from services.assignments import (STAGE_LIMIT_HOURS, dispatch_assignment,
                                   spawn_successor)
from services.common import emit_audit, emit_external_sync, serialize_assignment, touch
from services.project_state import re_evaluate_project_state
from services.workload import recompute_workload

from datetime import timedelta

bp = Blueprint("assignments", __name__)


@bp.post("/projects/<id>/assignments")
@require_roles("ProjectManager")
def create_assignment(id):
    project = store.projects.get(id)
    if not project:
        raise err("ERR_NOT_FOUND", "project not found")
    if project["state"] not in ("QUOTED", "ACTIVE", "ALL_TRANSLATED", "ALL_REVIEWED"):
        raise err("ERR_INVALID_STATE", "project not accepting assignments in current state.")
    body = request.get_json(silent=True) or {}
    translator_id = body.get("translator_id")
    role = body.get("role")
    segment_ids = body.get("segment_ids")
    if not isinstance(translator_id, str):
        raise err("ERR_VALIDATION_FAILED", "translator_id required.")
    a = dispatch_assignment(
        project=project,
        translator_id=translator_id,
        role=role,
        segment_ids=segment_ids or [],
        actor_role="ProjectManager",
        actor_id=request.headers.get("X-User-ID"),
    )
    return success(serialize_assignment(a), status=201)


@bp.get("/assignments/<id>")
@require_roles("ProjectManager", "Translator")
def get_assignment(id):
    a = store.assignments.get(id)
    if not a:
        raise err("ERR_NOT_FOUND", "assignment not found")
    return success(serialize_assignment(a))


@bp.post("/assignments/<id>/accept")
@require_roles("Translator")
def accept_assignment(id):
    a = store.assignments.get(id)
    if not a:
        raise err("ERR_NOT_FOUND", "assignment not found")
    # State check (priority 6). PRD §3.3: "the acceptance is rejected with
    # ERR_INVALID_ASSIGNMENT_STATE if the assignment is not in PENDING."
    # ERR_ASSIGNMENT_ALREADY_TAKEN is reserved for the concurrent-race loser
    # path described in PRD §2.13.
    if a["state"] != "PENDING":
        raise err("ERR_INVALID_ASSIGNMENT_STATE", "assignment not in PENDING.")
    # Ownership
    if a["translator_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "not your assignment.")

    translator = store.translators.get(a["translator_id"])
    if translator is None:
        raise err("ERR_NOT_FOUND", "translator not found")
    project = store.projects.get(a["project_id"])
    if project is None:
        raise err("ERR_NOT_FOUND", "project not found")

    # Priority 7: test_translation_passed
    if not translator.get("test_translation_passed"):
        raise err("ERR_TEST_TRANSLATION_REQUIRED", "translator has not passed test translation.")

    # Priority 8: profile match
    pair_ok = any(
        p.get("source_lang") == project["source_lang"] and p.get("target_lang") == project["target_lang"]
        for p in translator.get("language_pairs", [])
    )
    if not pair_ok or project["domain"] not in translator.get("domains", []):
        raise err("ERR_TRANSLATOR_PROFILE_MISMATCH", "Translator profile does not cover project pair/domain.")

    # Priority 9: accept window
    if clock.now() >= a["accept_deadline_at"]:
        raise err("ERR_ACCEPT_WINDOW_EXPIRED", "accept window has expired.")

    # Availability
    if translator.get("availability_status") not in ("AVAILABLE", "BUSY"):
        raise err("ERR_INVALID_ASSIGNMENT_STATE", "translator not available.")

    # Priority 12: workload cap
    if int(translator.get("workload_segments_open", 0)) + len(a["segment_ids"]) > 200:
        raise err("ERR_TRANSLATOR_OVERLOADED", "workload cap exceeded.")

    from_state = a["state"]
    a["state"] = "ACCEPTED"
    now = clock.now()
    a["accepted_at"] = now
    a["stage_deadline_at"] = now + timedelta(hours=STAGE_LIMIT_HOURS[a["role"]])
    touch(a)

    emit_audit(
        subject_type="Assignment",
        subject_id=a["id"],
        event="STATE_TRANSITION",
        from_state=from_state,
        to_state="ACCEPTED",
        actor_role="Translator",
        actor_id=g.user_id,
        payload={"stage_deadline_at": a["stage_deadline_at"].isoformat()},
    )

    # For TRANSLATOR role: covered segments NEW -> ASSIGNED
    if a["role"] == "TRANSLATOR":
        for sid in a["segment_ids"]:
            seg = store.segments.get(sid)
            if seg is None:
                continue
            if seg["state"] == "NEW":
                prev = seg["state"]
                seg["state"] = "ASSIGNED"
                seg["assignment_id"] = a["id"]
                touch(seg)
                emit_audit(
                    subject_type="Segment",
                    subject_id=seg["id"],
                    event="STATE_TRANSITION",
                    from_state=prev,
                    to_state="ASSIGNED",
                    actor_role="system",
                    actor_id=None,
                    payload={"assignment_id": a["id"]},
                )

    recompute_workload(a["translator_id"])
    return success(serialize_assignment(a))


@bp.post("/assignments/<id>/reject")
@require_roles("Translator")
def reject_assignment(id):
    a = store.assignments.get(id)
    if not a:
        raise err("ERR_NOT_FOUND", "assignment not found")
    if a["state"] != "PENDING":
        raise err("ERR_INVALID_ASSIGNMENT_STATE", "assignment not in PENDING.")
    if a["translator_id"] != g.user_id:
        raise err("ERR_FORBIDDEN", "not your assignment.")
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        raise err("ERR_VALIDATION_FAILED", "reason required.")
    if clock.now() >= a["accept_deadline_at"]:
        raise err("ERR_ACCEPT_WINDOW_EXPIRED", "accept window has expired.")

    from_state = a["state"]
    a["state"] = "REJECTED"
    touch(a)
    emit_audit(
        subject_type="Assignment",
        subject_id=a["id"],
        event="STATE_TRANSITION",
        from_state=from_state,
        to_state="REJECTED",
        actor_role="Translator",
        actor_id=g.user_id,
        payload={"reason": reason},
    )
    emit_external_sync(
        project_id=a["project_id"],
        target_system="IM",
        trigger_event="ASSIGNMENT_REJECTED",
        payload={"assignment_id": a["id"], "translator_id": a["translator_id"], "reason": reason},
        actor_role="Translator",
        actor_id=g.user_id,
    )
    # Spawn successor; exclude rejecter
    spawn_successor(a, excluded_ids={a["translator_id"]}, trigger_event="ASSIGNMENT_REJECTED",
                    actor_role="ProjectManager", actor_id=None)
    return success(serialize_assignment(a))


@bp.post("/assignments/<id>/reassign")
@require_roles("ProjectManager")
def reassign_assignment(id):
    a = store.assignments.get(id)
    if not a:
        raise err("ERR_NOT_FOUND", "assignment not found")
    if a["state"] != "ACCEPTED":
        raise err("ERR_INVALID_ASSIGNMENT_STATE", "assignment not in ACCEPTED.")
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason:
        raise err("ERR_VALIDATION_FAILED", "reason required.")
    # Allowed if past stage_deadline_at OR reason == 'STALE'
    now = clock.now()
    if a.get("stage_deadline_at") and now <= a["stage_deadline_at"] and reason != "STALE":
        raise err("ERR_INVALID_ASSIGNMENT_STATE", "stage deadline not passed and reason is not STALE.")

    from_state = a["state"]
    a["state"] = "REASSIGNED"
    touch(a)

    # For TRANSLATOR role, regress covered segments to NEW (clear assignment_id)
    if a["role"] == "TRANSLATOR":
        for sid in a["segment_ids"]:
            seg = store.segments.get(sid)
            if seg is None:
                continue
            if seg["state"] in ("ASSIGNED", "TRANSLATED", "REVIEWED"):
                prev = seg["state"]
                seg["state"] = "NEW"
                seg["assignment_id"] = None
                touch(seg)
                emit_audit(
                    subject_type="Segment",
                    subject_id=seg["id"],
                    event="STATE_TRANSITION",
                    from_state=prev,
                    to_state="NEW",
                    actor_role="ProjectManager",
                    actor_id=request.headers.get("X-User-ID"),
                    payload={"reason": "reassigned"},
                )

    emit_audit(
        subject_type="Assignment",
        subject_id=a["id"],
        event="STATE_TRANSITION",
        from_state=from_state,
        to_state="REASSIGNED",
        actor_role="ProjectManager",
        actor_id=request.headers.get("X-User-ID"),
        payload={"reason": reason},
    )

    recompute_workload(a["translator_id"])
    re_evaluate_project_state(a["project_id"])

    emit_external_sync(
        project_id=a["project_id"],
        target_system="IM",
        trigger_event="STAGE_DEADLINE_BREACHED",
        payload={"assignment_id": a["id"], "translator_id": a["translator_id"], "reason": reason},
        actor_role="ProjectManager",
        actor_id=request.headers.get("X-User-ID"),
    )

    # Spawn successor
    spawn_successor(a, excluded_ids={a["translator_id"]}, trigger_event="STAGE_DEADLINE_BREACHED",
                    actor_role="ProjectManager", actor_id=request.headers.get("X-User-ID"))
    return success(serialize_assignment(a))
