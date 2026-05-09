"""KeyResult endpoints + ProgressUpdate appender."""

from flask import Blueprint, request

import db
from audit import write_audit
from auth import require_role, is_owner_or_co_owner
from clock import now, format_ts
from envelope import success_object, success_array, empty_204
from errors import ApiError
from serialize import s_kr, s_progress, s_objective
from services.score import recompute_kr_score, recompute_objective_progress
from util import (get_json_body, parse_pagination, paginate, require_fields,
                  stamp_create, stamp_update, actor_id, actor_role, round4,
                  gen_id)


bp = Blueprint("key_results", __name__)


def _audit_kr(kr, action, before=None, after=None, system=False):
    write_audit(entity_type="KEY_RESULT", entity_id=kr["id"], action=action,
                before=before, after=after,
                actor_override="SYSTEM" if system else None,
                role_override="SYSTEM" if system else None)


def _audit_obj(o, action, before=None, after=None):
    write_audit(entity_type="OBJECTIVE", entity_id=o["id"], action=action,
                before=before, after=after)


def _stale_for_kr(kr) -> bool:
    """Compute stale flag at read time."""
    if kr["status"] != "ACTIVE":
        return False
    obj = db.objectives.get(kr["objective_id"])
    if not obj:
        return False
    from clock import parse_ts, now as logical_now
    last = kr.get("last_update_at")
    baseline = parse_ts(last) if last else parse_ts(obj["created_at"])
    diff = logical_now() - baseline
    age_days = int(diff.total_seconds() // 86400)  # truncate
    return age_days >= 14


def _kr_payload(kr):
    out = s_kr(kr)
    out["stale"] = _stale_for_kr(kr)
    return out


@bp.post("/objectives/<id>/key-results")
def create_kr(id):
    require_role("PlatformAdmin", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(o, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    cycle = db.cycles.get(o["cycle_id"])
    if cycle is None or cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409, "cycle not OPEN")
    if o["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_OBJECTIVE_NOT_ACTIVE", 409, f"objective status {o['status']}")
    body = get_json_body()
    require_fields(body, "title", "measurement_type", "weight")
    title = body["title"]
    mt = body["measurement_type"]
    weight = body["weight"]
    if mt not in ("NUMERIC", "PERCENTAGE", "MILESTONE"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "measurement_type invalid")
    try:
        w = float(weight)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "weight must be number")
    if w < 0 or w > 1:
        raise ApiError("ERR_INVALID_REQUEST", 400, "weight out of range")

    sv = body.get("start_value")
    tv = body.get("target_value")
    ms = body.get("milestones") or []

    if mt == "MILESTONE":
        if sv is not None or tv is not None:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "MILESTONE KR must not declare start_value/target_value")
        if not isinstance(ms, list):
            raise ApiError("ERR_INVALID_REQUEST", 400, "milestones must be list")
        # normalize: each {label,completed}
        normed = []
        for m in ms:
            if not isinstance(m, dict):
                raise ApiError("ERR_INVALID_REQUEST", 400, "milestone must be object")
            normed.append({"label": str(m.get("label", "")), "completed": bool(m.get("completed"))})
        ms = normed
        sv = None
        tv = None
        cv = None
    else:
        if ms:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "milestones must be empty for NUMERIC/PERCENTAGE")
        ms = []
        if sv is None or tv is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "start_value/target_value required")
        try:
            sv = float(sv)
            tv = float(tv)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "start/target must be numeric")
        if mt == "PERCENTAGE":
            if not (0 <= sv <= 1) or not (0 <= tv <= 1):
                raise ApiError("ERR_INVALID_REQUEST", 400, "PERCENTAGE values must be in [0,1]")
        cv = sv

    kr = {
        "objective_id": o["id"],
        "title": title,
        "measurement_type": mt,
        "start_value": sv,
        "target_value": tv,
        "current_value": cv,
        "milestones": ms,
        "weight": round4(w),
        "score": 0.0,
        "status": "ACTIVE",
        "last_update_at": None,
    }
    stamp_create(kr)
    recompute_kr_score(kr)
    db.key_results[kr["id"]] = kr
    # PRD §3.3: weight sum is rechecked when KRs are added to an ACTIVE objective.
    if o["status"] == "ACTIVE":
        active_weights = [k["weight"] for k in db.key_results.values()
                          if k["objective_id"] == o["id"] and k["status"] == "ACTIVE"]
        s = sum(active_weights)
        if abs(s - 1.0) > 0.0001:
            del db.key_results[kr["id"]]
            raise ApiError("ERR_KR_WEIGHTS_INVALID", 422,
                           f"active KR weight sum {s} fails tolerance")
    obj_before = s_objective(o)
    recompute_objective_progress(o, cascade_up=True)
    stamp_update(o)
    _audit_kr(kr, "CREATE", after=s_kr(kr))
    _audit_obj(o, "UPDATE", before=obj_before, after=s_objective(o))
    return success_object(_kr_payload(kr), status=201)


