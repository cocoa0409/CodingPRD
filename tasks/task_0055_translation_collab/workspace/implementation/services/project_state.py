"""Project compound-state bubble-up logic."""
from __future__ import annotations

from db import store
from services.common import emit_audit, touch
from services.pricing import segments_for_project


PROJECT_PIPELINE_STATES = ("ACTIVE", "ALL_TRANSLATED", "ALL_REVIEWED")


def re_evaluate_project_state(project_id: str, *, actor_role: str = "system", actor_id=None) -> None:
    """Promote/demote a project based on its segments' current states.

    Forward:
      ACTIVE -> ALL_TRANSLATED  iff every segment in {TRANSLATED, REVIEWED, FINAL_APPROVED}
      ALL_TRANSLATED -> ALL_REVIEWED iff every segment in {REVIEWED, FINAL_APPROVED}
    Backward:
      ALL_TRANSLATED -> ACTIVE if any segment in {NEW, ASSIGNED}
      ALL_REVIEWED -> ALL_TRANSLATED if any segment in {TRANSLATED, NEW, ASSIGNED}
    """
    proj = store.projects.get(project_id)
    if proj is None:
        return
    if proj["state"] not in PROJECT_PIPELINE_STATES:
        return

    segs = [s for s in store.segments.values() if s["project_id"] == project_id]
    # We do NOT count REJECTED/REASSIGNED segments toward "every segment" — those are
    # terminal-rejected. But per PRD, on cancel we mass-reject; bubble-up only relevant
    # while project is in pipeline states.
    relevant = [s for s in segs if s["state"] not in ("REJECTED", "REASSIGNED")]
    if not relevant:
        return

    states = [s["state"] for s in relevant]
    all_translated = all(st in {"TRANSLATED", "REVIEWED", "FINAL_APPROVED"} for st in states)
    all_reviewed = all(st in {"REVIEWED", "FINAL_APPROVED"} for st in states)
    has_pre_translation = any(st in {"NEW", "ASSIGNED"} for st in states)
    has_pre_review = any(st in {"TRANSLATED", "NEW", "ASSIGNED"} for st in states)

    current = proj["state"]
    target = current

    if current == "ACTIVE":
        if all_translated:
            target = "ALL_TRANSLATED"
            if all_reviewed:
                target = "ALL_REVIEWED"
    elif current == "ALL_TRANSLATED":
        if has_pre_translation:
            target = "ACTIVE"
        elif all_reviewed:
            target = "ALL_REVIEWED"
    elif current == "ALL_REVIEWED":
        if has_pre_review:
            # Demote to ALL_TRANSLATED if all are at least TRANSLATED,
            # else further back to ACTIVE if any are pre-translation
            if has_pre_translation:
                target = "ACTIVE"
            else:
                target = "ALL_TRANSLATED"

    if target != current:
        proj["state"] = target
        touch(proj)
        emit_audit(
            subject_type="Project",
            subject_id=proj["id"],
            event="STATE_TRANSITION",
            from_state=current,
            to_state=target,
            actor_role=actor_role,
            actor_id=actor_id,
            payload={"reason": "bubble_up"},
        )
        # Cascade once more in case multiple jumps possible (e.g., ACTIVE→ALL_TRANSLATED then →ALL_REVIEWED)
        re_evaluate_project_state(project_id, actor_role=actor_role, actor_id=actor_id)


def re_evaluate_assignment_completion(assignment_id: str) -> None:
    """If every covered segment has reached the role's terminal-for-this-stage state,
    transition the assignment from ACCEPTED to COMPLETED."""
    a = store.assignments.get(assignment_id)
    if a is None or a["state"] != "ACCEPTED":
        return

    role = a["role"]
    seg_states = []
    for sid in a["segment_ids"]:
        seg = store.segments.get(sid)
        if seg is None:
            return
        seg_states.append(seg["state"])

    if role == "TRANSLATOR":
        complete = all(s in {"TRANSLATED", "REVIEWED", "FINAL_APPROVED"} for s in seg_states)
    elif role == "REVIEWER":
        complete = all(s in {"REVIEWED", "FINAL_APPROVED"} for s in seg_states)
    elif role == "FINAL_REVIEWER":
        complete = all(s == "FINAL_APPROVED" for s in seg_states)
    else:
        complete = False

    if complete:
        from_state = a["state"]
        a["state"] = "COMPLETED"
        touch(a)
        emit_audit(
            subject_type="Assignment",
            subject_id=a["id"],
            event="STATE_TRANSITION",
            from_state=from_state,
            to_state="COMPLETED",
            actor_role="system",
            actor_id=None,
            payload={},
        )
        # Recompute workload for translator
        from services.workload import recompute_workload
        recompute_workload(a["translator_id"])
