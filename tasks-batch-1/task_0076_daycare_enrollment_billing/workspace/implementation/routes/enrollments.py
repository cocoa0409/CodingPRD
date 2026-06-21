"""Enrollment endpoints and lifecycle."""
from __future__ import annotations

from flask import Blueprint, g, request

from db import db, clock
from middleware import require_roles, current_user_id
from response import ok_object, ok_array
from common import (
    base_entity, touch, public, get_or_404, get_body,
    require_str, require_int, parse_pagination, paginate,
)
from errors import (
    APIError, ERR_REFERENCE_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_INVALID_STATE, ERR_OFFER_EXPIRED, ERR_AGE_BAND_MISMATCH,
    ERR_DUPLICATE_ENROLLMENT, ERR_CLASSROOM_FULL, ERR_STALE_VERSION,
)
from services.pricing import (
    compute_sliding_scale_tier, parent_share_for_tier,
    compute_monthly_net_tuition, recompute_sibling_cascade, _parse_iso,
)
from services.domain import recompute_classroom_status, age_band_fits

bp = Blueprint("enrollments", __name__)

NON_TERMINAL = ("OFFERED", "ACCEPTED", "ACTIVE")


@bp.post("/enrollments")
@require_roles("CenterDirector")
def create_enrollment():
    body = get_body()
    child_id = require_str(body, "child_id")
    classroom_id = require_str(body, "classroom_id")
    expected_version = require_int(body, "expected_classroom_version")
    waitlist_entry_id = body.get("waitlist_entry_id")
    if waitlist_entry_id is not None and not isinstance(waitlist_entry_id, str):
        from errors import ERR_INVALID_REQUEST
        raise APIError(ERR_INVALID_REQUEST, 400, "waitlist_entry_id must be a string")

    # body FK existence (priority 4)
    child = db.children.get(child_id)
    if child is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 422, "child_id does not exist")
    classroom = db.classrooms.get(classroom_id)
    if classroom is None:
        raise APIError(ERR_REFERENCE_NOT_FOUND, 422, "classroom_id does not exist")
    wl = None
    if waitlist_entry_id is not None:
        wl = db.waitlist_entries.get(waitlist_entry_id)
        if wl is None:
            raise APIError(ERR_REFERENCE_NOT_FOUND, 422, "waitlist_entry_id does not exist")

    # offer-expiry / state for the waitlist entry (priority 8)
    if wl is not None:
        if wl["status"] != "OFFERED":
            raise APIError(ERR_INVALID_STATE, 409, "Waitlist entry is not OFFERED")
        if wl["offer_expires_at"] is not None and clock.now() > _parse_iso(wl["offer_expires_at"]):
            raise APIError(ERR_OFFER_EXPIRED, 409, "Offer has expired")

    # duplicate enrollment guard (priority 10)
    for e in db.enrollments.values():
        if e["child_id"] == child_id and e["status"] in NON_TERMINAL:
            raise APIError(ERR_DUPLICATE_ENROLLMENT, 409, "Child already has a non-terminal enrollment")

    # OCC (priority 18)
    if expected_version != classroom["version"]:
        raise APIError(ERR_STALE_VERSION, 412, "Classroom version mismatch")

    ent = base_entity()
    ent.update({
        "child_id": child_id,
        "classroom_id": classroom_id,
        "waitlist_entry_id": waitlist_entry_id,
        "status": "OFFERED",
        "sibling_discount_pct": 0,
        "locked_base_tuition_cents": 0,
        "locked_parent_share_pct": 100,
        "monthly_net_tuition_cents": 0,
    })
    db.enrollments[ent["id"]] = ent

    # convert the waitlist entry
    if wl is not None:
        wl["status"] = "CONVERTED"
        touch(wl)

    # increment classroom version
    touch(classroom)

    return ok_object(public(ent), 201)


@bp.get("/enrollments")
@require_roles("CenterDirector", "BillingAdmin", "Parent", "Teacher")
def list_enrollments():
    limit, offset = parse_pagination()
    child_id = request.args.get("child_id")
    classroom_id = request.args.get("classroom_id")
    waitlist_entry_id = request.args.get("waitlist_entry_id")
    rows = list(db.enrollments.values())
    if child_id is not None:
        rows = [e for e in rows if e["child_id"] == child_id]
    if classroom_id is not None:
        rows = [e for e in rows if e["classroom_id"] == classroom_id]
    if waitlist_entry_id is not None:
        rows = [e for e in rows if e["waitlist_entry_id"] == waitlist_entry_id]
    if g.user_role == "Parent":
        uid = current_user_id()
        rows = [e for e in rows
                if (c := db.children.get(e["child_id"])) is not None and c["family_id"] == uid]
    elif g.user_role == "Teacher":
        uid = current_user_id()
        rows = [e for e in rows if e["classroom_id"] == uid]
    rows.sort(key=lambda e: e["_seq"])
    page, total = paginate(rows, limit, offset)
    return ok_array([public(e) for e in page], limit, offset, total, 200)


