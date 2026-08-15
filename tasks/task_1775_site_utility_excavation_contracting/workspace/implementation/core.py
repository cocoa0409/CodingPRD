"""Core services: auth, audit, common-field stamping, cascades, clock advance."""
from datetime import timedelta
from functools import wraps

from flask import request

import store
from helpers import (
    ApiError, CLOCK, err, format_iso, iso_now, new_uuid, parse_iso,
)


# ---------------------------------------------------------------------------
# Roles / auth
# ---------------------------------------------------------------------------
ALL_ROLES = {
    "OpsAdmin", "ProjectManager", "Foreman",
    "SafetyOfficer", "Inspector", "UtilityOwnerRep",
}


def current_actor():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        err("ERR_UNAUTHENTICATED", 401, "X-User-Role and X-User-ID headers are required")
    if role not in ALL_ROLES:
        err("ERR_UNAUTHENTICATED", 401, f"Unrecognized role: {role}")
    return {"role": role, "user_id": user_id}


def require_roles(*allowed):
    actor = current_actor()
    if actor["role"] not in allowed:
        err(
            "ERR_UNAUTHORIZED_ROLE", 403,
            f"Role {actor['role']} is not permitted for this endpoint",
        )
    return actor


# ---------------------------------------------------------------------------
# Entity stamping
# ---------------------------------------------------------------------------
def stamp_new(entity):
    """Populate common fields on a fresh entity."""
    now = iso_now()
    entity["id"] = new_uuid()
    entity["created_at"] = now
    entity["updated_at"] = now
    entity["version"] = 1
    return entity


def touch(entity):
    """Refresh updated_at and bump version after a mutation."""
    entity["updated_at"] = iso_now()
    entity["version"] = entity.get("version", 1) + 1
    return entity


def project_id_for_entity(entity_type, entity):
    """Resolve the project scope for audit logging."""
    if entity_type == "Project":
        return entity["id"]
    if entity_type == "UtilityOwner":
        # Owners are not project-scoped; audit events still require a project_id.
        # The PRD scopes audit per project; owner registration is global. We
        # omit owner events from per-project trails by using a sentinel None.
        return None
    return entity.get("project_id") or _lookup_project_id(entity_type, entity)


def _lookup_project_id(entity_type, entity):
    if entity_type == "InstallationInspection":
        seg = store.pipe_segments.get(entity["pipe_segment_id"])
        return seg["project_id"] if seg else None
    if entity_type == "CompactionTest":
        seg = store.pipe_segments.get(entity["pipe_segment_id"])
        return seg["project_id"] if seg else None
    if entity_type == "AsBuiltPackage":
        seg = store.pipe_segments.get(entity["pipe_segment_id"])
        return seg["project_id"] if seg else None
    if entity_type == "DischargeReading":
        permit = store.discharge_permits.get(entity["discharge_permit_id"])
        return permit["project_id"] if permit else None
    return None


def audit(project_id, actor, action, entity_type, entity_id, detail):
    if project_id is None:
        return
    evt = {
        "id": new_uuid(),
        "created_at": iso_now(),
        "project_id": project_id,
        "actor_role": actor["role"] if actor else "system",
        "actor_user_id": actor["user_id"] if actor else "system",
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "detail": detail,
    }
    store.audit_events[evt["id"]] = evt
    return evt


# ---------------------------------------------------------------------------
# Work-posture / cascade helpers
# ---------------------------------------------------------------------------
def recompute_work_posture(project, actor=None):
    """Recompute posture. If it clears, resume STOP_WORK-held segments."""
    blocking = [
        c for c in store.unforeseen_conditions.values()
        if c["project_id"] == project["id"]
        and c["status"] == "OPEN"
        and c.get("stop_work_required")
    ]
    new_posture = "STOPPED" if blocking else "CLEAR"
    old = project.get("work_posture", "CLEAR")
    if new_posture == old:
        return
    project["work_posture"] = new_posture
    touch(project)
    if new_posture == "CLEAR":
        for seg in store.pipe_segments.values():
            if (
                seg["project_id"] == project["id"]
                and seg["status"] == "ON_HOLD"
                and seg.get("hold_reason") == "STOP_WORK"
            ):
                resume = seg.get("resume_status")
                if resume in ("INSTALLING", "BACKFILLING"):
                    seg["status"] = resume
                    seg["hold_reason"] = "NONE"
                    seg["resume_status"] = None
                    touch(seg)


def apply_stop_work(project, actor):
    """Project posture -> STOPPED; hold INSTALLING/BACKFILLING segments."""
    if project.get("work_posture") != "STOPPED":
        project["work_posture"] = "STOPPED"
        touch(project)
    for seg in store.pipe_segments.values():
        if seg["project_id"] != project["id"]:
            continue
        if seg["status"] in ("INSTALLING", "BACKFILLING"):
            prior = seg["status"]
            seg["status"] = "ON_HOLD"
            seg["hold_reason"] = "STOP_WORK"
            seg["resume_status"] = prior
            touch(seg)


