from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles
from response import success, success_list, parse_pagination, no_content
from services import (
    get_body, req_str, opt_str, get_focused_review, get_focus_group,
    pub, sort_created, make_versioned, make_ledger, touch, now_iso,
    active_focused_review,
)

bp = Blueprint("focus", __name__)

STAFF_ROLES = ("QualityDirector", "PeerReviewCoordinator", "CommitteeMember")


def _list_response(records):
    limit, offset = parse_pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([pub(r) for r in page], limit, offset, total)


@bp.post("/peer-review/focused-reviews")
def create_focused_review():
    require_roles("QualityDirector")
    b = get_body()
    # stage 3: body FK existence
    pid = b.get("provider_id")
    if pid is not None:
        if not isinstance(pid, str) or store.providers.get(pid) is None:
            raise ApiError("ERR_PROVIDER_NOT_FOUND", 404, "provider_id does not resolve")
    # stage 8: input shape
    if not isinstance(pid, str) or not pid:
        raise ApiError("ERR_VALIDATION", 400, "provider_id is required")
    basis = opt_str(b, "basis")
    # stage 10: aggregate uniqueness (at most one ACTIVE per provider)
    if active_focused_review(pid) is not None:
        raise ApiError("ERR_FOCUSED_REVIEW_ALREADY_ACTIVE", 409,
                       "provider already has an ACTIVE focused review")
    rec = make_versioned()
    rec.update({
        "provider_id": pid,
        "trigger_type": "MANUAL",
        "basis": basis,
        "trigger_snapshot": None,
        "status": "ACTIVE",
        "opened_at": now_iso(),
        "closed_at": None,
        "resolution_note": None,
    })
    store.focused_reviews[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/peer-review/focused-reviews")
def list_focused_reviews():
    require_roles(*STAFF_ROLES)
    items = sort_created(list(store.focused_reviews.values()))
    q = request.args
    if q.get("provider_id") is not None:
        items = [f for f in items if f["provider_id"] == q.get("provider_id")]
    if q.get("status") is not None:
        items = [f for f in items if f["status"] == q.get("status")]
    return _list_response(items)


@bp.get("/peer-review/focused-reviews/<fid>")
def get_one_focused_review(fid):
    require_roles(*STAFF_ROLES)
    return success(pub(get_focused_review(fid)))


@bp.post("/peer-review/focused-reviews/<fid>/close")
def close_focused_review(fid):
    require_roles("QualityDirector")
    fr = get_focused_review(fid)
    if fr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "focused review is not ACTIVE")
    b = get_body()
    note = req_str(b, "resolution_note")
    fr["status"] = "CLOSED"
    fr["closed_at"] = now_iso()
    fr["resolution_note"] = note
    touch(fr)
    return success(pub(fr))


@bp.post("/peer-review/focused-reviews/<fid>/focus-groups")
def create_focus_group(fid):
    require_roles("QualityDirector")
    fr = get_focused_review(fid)
    if fr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "focused review is not ACTIVE")
    b = get_body()
    name = req_str(b, "name")
    rec = make_versioned()
    rec.update({"focus_id": fid, "name": name})
    store.focus_groups[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/peer-review/focused-reviews/<fid>/focus-groups")
def list_focus_groups(fid):
    require_roles(*STAFF_ROLES)
    get_focused_review(fid)
    items = sort_created([g for g in store.focus_groups.values() if g["focus_id"] == fid])
    return _list_response(items)


@bp.get("/peer-review/focus-groups/<gid>")
def get_one_focus_group(gid):
    require_roles(*STAFF_ROLES)
    return success(pub(get_focus_group(gid)))


@bp.get("/peer-review/focus-groups/<gid>/cases")
def list_focus_group_cases(gid):
    require_roles(*STAFF_ROLES)
    get_focus_group(gid)
    items = sort_created([c for c in store.cases.values() if c["focus_group_id"] == gid])
    return _list_response(items)


@bp.post("/peer-review/focus-groups/<gid>/members")
def add_focus_group_member(gid):
    require_roles("QualityDirector")
    group = get_focus_group(gid)
    b = get_body()
    # stage 3: body FK existence (member_id) when present
    mid = b.get("member_id")
    member = None
    if mid is not None:
        member = store.members.get(mid) if isinstance(mid, str) else None
        if member is None:
            raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "member_id does not resolve")
    # stage 5: parent focused review must be ACTIVE
    fr = store.focused_reviews.get(group["focus_id"])
    if fr is None or fr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "focused review is not ACTIVE")
    # stage 8: input shape, then membership constraints
    if not isinstance(mid, str) or not mid:
        raise ApiError("ERR_VALIDATION", 400, "member_id is required")
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_REVIEWER_INACTIVE", 422, "member is not ACTIVE")
    if any(gm for gm in store.focus_group_members.values()
           if gm["focus_group_id"] == gid and gm["member_id"] == mid):
        raise ApiError("ERR_DUPLICATE_FOCUS_MEMBER", 409, "member is already in the focus group")
    rec = make_ledger()
    rec.update({"focus_group_id": gid, "member_id": mid})
    store.focus_group_members[rec["id"]] = rec
    return success(pub(rec), 201)


@bp.get("/peer-review/focus-groups/<gid>/members")
def list_focus_group_members(gid):
    require_roles(*STAFF_ROLES)
    get_focus_group(gid)
    items = sort_created([gm for gm in store.focus_group_members.values()
                          if gm["focus_group_id"] == gid])
    return _list_response(items)


@bp.delete("/peer-review/focus-groups/<gid>/members/<member_id>")
def remove_focus_group_member(gid, member_id):
    require_roles("QualityDirector")
    get_focus_group(gid)
    rec = None
    for gm in store.focus_group_members.values():
        if gm["focus_group_id"] == gid and gm["member_id"] == member_id:
            rec = gm
            break
    if rec is None:
        raise ApiError("ERR_MEMBERSHIP_NOT_FOUND", 404, "no membership row for this (group, member) pair")
    del store.focus_group_members[rec["id"]]
    return no_content()
