"""Objective endpoints."""

from flask import Blueprint, request

import db
from audit import write_audit
from auth import require_role, is_owner_or_co_owner
from envelope import success_object, success_array, empty_204
from errors import ApiError
from serialize import s_objective, s_link
from services.score import recompute_objective_progress
from services.visibility import is_visible
from services.alignment import (compute_forward_impact, compute_backward_impact,
                                count_accepted_upstreams)
from util import (get_json_body, parse_pagination, paginate, require_fields,
                  stamp_create, stamp_update, actor_id, actor_role, round4)


bp = Blueprint("objectives", __name__)

LEVEL_RANK = {"COMPANY": 4, "DEPARTMENT": 3, "TEAM": 2, "INDIVIDUAL": 1}


def _audit_objective(obj, action, before=None, after=None, system=False):
    write_audit(entity_type="OBJECTIVE", entity_id=obj["id"], action=action,
                before=before, after=after,
                actor_override="SYSTEM" if system else None,
                role_override="SYSTEM" if system else None)


def _audit_link(link, action, before=None, after=None, system=False):
    write_audit(entity_type="ALIGNMENT_LINK", entity_id=link["id"], action=action,
                before=before, after=after,
                actor_override="SYSTEM" if system else None,
                role_override="SYSTEM" if system else None)


@bp.post("/objectives")
def create_objective():
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    body = get_json_body()
    require_fields(body, "cycle_id", "level", "department_id", "owner_user_id", "title", "weight")
    cycle_id = body["cycle_id"]
    level = body["level"]
    dept_id = body["department_id"]
    owner_user_id = body["owner_user_id"]
    title = body["title"]
    weight = body["weight"]
    description = body.get("description", "")
    confidential = body.get("confidential", False)
    parent_id = body.get("parent_objective_id")

    # Existence
    cycle = db.cycles.get(cycle_id)
    if not cycle:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle not found")
    if level not in LEVEL_RANK:
        raise ApiError("ERR_INVALID_REQUEST", 400, "level invalid")
    if owner_user_id not in db.users:
        raise ApiError("ERR_USER_NOT_FOUND", 404, "owner user not found")
    if dept_id is not None and dept_id not in db.departments:
        raise ApiError("ERR_DEPARTMENT_NOT_FOUND", 404, "department not found")
    if parent_id is not None and parent_id not in db.objectives:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "parent objective not found")

    # State: cycle must be OPEN for creation
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409, f"cycle status is {cycle['status']}")

    # Parent referential
    if parent_id is not None:
        parent = db.objectives[parent_id]
        # Same cycle
        if parent["cycle_id"] != cycle_id:
            raise ApiError("ERR_PARENT_NOT_IN_SAME_CYCLE", 422, "parent.cycle_id != child.cycle_id")
        # Parent level rank exactly one above
        if LEVEL_RANK[parent["level"]] - LEVEL_RANK[level] != 1:
            raise ApiError("ERR_PARENT_LEVEL_INVALID", 422, "parent level not exactly one rank above")

    # Weight bounds
    try:
        weight_f = float(weight)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "weight must be number")
    if weight_f < 0 or weight_f > 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "weight out of range")

    obj = {
        "cycle_id": cycle_id,
        "parent_objective_id": parent_id,
        "level": level,
        "department_id": dept_id,
        "owner_user_id": owner_user_id,
        "title": title,
        "description": description,
        "weight": round4(weight_f),
        "confidential": bool(confidential),
        "status": "DRAFT",
        "progress": 0.0,
        "final_score": None,
        "stale_warning_count": 0,
        "kr_count": 0,
        "child_count": 0,
    }
    stamp_create(obj)
    db.objectives[obj["id"]] = obj
    _audit_objective(obj, "CREATE", after=s_objective(obj))
    return success_object(s_objective(obj), status=201)