def groundwater_readiness_recompute(project, actor):
    """VOID APPROVED SLOPING/BENCHING plans of the project; READY segments of
    voided plans revert to PLANNED."""
    open_gw = [
        c for c in store.unforeseen_conditions.values()
        if c["project_id"] == project["id"]
        and c["status"] == "OPEN"
        and c["condition_type"] == "GROUNDWATER"
    ]
    if not open_gw:
        return
    voided_plan_ids = set()
    for plan in store.trench_safety_plans.values():
        if (
            plan["project_id"] == project["id"]
            and plan["status"] == "APPROVED"
            and plan["protective_system"] in ("SLOPING", "BENCHING")
        ):
            plan["status"] = "VOIDED"
            touch(plan)
            voided_plan_ids.add(plan["id"])
            audit(
                project["id"], actor,
                "POST /site-utility/unforeseen-conditions",
                "TrenchSafetyPlan", plan["id"],
                "status APPROVED->VOIDED (groundwater)",
            )
    if not voided_plan_ids:
        return
    for seg in store.pipe_segments.values():
        if seg["project_id"] != project["id"] or seg["status"] != "READY":
            continue
        seg_plan = next(
            (p for p in store.trench_safety_plans.values()
             if p["pipe_segment_id"] == seg["id"] and p["id"] in voided_plan_ids),
            None,
        )
        if seg_plan:
            seg["status"] = "PLANNED"
            touch(seg)
            audit(
                project["id"], actor,
                "POST /site-utility/unforeseen-conditions",
                "PipeSegment", seg["id"],
                "status READY->PLANNED (plan voided)",
            )


def suspend_permit_cascade(permit, actor):
    """EXCEEDS_TURBIDITY: permit ACTIVE -> SUSPENDED, hold dewatering segments,
    cancel their PROPOSED windows."""
    if permit["status"] != "ACTIVE":
        return
    permit["status"] = "SUSPENDED"
    touch(permit)
    project = store.projects.get(permit["project_id"])
    held_segments = []
    for seg in store.pipe_segments.values():
        if (
            seg["project_id"] == permit["project_id"]
            and seg["status"] == "INSTALLING"
            and seg.get("requires_dewatering")
        ):
            seg["status"] = "ON_HOLD"
            seg["hold_reason"] = "DEWATERING"
            seg["resume_status"] = "INSTALLING"
            touch(seg)
            held_segments.append(seg)
    held_ids = {s["id"] for s in held_segments}
    for win in store.shutdown_windows.values():
        if win["pipe_segment_id"] in held_ids and win["status"] == "PROPOSED":
            win["status"] = "CANCELLED"
            touch(win)
            owner = store.utility_owners.get(win["utility_owner_id"])
            if owner:
                owner["committed_shutdown_minutes"] = max(
                    0, owner.get("committed_shutdown_minutes", 0) - win["duration_minutes"]
                )
                touch(owner)
            if project:
                audit(
                    project["id"], actor,
                    "POST /site-utility/discharge-readings",
                    "ShutdownWindow", win["id"],
                    "status PROPOSED->CANCELLED (dewatering hold)",
                )


def reinstate_permit_cascade(permit, actor):
    """SUSPENDED -> ACTIVE: resume DEWATERING-held segments."""
    project = store.projects.get(permit["project_id"])
    for seg in store.pipe_segments.values():
        if (
            seg["project_id"] == permit["project_id"]
            and seg["status"] == "ON_HOLD"
            and seg.get("hold_reason") == "DEWATERING"
        ):
            resume = seg.get("resume_status")
            if resume in ("INSTALLING", "BACKFILLING"):
                seg["status"] = resume
                seg["hold_reason"] = "NONE"
                seg["resume_status"] = None
                touch(seg)
                if project:
                    audit(
                        project["id"], actor,
                        "POST /site-utility/discharge-permits/{id}/reinstate",
                        "PipeSegment", seg["id"],
                        f"status ON_HOLD->{resume} (permit reinstated)",
                    )


def recompute_segment_compaction(seg):
    """Recompute lifts_satisfied / avg / min over ACCEPTED tests."""
    governing = [
        t for t in store.compaction_tests.values()
        if t["pipe_segment_id"] == seg["id"] and t["status"] == "ACCEPTED"
    ]
    if not governing:
        seg["lifts_satisfied"] = 0
        seg["avg_compaction_pct"] = None
        seg["min_compaction_pct"] = None
        touch(seg)
        return
    pcts = [t["compaction_pct"] for t in governing]
    from helpers import round_half_up
    avg = round_half_up(sum(pcts) / len(pcts), 1)
    seg["avg_compaction_pct"] = avg
    seg["min_compaction_pct"] = min(pcts)
    passing_lifts = {
        t["lift_number"] for t in governing
        if t["result"] == "PASS" and 1 <= t["lift_number"] <= seg["lifts_required"]
    }
    seg["lifts_satisfied"] = len(passing_lifts)
    touch(seg)


