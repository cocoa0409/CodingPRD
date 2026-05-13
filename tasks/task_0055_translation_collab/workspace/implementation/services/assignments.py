"""Assignment lifecycle: dispatch, accept, reject, expire, reassign, spawn successor."""
from __future__ import annotations

from datetime import timedelta

from clock import clock
from db import new_id, store
from errors import err
from services.common import emit_audit, emit_external_sync, stamp_create, touch
from services.workload import recompute_workload, select_successor_translator

ACCEPT_WINDOW_HOURS = 48
STAGE_LIMIT_HOURS = {
    "TRANSLATOR": 72,
    "REVIEWER": 48,
    "FINAL_REVIEWER": 24,
}


def _segments_pre_state_for_role(role: str) -> set[str]:
    if role == "TRANSLATOR":
        return {"NEW"}
    if role == "REVIEWER":
        return {"TRANSLATED"}
    if role == "FINAL_REVIEWER":
        return {"REVIEWED"}
    return set()


def _segment_held_by_other_assignment(seg: dict, role: str, exclude_assignment_id: str | None = None) -> bool:
    """True if any non-terminal assignment with same role covers this segment."""
    for a in store.assignments.values():
        if exclude_assignment_id and a["id"] == exclude_assignment_id:
            continue
        if a["state"] not in {"PENDING", "ACCEPTED"}:
            continue
        if a["role"] != role:
            continue
        if seg["id"] in a["segment_ids"]:
            return True
    return False


def dispatch_assignment(project: dict, translator_id: str, role: str, segment_ids: list[str],
                        *, actor_role: str, actor_id: str | None, validate_workload: bool = True) -> dict:
    if role not in {"TRANSLATOR", "REVIEWER", "FINAL_REVIEWER"}:
        raise err("ERR_VALIDATION_FAILED", "role invalid.")
    if not isinstance(segment_ids, list) or not segment_ids:
        raise err("ERR_VALIDATION_FAILED", "segment_ids must be non-empty list.")
    # Package-size check (priority 11)
    if len(segment_ids) > int(project["package_size_segments"]):
        raise err("ERR_PACKAGE_SIZE_EXCEEDED", "Segment package too large.")

    translator = store.translators.get(translator_id)
    if translator is None:
        raise err("ERR_NOT_FOUND", "translator not found.")

    # Profile match (priority 8)
    pair_ok = any(
        p.get("source_lang") == project["source_lang"] and p.get("target_lang") == project["target_lang"]
        for p in translator.get("language_pairs", [])
    )
    if not pair_ok or project["domain"] not in translator.get("domains", []):
        raise err("ERR_TRANSLATOR_PROFILE_MISMATCH", "Translator profile does not cover project pair/domain.")

    # Segment-already-assigned check + state check (priority 10)
    pre_states = _segments_pre_state_for_role(role)
    for sid in segment_ids:
        seg = store.segments.get(sid)
        if seg is None:
            raise err("ERR_NOT_FOUND", f"segment {sid} not found.")
        if seg["project_id"] != project["id"]:
            raise err("ERR_NOT_FOUND", f"segment {sid} not under project.")
        if seg["state"] not in pre_states:
            raise err("ERR_SEGMENT_ALREADY_ASSIGNED", f"segment {sid} not in role pre-state.")
        if _segment_held_by_other_assignment(seg, role):
            raise err("ERR_SEGMENT_ALREADY_ASSIGNED", f"segment {sid} already in non-terminal assignment for role.")

    # Workload cap (priority 12)
    if validate_workload:
        if int(translator.get("workload_segments_open", 0)) + len(segment_ids) > 200:
            raise err("ERR_TRANSLATOR_OVERLOADED", "Translator workload cap exceeded.")

    now = clock.now()
    a = {
        "id": new_id(),
        "project_id": project["id"],
        "translator_id": translator_id,
        "role": role,
        "segment_ids": list(segment_ids),
        "dispatched_at": now,
        "accept_deadline_at": now + timedelta(hours=ACCEPT_WINDOW_HOURS),
        "stage_deadline_at": None,
        "accepted_at": None,
        "state": "PENDING",
    }
    stamp_create(a)
    # stamp_create overwrote created_at/updated_at to clock.now() — keep dispatched_at aligned
    a["dispatched_at"] = a["created_at"]
    a["accept_deadline_at"] = a["created_at"] + timedelta(hours=ACCEPT_WINDOW_HOURS)
    store.assignments[a["id"]] = a

    emit_audit(
        subject_type="Assignment",
        subject_id=a["id"],
        event="STATE_TRANSITION",
        from_state=None,
        to_state="PENDING",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"role": role, "segment_count": len(segment_ids)},
    )
    emit_external_sync(
        project_id=project["id"],
        target_system="IM",
        trigger_event="ASSIGNMENT_DISPATCHED",
        payload={"assignment_id": a["id"], "translator_id": translator_id, "role": role},
        actor_role=actor_role,
        actor_id=actor_id,
    )
    return a