@bp.get("/objectives")
def list_objectives():
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    limit, offset = parse_pagination()
    aid = actor_id()
    arole = actor_role()
    items = list(db.objectives.values())
    cycle_id = request.args.get("cycle_id")
    level = request.args.get("level")
    owner_user_id = request.args.get("owner_user_id")
    status = request.args.get("status")
    department_id = request.args.get("department_id")
    confidential = request.args.get("confidential")
    if cycle_id is not None:
        items = [o for o in items if o["cycle_id"] == cycle_id]
    if level is not None:
        items = [o for o in items if o["level"] == level]
    if owner_user_id is not None:
        items = [o for o in items if o["owner_user_id"] == owner_user_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    if department_id is not None:
        items = [o for o in items if o["department_id"] == department_id]
    if confidential is not None:
        want = confidential.lower() in ("true", "1", "yes")
        items = [o for o in items if bool(o["confidential"]) == want]
    # Visibility filter
    items = [o for o in items if is_visible(o, aid, arole)]
    items.sort(key=lambda o: o["created_at"])
    page, total = paginate(items, limit, offset)
    return success_array([s_objective(o) for o in page], total, limit, offset)


@bp.get("/objectives/<id>")
def read_objective(id):
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    if not is_visible(o, actor_id(), actor_role()):
        raise ApiError("ERR_NOT_VISIBLE", 403, "objective is confidential")
    return success_object(s_objective(o))


@bp.patch("/objectives/<id>")
def patch_objective(id):
    require_role("PlatformAdmin", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    arole = actor_role()
    aid = actor_id()
    # Ownership: PlatformAdmin or owner/co-owner
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(o, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    body = get_json_body()
    # OCC
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(o["version"]):
            raise ApiError("ERR_VERSION_CONFLICT", 409, "version mismatch")
    before = s_objective(o)
    if "title" in body and body["title"] is not None:
        o["title"] = body["title"]
    if "description" in body and body["description"] is not None:
        o["description"] = body["description"]
    if "weight" in body and body["weight"] is not None:
        try:
            w = float(body["weight"])
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "weight must be number")
        if w < 0 or w > 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "weight out of range")
        o["weight"] = round4(w)
    if "confidential" in body and body["confidential"] is not None:
        o["confidential"] = bool(body["confidential"])
    stamp_update(o)
    _audit_objective(o, "UPDATE", before=before, after=s_objective(o))
    return success_object(s_objective(o))


@bp.post("/objectives/<id>/publish")
def publish_objective(id):
    require_role("PlatformAdmin", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(o, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    cycle = db.cycles.get(o["cycle_id"])
    if not cycle:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle not found")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409, f"cycle status is {cycle['status']}")
    if o["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, f"objective in status {o['status']}")
    # Parent active check
    if o.get("parent_objective_id"):
        parent = db.objectives.get(o["parent_objective_id"])
        if not parent or parent["status"] != "ACTIVE":
            raise ApiError("ERR_PARENT_NOT_ACTIVE", 422, "parent not ACTIVE")
        # Re-check level + cycle (keeps invariants enforced even if parent changed)
        if LEVEL_RANK[parent["level"]] - LEVEL_RANK[o["level"]] != 1:
            raise ApiError("ERR_PARENT_LEVEL_INVALID", 422, "parent level not exactly one rank above")
        if parent["cycle_id"] != o["cycle_id"]:
            raise ApiError("ERR_PARENT_NOT_IN_SAME_CYCLE", 422, "parent not in same cycle")

    active_krs = [k for k in db.key_results.values()
                  if k["objective_id"] == o["id"] and k["status"] == "ACTIVE"]
    active_children = [c for c in db.objectives.values()
                       if c.get("parent_objective_id") == o["id"] and c["status"] == "ACTIVE"]

    if active_krs and active_children:
        raise ApiError("ERR_OBJECTIVE_KR_OR_CHILDREN", 422,
                       "objective has both KRs and child objectives")
    if not active_krs and not active_children:
        raise ApiError("ERR_KR_WEIGHTS_INVALID", 422, "no KRs or children to publish with")
    if active_krs:
        ws = sum(float(k["weight"]) for k in active_krs)
        if abs(ws - 1.0) > 1e-4:
            raise ApiError("ERR_KR_WEIGHTS_INVALID", 422, f"KR weights sum to {ws}")
    else:
        ws = sum(float(c["weight"]) for c in active_children)
        if abs(ws - 1.0) > 1e-4:
            raise ApiError("ERR_KR_WEIGHTS_INVALID", 422, f"child objective weights sum to {ws}")

    before = s_objective(o)
    o["status"] = "ACTIVE"
    stamp_update(o)
    recompute_objective_progress(o, cascade_up=True)
    _audit_objective(o, "STATE_TRANSITION", before=before, after=s_objective(o))
    return success_object(s_objective(o))


@bp.post("/objectives/<id>/revert")
def revert_objective(id):
    require_role("PlatformAdmin", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(o, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    cycle = db.cycles.get(o["cycle_id"])
    if not cycle:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle not found")
    if cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409, f"cycle status is {cycle['status']}")
    if o["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, f"objective in status {o['status']}")
    # No progress on any KR
    obj_kr_ids = {k["id"] for k in db.key_results.values() if k["objective_id"] == o["id"]}
    for p in db.progress_updates.values():
        if p["key_result_id"] in obj_kr_ids:
            raise ApiError("ERR_INVALID_STATE", 409, "progress already recorded")
    # No accepted alignment link
    for l in db.alignment_links.values():
        if l["status"] == "ACCEPTED" and (l["upstream_objective_id"] == o["id"] or l["downstream_objective_id"] == o["id"]):
            raise ApiError("ERR_INVALID_STATE", 409, "ACCEPTED alignment link references this objective")
    # No active child
    for c in db.objectives.values():
        if c.get("parent_objective_id") == o["id"] and c["status"] == "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "ACTIVE child objective exists")
    before = s_objective(o)
    o["status"] = "DRAFT"
    stamp_update(o)
    _audit_objective(o, "STATE_TRANSITION", before=before, after=s_objective(o))
    return success_object(s_objective(o))


@bp.post("/objectives/<id>/archive")
def archive_objective_admin(id):
    require_role("PlatformAdmin")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    cycle = db.cycles.get(o["cycle_id"])
    if not cycle:
        raise ApiError("ERR_CYCLE_NOT_FOUND", 404, "cycle not found")
    if cycle["status"] not in ("OPEN", "LOCKED"):
        raise ApiError("ERR_INVALID_STATE", 409, f"cycle status is {cycle['status']}")
    if o["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, f"objective in status {o['status']}")
    # No ACTIVE child
    for c in db.objectives.values():
        if c.get("parent_objective_id") == o["id"] and c["status"] == "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", 409, "ACTIVE child objective exists")
    before = s_objective(o)
    o["status"] = "ARCHIVED"
    stamp_update(o)
    # Cascade ACCEPTED links touching this objective -> BROKEN
    for l in db.alignment_links.values():
        if l["status"] == "ACCEPTED" and (l["upstream_objective_id"] == o["id"] or l["downstream_objective_id"] == o["id"]):
            li_before = s_link(l)
            l["status"] = "BROKEN"
            stamp_update(l)
            write_audit(entity_type="ALIGNMENT_LINK", entity_id=l["id"],
                        action="STATE_TRANSITION", before=li_before, after=s_link(l),
                        actor_override="SYSTEM", role_override="SYSTEM")
    _audit_objective(o, "STATE_TRANSITION", before=before, after=s_objective(o))
    return success_object(s_objective(o))


@bp.get("/objectives/<id>/impact-graph")
def impact_graph(id):
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    if not is_visible(o, actor_id(), actor_role()):
        raise ApiError("ERR_NOT_VISIBLE", 403, "objective is confidential")
    upstream = []
    downstream = []
    for l in db.alignment_links.values():
        if l["status"] != "ACCEPTED":
            continue
        if l["downstream_objective_id"] == id:
            entry = dict(s_link(l))
            entry["forward_impact_score"] = compute_forward_impact(l)
            entry["backward_impact_score"] = compute_backward_impact(l)
            upstream.append(entry)
        if l["upstream_objective_id"] == id:
            entry = dict(s_link(l))
            entry["forward_impact_score"] = compute_forward_impact(l)
            entry["backward_impact_score"] = compute_backward_impact(l)
            downstream.append(entry)
    return success_object({
        "objective_id": id,
        "upstream": upstream,
        "downstream": downstream,
    })
