from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles
from response import success, success_list, parse_pagination, no_content
from services import (
    MEMBER_ROLES, CONFLICT_TYPES, get_body, req_enum, get_member, get_provider,
    pub, sort_created, make_versioned, make_ledger, touch,
)

bp = Blueprint("members", __name__)

STAFF_ROLES = ("QualityDirector", "PeerReviewCoordinator", "CommitteeMember")


def _list_response(records):
    limit, offset = parse_pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([pub(r) for r in page], limit, offset, total)


@bp.post("/peer-review/committee-members")
def create_member():
    require_roles("QualityDirector")
    b = get_body()
    # stage 3: body FK existence (provider_id) when present
    pid = b.get("provider_id")
    provider = None
    if pid is not None:
        provider = store.providers.get(pid) if isinstance(pid, str) else None
        if provider is None:
            raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "provider_id does not resolve")
    # stage 8: input shape
    if not isinstance(pid, str) or not pid:
        raise ApiError("ERR_VALIDATION", 400, "provider_id is required")
    member_role = req_enum(b, "member_role", MEMBER_ROLES)
    if any(m for m in store.members.values()
           if m["provider_id"] == pid and m["status"] == "ACTIVE"):
        raise ApiError("ERR_MEMBER_ALREADY_ACTIVE_FOR_PROVIDER", 409,
                       "an ACTIVE membership already exists for this provider")
    rec = make_versioned()
    rec.update({
        "provider_id": pid,
        "specialty": provider["specialty"],  # denormalized; client value ignored
        "member_role": member_role,
        "status": "ACTIVE",
        "reliability_completed_count": 0,
    })
    store.members[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/peer-review/committee-members")
def list_members():
    require_roles(*STAFF_ROLES)
    items = sort_created(list(store.members.values()))
    q = request.args
    if q.get("provider_id") is not None:
        items = [m for m in items if m["provider_id"] == q.get("provider_id")]
    if q.get("status") is not None:
        items = [m for m in items if m["status"] == q.get("status")]
    if q.get("member_role") is not None:
        items = [m for m in items if m["member_role"] == q.get("member_role")]
    if q.get("specialty") is not None:
        items = [m for m in items if m["specialty"] == q.get("specialty")]
    return _list_response(items)


@bp.get("/peer-review/committee-members/<mid>")
def get_one_member(mid):
    require_roles(*STAFF_ROLES)
    return success(pub(get_member(mid)))


@bp.post("/peer-review/committee-members/<mid>/deactivate")
def deactivate_member(mid):
    require_roles("QualityDirector")
    member = get_member(mid)
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "member is not ACTIVE")
    member["status"] = "INACTIVE"
    touch(member)
    # cascade: every PENDING assignment flips to WAIVED; housing case bumps
    for a in store.assignments.values():
        if a["reviewer_id"] == member["id"] and a["status"] == "PENDING":
            a["status"] = "WAIVED"
            touch(a)
            case = store.cases.get(a["case_id"])
            if case is not None:
                touch(case)
    return success(pub(member))


@bp.post("/peer-review/committee-members/<mid>/activate")
def activate_member(mid):
    require_roles("QualityDirector")
    member = get_member(mid)
    if member["status"] != "INACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "member is not INACTIVE")
    if any(m for m in store.members.values()
           if m["id"] != member["id"] and m["provider_id"] == member["provider_id"]
           and m["status"] == "ACTIVE"):
        raise ApiError("ERR_MEMBER_ALREADY_ACTIVE_FOR_PROVIDER", 409,
                       "an ACTIVE membership already exists for this provider")
    member["status"] = "ACTIVE"
    touch(member)
    return success(pub(member))


@bp.post("/peer-review/committee-members/<mid>/conflict-declarations")
def declare_conflict(mid):
    actor = require_roles("CommitteeMember")
    member = get_member(mid)
    b = get_body()
    # stage 3: body FK existence (provider_id) when present
    pid = b.get("provider_id")
    if pid is not None:
        if not isinstance(pid, str) or store.providers.get(pid) is None:
            raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "provider_id does not resolve")
    # stage 4: self only
    if actor.id != member["id"]:
        raise ApiError("ERR_FORBIDDEN_RESOURCE", 403, "members may only declare their own conflicts")
    # stage 8: input shape
    if not isinstance(pid, str) or not pid:
        raise ApiError("ERR_VALIDATION", 400, "provider_id is required")
    conflict_type = req_enum(b, "conflict_type", CONFLICT_TYPES)
    if any(c for c in store.conflicts.values()
           if c["member_id"] == member["id"] and c["provider_id"] == pid):
        raise ApiError("ERR_CONFLICT_ALREADY_DECLARED", 409,
                       "a declaration for this (member_id, provider_id) already exists")
    rec = make_ledger()
    rec.update({
        "member_id": member["id"],
        "provider_id": pid,
        "conflict_type": conflict_type,
        "source": "SELF_DECLARED",
    })
    store.conflicts[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/peer-review/committee-members/<mid>/conflict-declarations")
def list_member_conflicts(mid):
    require_roles(*STAFF_ROLES)
    get_member(mid)
    items = sort_created([c for c in store.conflicts.values() if c["member_id"] == mid])
    return _list_response(items)


@bp.delete("/peer-review/conflict-declarations/<cid>")
def rescind_conflict(cid):
    actor = require_roles("CommitteeMember")
    rec = None
    for c in store.conflicts.values():
        if c["id"] == cid:
            rec = c
            break
    if rec is None:
        raise ApiError("ERR_CONFLICT_NOT_FOUND", 404, "conflict declaration not found")
    if rec["member_id"] != actor.id:
        raise ApiError("ERR_FORBIDDEN_RESOURCE", 403, "only the declaring member may rescind")
    del store.conflicts[cid]
    return no_content()


@bp.get("/peer-review/committee-members/<mid>/assignments")
def list_member_assignments(mid):
    require_roles(*STAFF_ROLES)
    get_member(mid)
    items = sort_created([a for a in store.assignments.values() if a["reviewer_id"] == mid])
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    return _list_response(items)


@bp.get("/peer-review/committee-members/<mid>/notes")
def list_member_notes(mid):
    require_roles(*STAFF_ROLES)
    get_member(mid)
    items = sort_created([n for n in store.notes.values() if n["author_member_id"] == mid])
    return _list_response(items)


@bp.get("/peer-review/committee-members/<mid>/focus-group-memberships")
def list_member_focus_memberships(mid):
    require_roles(*STAFF_ROLES)
    get_member(mid)
    items = sort_created([g for g in store.focus_group_members.values() if g["member_id"] == mid])
    return _list_response(items)