@bp.get("/objectives/<id>/key-results")
def list_krs(id):
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    o = db.objectives.get(id)
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = [k for k in db.key_results.values() if k["objective_id"] == id]
    if status:
        items = [k for k in items if k["status"] == status]
    items.sort(key=lambda k: k["created_at"])
    page, total = paginate(items, limit, offset)
    return success_array([_kr_payload(k) for k in page], total, limit, offset)


@bp.get("/key-results/<id>")
def read_kr(id):
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    k = db.key_results.get(id)
    if not k:
        raise ApiError("ERR_KR_NOT_FOUND", 404, "key result not found")
    return success_object(_kr_payload(k))


@bp.patch("/key-results/<id>")
def patch_kr(id):
    require_role("PlatformAdmin", "Manager", "Employee")
    k = db.key_results.get(id)
    if not k:
        raise ApiError("ERR_KR_NOT_FOUND", 404, "key result not found")
    o = db.objectives.get(k["objective_id"])
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(o, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    body = get_json_body()
    if "version" in body and body["version"] is not None:
        if int(body["version"]) != int(k["version"]):
            raise ApiError("ERR_VERSION_CONFLICT", 409, "version mismatch")
    # State: parent must be DRAFT or ACTIVE-with-no-progress
    if o["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_INVALID_STATE", 409, f"parent objective in {o['status']}")
    if o["status"] == "ACTIVE":
        for p in db.progress_updates.values():
            if p["key_result_id"] == k["id"]:
                raise ApiError("ERR_INVALID_STATE", 409, "progress already recorded")
    before = s_kr(k)
    if "title" in body and body["title"] is not None:
        k["title"] = body["title"]
    if "weight" in body and body["weight"] is not None:
        try:
            w = float(body["weight"])
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "weight must be number")
        if w < 0 or w > 1:
            raise ApiError("ERR_INVALID_REQUEST", 400, "weight out of range")
        k["weight"] = round4(w)
    if "target_value" in body and body["target_value"] is not None:
        if k["measurement_type"] == "MILESTONE":
            raise ApiError("ERR_INVALID_REQUEST", 400, "target_value not applicable for MILESTONE")
        try:
            tv = float(body["target_value"])
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "target_value must be number")
        if k["measurement_type"] == "PERCENTAGE" and not (0 <= tv <= 1):
            raise ApiError("ERR_INVALID_REQUEST", 400, "PERCENTAGE target must be in [0,1]")
        k["target_value"] = tv
    stamp_update(k)
    recompute_kr_score(k)
    obj_before = s_objective(o)
    recompute_objective_progress(o, cascade_up=True)
    stamp_update(o)
    _audit_kr(k, "UPDATE", before=before, after=s_kr(k))
    _audit_obj(o, "UPDATE", before=obj_before, after=s_objective(o))
    return success_object(_kr_payload(k))


