"""Waitlist endpoints."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import db, clock, iso
from middleware import require_roles, current_user_id
from response import ok_object, ok_array
from common import (
    base_entity, touch, public, get_or_404, get_body,
    require_str, parse_pagination, paginate,
)
from errors import (
    APIError, ERR_REFERENCE_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_DUPLICATE_WAITLIST, ERR_INVALID_STATE, ERR_CLASSROOM_FULL,
    ERR_WAITLIST_EMPTY, ERR_OFFER_EXPIRED,
)
from services.domain import (
    compute_has_active_sibling, recompute_waitlist_ranks, select_promote_entry,
)
from services.pricing import offer_ttl, _parse_iso

bp = Blueprint("waitlist", __name__)


@bp.post("/classrooms/<cid>/waitlist")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def add_to_waitlist(cid):
    classroom = get_or_404(db.classrooms, cid, "classroom")
    body = get_body()
    child_id = require_str(body, "child_id")
    child = db.children.get(child_id)
    if child is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 422, "child_id does not exist")
    if g.user_role == "Parent" and current_user_id() != child["family_id"]:
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this child")
    # duplicate guard: no two WAITING/OFFERED entries for this child on this classroom
    for w in db.waitlist_entries.values():
        if w["classroom_id"] == cid and w["child_id"] == child_id and w["status"] in ("WAITING", "OFFERED"):
            raise APIError(ERR_DUPLICATE_WAITLIST, 409, "Child already on this classroom's waitlist")
    ent = base_entity()
    ent.update({
        "classroom_id": cid,
        "child_id": child_id,
        "priority_rank": 0,
        "has_active_sibling": False,
        "status": "WAITING",
        "offer_expires_at": None,
    })
    ent["has_active_sibling"] = compute_has_active_sibling(child, classroom["center_id"])
    db.waitlist_entries[ent["id"]] = ent
    recompute_waitlist_ranks(cid)
    return ok_object(public(ent), 201)


@bp.get("/classrooms/<cid>/waitlist")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def list_classroom_waitlist(cid):
    get_or_404(db.classrooms, cid, "classroom")
    limit, offset = parse_pagination()
    recompute_waitlist_ranks(cid)
    rows = [w for w in db.waitlist_entries.values() if w["classroom_id"] == cid]
    # ordered by priority_rank; terminal entries (rank unchanged) sort after by seq
    rows.sort(key=lambda w: (w["priority_rank"] if w["status"] in ("WAITING", "OFFERED") else 10**9, w["_seq"]))
    page, total = paginate(rows, limit, offset)
    return ok_array([public(w) for w in page], limit, offset, total, 200)


@bp.get("/waitlist-entries")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def list_waitlist_entries():
    limit, offset = parse_pagination()
    child_id = request.args.get("child_id")
    classroom_id = request.args.get("classroom_id")
    rows = list(db.waitlist_entries.values())
    if child_id is not None:
        rows = [w for w in rows if w["child_id"] == child_id]
    if classroom_id is not None:
        rows = [w for w in rows if w["classroom_id"] == classroom_id]
    if g.user_role == "Parent":
        uid = current_user_id()
        rows = [w for w in rows
                if (c := db.children.get(w["child_id"])) is not None and c["family_id"] == uid]
    rows.sort(key=lambda w: w["_seq"])
    page, total = paginate(rows, limit, offset)
    return ok_array([public(w) for w in page], limit, offset, total, 200)


@bp.get("/waitlist-entries/<rid>")
@require_roles("CenterDirector", "BillingAdmin", "Parent")
def get_waitlist_entry(rid):
    ent = get_or_404(db.waitlist_entries, rid, "waitlist entry")
    if g.user_role == "Parent":
        child = db.children.get(ent["child_id"])
        if child is None or child["family_id"] != current_user_id():
            raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this entry")
    return ok_object(public(ent), 200)


@bp.post("/classrooms/<cid>/waitlist/promote")
@require_roles("CenterDirector")
def promote_waitlist(cid):
    classroom = get_or_404(db.classrooms, cid, "classroom")
    # capacity gate
    if classroom["active_enrollment_count"] >= classroom["licensed_capacity"]:
        raise APIError(ERR_CLASSROOM_FULL, 409, "Classroom is full")
    entry = select_promote_entry(cid)
    if entry is None:
        raise APIError(ERR_WAITLIST_EMPTY, 409, "No WAITING entries to promote")
    entry["status"] = "OFFERED"
    entry["offer_expires_at"] = iso(offer_ttl(clock.now()))
    touch(entry)
    return ok_object(public(entry), 200)


@bp.post("/classrooms/<cid>/waitlist/expire-stale")
@require_roles("CenterDirector")
def expire_stale(cid):
    get_or_404(db.classrooms, cid, "classroom")
    now = clock.now()
    offered = [w for w in db.waitlist_entries.values()
               if w["classroom_id"] == cid and w["status"] == "OFFERED"]
    stale = [w for w in offered if w["offer_expires_at"] is not None
             and _parse_iso(w["offer_expires_at"]) < now]
    # If there are OFFERED entries but none stale, that is ERR_OFFER_EXPIRED per §3.3
    if offered and not stale:
        raise APIError(ERR_OFFER_EXPIRED, 409, "No stale offers to expire")
    swept = []
    for w in stale:
        w["status"] = "EXPIRED"
        touch(w)
        swept.append(w)
    swept.sort(key=lambda w: w["_seq"])
    limit, offset = parse_pagination()
    page, total = paginate(swept, limit, offset)
    return ok_array([public(w) for w in page], limit, offset, total, 200)


@bp.post("/waitlist-entries/<rid>/withdraw")
@require_roles("Parent")
def withdraw_waitlist(rid):
    ent = get_or_404(db.waitlist_entries, rid, "waitlist entry")
    child = db.children.get(ent["child_id"])
    if child is None or child["family_id"] != current_user_id():
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this entry")
    if ent["status"] not in ("WAITING", "OFFERED"):
        raise APIError(ERR_INVALID_STATE, 409, "Entry cannot be withdrawn from its current state")
    ent["status"] = "WITHDRAWN"
    touch(ent)
    return ok_object(public(ent), 200)