@bp.get("/enrollments/<rid>")
@require_roles("CenterDirector", "BillingAdmin", "Parent", "Teacher")
def get_enrollment(rid):
    ent = get_or_404(db.enrollments, rid, "enrollment")
    if g.user_role == "Parent":
        child = db.children.get(ent["child_id"])
        if child is None or child["family_id"] != current_user_id():
            raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this enrollment")
    elif g.user_role == "Teacher":
        if ent["classroom_id"] != current_user_id():
            raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Teacher does not own this enrollment")
    return ok_object(public(ent), 200)


def _parent_owns_enrollment(ent):
    child = db.children.get(ent["child_id"])
    if child is None or child["family_id"] != current_user_id():
        raise APIError(ERR_NOT_RESOURCE_OWNER, 403, "Parent does not own this child")


@bp.post("/enrollments/<rid>/accept")
@require_roles("Parent")
def accept_enrollment(rid):
    ent = get_or_404(db.enrollments, rid, "enrollment")
    _parent_owns_enrollment(ent)
    if ent["status"] != "OFFERED":
        raise APIError(ERR_INVALID_STATE, 409, "Enrollment is not OFFERED")
    ent["status"] = "ACCEPTED"
    touch(ent)
    return ok_object(public(ent), 200)


@bp.post("/enrollments/<rid>/decline")
@require_roles("Parent")
def decline_enrollment(rid):
    ent = get_or_404(db.enrollments, rid, "enrollment")
    _parent_owns_enrollment(ent)
    if ent["status"] != "OFFERED":
        raise APIError(ERR_INVALID_STATE, 409, "Enrollment is not OFFERED")
    ent["status"] = "DECLINED"
    touch(ent)
    return ok_object(public(ent), 200)


@bp.post("/enrollments/<rid>/activate")
@require_roles("CenterDirector")
def activate_enrollment(rid):
    ent = get_or_404(db.enrollments, rid, "enrollment")
    if ent["status"] != "ACCEPTED":
        raise APIError(ERR_INVALID_STATE, 409, "Enrollment is not ACCEPTED")
    classroom = db.classrooms.get(ent["classroom_id"])
    # capacity gate (priority 13)
    if classroom["active_enrollment_count"] >= classroom["licensed_capacity"]:
        raise APIError(ERR_CLASSROOM_FULL, 409, "Classroom is full")
    child = db.children.get(ent["child_id"])
    # age-band gate (priority 9)
    if not age_band_fits(child["birthdate"], classroom["age_band"]):
        raise APIError(ERR_AGE_BAND_MISMATCH, 422, "Child does not fit classroom age band")

    family = db.families.get(child["family_id"])
    # snapshot pricing
    ent["locked_base_tuition_cents"] = classroom["base_monthly_tuition_cents"]
    family["sliding_scale_tier"] = compute_sliding_scale_tier(family)
    ent["locked_parent_share_pct"] = parent_share_for_tier(
        family["center_id"], family["sliding_scale_tier"])
    ent["status"] = "ACTIVE"
    # initial net (cascade will finalize sibling_discount_pct)
    ent["monthly_net_tuition_cents"] = compute_monthly_net_tuition(
        ent["locked_base_tuition_cents"], ent["locked_parent_share_pct"], 0)
    touch(ent)

    # sibling cascade across family's ACTIVE siblings
    recompute_sibling_cascade(family["id"])

    # capacity bump + status
    classroom["active_enrollment_count"] += 1
    recompute_classroom_status(classroom)
    touch(classroom)

    return ok_object(public(ent), 200)


def _terminate(ent, new_status):
    classroom = db.classrooms.get(ent["classroom_id"])
    child = db.children.get(ent["child_id"])
    family = db.families.get(child["family_id"])
    ent["status"] = new_status
    touch(ent)
    classroom["active_enrollment_count"] -= 1
    recompute_classroom_status(classroom)
    touch(classroom)
    recompute_sibling_cascade(family["id"])
    return ent


@bp.post("/enrollments/<rid>/withdraw")
@require_roles("CenterDirector")
def withdraw_enrollment(rid):
    ent = get_or_404(db.enrollments, rid, "enrollment")
    if ent["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Enrollment is not ACTIVE")
    _terminate(ent, "WITHDRAWN")
    return ok_object(public(ent), 200)


@bp.post("/enrollments/<rid>/graduate")
@require_roles("CenterDirector")
def graduate_enrollment(rid):
    ent = get_or_404(db.enrollments, rid, "enrollment")
    if ent["status"] != "ACTIVE":
        raise APIError(ERR_INVALID_STATE, 409, "Enrollment is not ACTIVE")
    _terminate(ent, "GRADUATED")
    return ok_object(public(ent), 200)