@bp.delete("/key-results/<id>")
def delete_kr(id):
    require_role("PlatformAdmin", "Manager", "Employee")
    k = db.key_results.get(id)
    if not k:
        raise ApiError("ERR_KR_NOT_FOUND", 404, "key result not found")
    o = db.objectives.get(k["objective_id"])
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(o, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    if o["status"] in ("IN_REVIEW", "LOCKED", "ARCHIVED"):
        raise ApiError("ERR_INVALID_STATE", 409, f"parent in {o['status']}")
    for p in db.progress_updates.values():
        if p["key_result_id"] == k["id"]:
            raise ApiError("ERR_INVALID_STATE", 409, "progress recorded; cannot soft-delete")
    if k["status"] == "ARCHIVED":
        raise ApiError("ERR_INVALID_STATE", 409, "already archived")
    before = s_kr(k)
    k["status"] = "ARCHIVED"
    stamp_update(k)
    obj_before = s_objective(o)
    recompute_objective_progress(o, cascade_up=True)
    stamp_update(o)
    _audit_kr(k, "DELETE", before=before, after=s_kr(k))
    _audit_obj(o, "UPDATE", before=obj_before, after=s_objective(o))
    return empty_204()


@bp.post("/key-results/<id>/progress")
def append_progress(id):
    require_role("PlatformAdmin", "Manager", "Employee")
    k = db.key_results.get(id)
    if not k:
        raise ApiError("ERR_KR_NOT_FOUND", 404, "key result not found")
    o = db.objectives.get(k["objective_id"])
    if not o:
        raise ApiError("ERR_OBJECTIVE_NOT_FOUND", 404, "objective not found")
    aid = actor_id()
    arole = actor_role()
    if arole != "PlatformAdmin" and not is_owner_or_co_owner(o, aid):
        raise ApiError("ERR_NOT_OWNER", 403, "must be owner or co-owner")
    cycle = db.cycles.get(o["cycle_id"])
    if cycle is None or cycle["status"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN", 409, "cycle not OPEN")
    if o["status"] != "ACTIVE":
        raise ApiError("ERR_OBJECTIVE_NOT_ACTIVE", 409, f"objective {o['status']}")
    if k["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, f"KR is {k['status']}")
    body = get_json_body()
    require_fields(body, "update_type")
    ut = body["update_type"]
    if ut not in ("VALUE_CHANGE", "MILESTONE_TOGGLE"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "update_type invalid")
    mt = k["measurement_type"]
    if ut == "VALUE_CHANGE" and mt not in ("NUMERIC", "PERCENTAGE"):
        raise ApiError("ERR_KR_TYPE_MISMATCH", 422, "VALUE_CHANGE requires NUMERIC/PERCENTAGE")
    if ut == "MILESTONE_TOGGLE" and mt != "MILESTONE":
        raise ApiError("ERR_KR_TYPE_MISMATCH", 422, "MILESTONE_TOGGLE requires MILESTONE KR")

    pu = {
        "key_result_id": k["id"],
        "update_type": ut,
        "new_value": None,
        "milestone_index": None,
        "milestone_completed": None,
        "comment": body.get("comment"),
        "actor_user_id": aid,
        "score_at_update": None,
        "id": gen_id(),
        "created_at": format_ts(now()),
    }

    if ut == "VALUE_CHANGE":
        new_value = body.get("new_value")
        if new_value is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "new_value required for VALUE_CHANGE")
        try:
            nv = float(new_value)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "new_value must be number")
        sv = k["start_value"]
        tv = k["target_value"]
        # Sign-aware range
        lo, hi = (sv, tv) if tv >= sv else (tv, sv)
        if not (lo <= nv <= hi):
            raise ApiError("ERR_PROGRESS_OUT_OF_RANGE", 422,
                           f"new_value {nv} out of range [{lo},{hi}]")
        if mt == "PERCENTAGE" and not (0 <= nv <= 1):
            raise ApiError("ERR_PROGRESS_OUT_OF_RANGE", 422,
                           "PERCENTAGE new_value must be in [0,1]")
        k["current_value"] = nv
        pu["new_value"] = nv
    else:
        idx = body.get("milestone_index")
        completed = body.get("milestone_completed")
        if idx is None or completed is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "milestone_index and milestone_completed required")
        try:
            idx_i = int(idx)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "milestone_index must be int")
        if idx_i < 0 or idx_i >= len(k["milestones"]):
            raise ApiError("ERR_INVALID_REQUEST", 400, "milestone_index out of bounds")
        k["milestones"][idx_i]["completed"] = bool(completed)
        pu["milestone_index"] = idx_i
        pu["milestone_completed"] = bool(completed)

    k["last_update_at"] = format_ts(now())
    recompute_kr_score(k)
    pu["score_at_update"] = k["score"]
    db.progress_updates[pu["id"]] = pu
    stamp_update(k)
    obj_before = s_objective(o)
    recompute_objective_progress(o, cascade_up=True)
    stamp_update(o)
    _audit_kr(k, "SCORE_CHANGE", before=None, after={"score": k["score"]})
    _audit_obj(o, "UPDATE", before=obj_before, after=s_objective(o))
    return success_object(s_progress(pu), status=201)


@bp.get("/key-results/<id>/progress")
def list_progress(id):
    require_role("PlatformAdmin", "HRBP", "Manager", "Employee")
    k = db.key_results.get(id)
    if not k:
        raise ApiError("ERR_KR_NOT_FOUND", 404, "key result not found")
    limit, offset = parse_pagination()
    items = [p for p in db.progress_updates.values() if p["key_result_id"] == id]
    items.sort(key=lambda p: p["created_at"])
    page, total = paginate(items, limit, offset)
    return success_array([s_progress(p) for p in page], total, limit, offset)