# ---------------------------------------------------------------------------
# Clock advance — pinned evaluation order
# ---------------------------------------------------------------------------
def advance_clock(to_dt, actor):
    """Advance CLOCK; fire pinned time-driven transitions.

    Order:
      (1) SUBMITTED locate tickets -> ACTIVE when now >= legal_start_at
      (2) ACTIVE/SUBMITTED tickets -> EXPIRED when now >= valid_until
      (3) Permits ISSUED->ACTIVE inside window; ISSUED/ACTIVE->EXPIRED past end
      (4) Windows: PROPOSED->MISSED at start; CONFIRMED->ACTIVE at start when
          posture CLEAR; CONFIRMED/ACTIVE->MISSED at end
    """
    CLOCK.set(to_dt)
    now = CLOCK.now()

    # (1) activate
    for ticket in list(store.locate_tickets.values()):
        if ticket["status"] == "SUBMITTED" and now >= parse_iso(ticket["legal_start_at"]):
            ticket["status"] = "ACTIVE"
            touch(ticket)
            audit(
                ticket["project_id"], actor,
                "POST /site-utility/_clock/set_current_utc",
                "LocateTicket", ticket["id"],
                "status SUBMITTED->ACTIVE (clock)",
            )
    # (2) expire
    for ticket in list(store.locate_tickets.values()):
        if ticket["status"] in ("SUBMITTED", "ACTIVE") and now >= parse_iso(ticket["valid_until"]):
            ticket["status"] = "EXPIRED"
            touch(ticket)
            audit(
                ticket["project_id"], actor,
                "POST /site-utility/_clock/set_current_utc",
                "LocateTicket", ticket["id"],
                f"status {ticket['status']}->EXPIRED (clock)".replace("EXPIRED->EXPIRED", "ACTIVE->EXPIRED"),
            )
    # (3) permits
    for permit in list(store.discharge_permits.values()):
        eff_from = parse_iso(permit["effective_from"])
        eff_to = parse_iso(permit["effective_to"])
        if permit["status"] == "ISSUED" and eff_from <= now < eff_to:
            permit["status"] = "ACTIVE"
            touch(permit)
            audit(
                permit["project_id"], actor,
                "POST /site-utility/_clock/set_current_utc",
                "DischargePermit", permit["id"],
                "status ISSUED->ACTIVE (clock)",
            )
        if permit["status"] in ("ISSUED", "ACTIVE") and now >= eff_to:
            prior = permit["status"]
            permit["status"] = "EXPIRED"
            touch(permit)
            audit(
                permit["project_id"], actor,
                "POST /site-utility/_clock/set_current_utc",
                "DischargePermit", permit["id"],
                f"status {prior}->EXPIRED (clock)",
            )
    # (4) windows
    for win in list(store.shutdown_windows.values()):
        ws = parse_iso(win["window_start"])
        we = parse_iso(win["window_end"])
        if win["status"] == "PROPOSED" and now >= ws:
            win["status"] = "MISSED"
            touch(win)
            owner = store.utility_owners.get(win["utility_owner_id"])
            if owner:
                owner["committed_shutdown_minutes"] = max(
                    0, owner.get("committed_shutdown_minutes", 0) - win["duration_minutes"]
                )
                touch(owner)
            audit(
                win["project_id"], actor,
                "POST /site-utility/_clock/set_current_utc",
                "ShutdownWindow", win["id"],
                "status PROPOSED->MISSED (clock)",
            )
            continue
        if win["status"] == "CONFIRMED" and ws <= now < we:
            project = store.projects.get(win["project_id"])
            posture = project.get("work_posture") if project else "CLEAR"
            if posture == "CLEAR":
                win["status"] = "ACTIVE"
                touch(win)
                audit(
                    win["project_id"], actor,
                    "POST /site-utility/_clock/set_current_utc",
                    "ShutdownWindow", win["id"],
                    "status CONFIRMED->ACTIVE (clock)",
                )
        if win["status"] in ("CONFIRMED", "ACTIVE") and now >= we:
            prior = win["status"]
            win["status"] = "MISSED"
            touch(win)
            owner = store.utility_owners.get(win["utility_owner_id"])
            if owner:
                owner["committed_shutdown_minutes"] = max(
                    0, owner.get("committed_shutdown_minutes", 0) - win["duration_minutes"]
                )
                touch(owner)
            audit(
                win["project_id"], actor,
                "POST /site-utility/_clock/set_current_utc",
                "ShutdownWindow", win["id"],
                f"status {prior}->MISSED (clock)",
            )


# ---------------------------------------------------------------------------
# FK / project-scope helpers
# ---------------------------------------------------------------------------
def get_or_404(collection, entity_id, label):
    obj = collection.get(entity_id)
    if not obj:
        err("ERR_NOT_FOUND", 404, f"{label} not found: {entity_id}")
    return obj


def project_of_entity(entity):
    return store.projects.get(entity.get("project_id"))