def spawn_successor(predecessor: dict, *, excluded_ids: set[str], trigger_event: str, actor_role: str, actor_id: str | None) -> dict | None:
    """Spawn a successor PENDING assignment to a different translator. May raise
    ERR_NO_ELIGIBLE_TRANSLATOR when the candidate pool is empty."""
    project = store.projects.get(predecessor["project_id"])
    if project is None:
        return None
    successor_translator = select_successor_translator(project, len(predecessor["segment_ids"]), excluded_ids)
    if successor_translator is None:
        raise err("ERR_NO_ELIGIBLE_TRANSLATOR", "No eligible translator available for successor.")

    # Bypass workload cap since selector already enforced; but skip re-validation that may
    # spuriously reject (we already checked eligibility).
    succ = dispatch_assignment(
        project=project,
        translator_id=successor_translator["id"],
        role=predecessor["role"],
        segment_ids=list(predecessor["segment_ids"]),
        actor_role=actor_role,
        actor_id=actor_id,
        validate_workload=False,
    )
    # Audit REASSIGNED event linking predecessor to successor
    emit_audit(
        subject_type="Assignment",
        subject_id=predecessor["id"],
        event="REASSIGNED",
        actor_role=actor_role,
        actor_id=actor_id,
        payload={"successor_assignment_id": succ["id"], "successor_translator_id": successor_translator["id"]},
    )
    return succ


def expire_pending_assignments() -> int:
    """Sweep PENDING assignments whose accept_deadline_at has passed. Returns count expired."""
    now = clock.now()
    expired_count = 0
    # Snapshot since spawning successors mutates the dict
    pending = [a for a in list(store.assignments.values()) if a["state"] == "PENDING"]
    for a in pending:
        if a["state"] != "PENDING":
            continue
        if now < a["accept_deadline_at"]:
            continue
        # Expire
        from_state = a["state"]
        a["state"] = "EXPIRED"
        touch(a)
        emit_audit(
            subject_type="Assignment",
            subject_id=a["id"],
            event="STATE_TRANSITION",
            from_state=from_state,
            to_state="EXPIRED",
            actor_role="system",
            actor_id=None,
            payload={"reason": "accept_window_expired"},
        )
        emit_external_sync(
            project_id=a["project_id"],
            target_system="IM",
            trigger_event="ASSIGNMENT_REJECTED",
            payload={"assignment_id": a["id"], "translator_id": a["translator_id"], "reason": "expired"},
            actor_role="system",
            actor_id=None,
        )
        # Spawn successor; exclude the expirer
        excluded = {a["translator_id"]}
        try:
            spawn_successor(a, excluded_ids=excluded, trigger_event="ASSIGNMENT_REJECTED",
                            actor_role="system", actor_id=None)
        except Exception:
            # No eligible translator — leave as expired with no successor
            pass
        expired_count += 1
    return expired_count
