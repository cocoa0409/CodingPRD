"""ReviewCycle endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_ENGAGEMENT_NOT_FOUND,
    ERR_CYCLE_NOT_FOUND,
    ERR_NOT_ENGAGEMENT_APPLICANT,
    ERR_ENGAGEMENT_NOT_ACTIVE,
    ERR_RECORD_ALREADY_SEALED,
    ERR_CYCLE_STILL_ACTIVE,
    ERR_CYCLE_NOT_IN_REVIEW,
    ERR_NO_COMMENTS_TO_ISSUE,
    ERR_UNRESOLVED_COMMENTS_REMAIN,
    ERR_VERIFICATION_INCOMPLETE,
)
from middleware import (
    require_roles, get_json_body, require_fields, reject_unknown_fields,
    require_string, require_bool, parse_pagination, paginate,
)
from response import success_object, success_list
from services.core import (
    record_for_engagement, complete_active_assignments,
    refresh_engagement_counts, require_assigned_reviewer,
)
from services.fees import compute_due_at

bp = Blueprint("cycles", __name__)

READ_ROLES = ("PlatformAdmin", "ReviewCoordinator", "Reviewer", "ChiefReviewer", "Applicant")


def get_cycle_or_404(cid):
    c = db.cycles.get(cid)
    if c is None:
        raise ApiError(ERR_CYCLE_NOT_FOUND, 404, "No review cycle with the given id")
    return c


@bp.post("/plan-review/cycles")
def create_cycle():
    uid, role = require_roles("ReviewCoordinator", "Applicant")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {"engagement_id", "documents_ref"})
    require_fields(body, ["engagement_id", "documents_ref"])
    engagement_id = require_string(body, "engagement_id")
    documents_ref = require_string(body, "documents_ref")

    engagement = db.engagements.get(engagement_id)
    if engagement is None:
        raise ApiError(ERR_ENGAGEMENT_NOT_FOUND, 404, "No engagement with the given id")

    # ownership: applicant caller must own the engagement
    if role == "Applicant" and uid != engagement["applicant_contact_id"]:
        raise ApiError(ERR_NOT_ENGAGEMENT_APPLICANT, 403,
                       "X-User-ID does not equal engagement.applicant_contact_id")

    # state: engagement must be REGISTERED / IN_PROGRESS / APPROVED
    if engagement["status"] not in ("REGISTERED", "IN_PROGRESS", "APPROVED"):
        raise ApiError(ERR_ENGAGEMENT_NOT_ACTIVE, 409,
                       "Engagement is not in a status that accepts new cycles")
    if engagement["status"] == "APPROVED":
        rec = record_for_engagement(engagement["id"])
        if rec is not None and rec["status"] != "DRAFT":
            raise ApiError(ERR_RECORD_ALREADY_SEALED, 409,
                           "Revision impossible once the record is SEALED or TRANSMITTED")

    # strict single-cycle-slot exclusion
    eng_cycles = [c for c in db.cycles.values() if c["engagement_id"] == engagement["id"]]
    for c in eng_cycles:
        if c["status"] in ("OPEN", "IN_REVIEW"):
            raise ApiError(ERR_CYCLE_STILL_ACTIVE, 409,
                           "An OPEN or IN_REVIEW cycle already exists on the engagement")

    now = db.clock_now()

    # supersede a COMMENTS_ISSUED prior cycle
    for c in eng_cycles:
        if c["status"] == "COMMENTS_ISSUED":
            complete_active_assignments(c)
            c["status"] = "SUPERSEDED"
            db.touch(c)

    # cycle numbering: 1-based, monotonic, never reused
    engagement["cycle_count"] += 1
    cycle_number = engagement["cycle_count"]

    due_at = compute_due_at(
        now,
        engagement["pinned_turnaround_days"],
        engagement["pinned_sla_mode"],
        engagement.get("requested_expedite", False),
    )

    entity = db.stamp_new({
        "engagement_id": engagement["id"],
        "cycle_number": cycle_number,
        "documents_ref": documents_ref,
        "received_at": now,
        "due_at": due_at,
        "completed_at": None,
        "is_on_time": None,
        "load_path_confirmed": False,
        "lateral_system_confirmed": False,
        "status": "OPEN",
    })
    db.cycles[entity["id"]] = entity

    # engagement cascade: REGISTERED -> IN_PROGRESS or APPROVED -> IN_PROGRESS
    engagement["status"] = "IN_PROGRESS"
    db.touch(engagement)
    refresh_engagement_counts(engagement)

    return success_object(db.serialize(entity), status=201)


@bp.get("/plan-review/cycles")
def list_cycles():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination()
    items = list(db.cycles.values())
    engagement_id = request.args.get("engagement_id")
    status = request.args.get("status")
    if engagement_id is not None:
        items = [c for c in items if c["engagement_id"] == engagement_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (c["created_at"], c["id"]))
    page, total = paginate(items, limit, offset)
    return success_list([db.serialize(c) for c in page], limit, offset, total)


@bp.get("/plan-review/cycles/<cid>")
def get_cycle(cid):
    require_roles(*READ_ROLES)
    c = get_cycle_or_404(cid)
    return success_object(db.serialize(c))


@bp.post("/plan-review/cycles/<cid>/issue-comments")
def issue_comments(cid):
    uid, _role = require_roles("Reviewer")
    get_json_body(required=False)
    cycle = get_cycle_or_404(cid)
    engagement = db.engagements[cycle["engagement_id"]]

    # ownership: caller must be the reviewer on this cycle's ACTIVE assignment
    require_assigned_reviewer(cycle, uid)

    # state
    if cycle["status"] != "IN_REVIEW":
        raise ApiError(ERR_CYCLE_NOT_IN_REVIEW, 409,
                       "Cycle is not IN_REVIEW")

    raised_here = any(
        c["raised_in_cycle_id"] == cycle["id"] for c in db.comments.values()
    )
    reopened_awaiting = any(
        c["engagement_id"] == engagement["id"] and c["status"] == "REOPENED"
        for c in db.comments.values()
    )
    if not (raised_here or reopened_awaiting):
        raise ApiError(ERR_NO_COMMENTS_TO_ISSUE, 409,
                       "No comments raised in this cycle and none REOPENED awaiting a response round")

    now = db.clock_now()
    cycle["completed_at"] = now
    cycle["is_on_time"] = now <= cycle["due_at"]
    cycle["status"] = "COMMENTS_ISSUED"
    db.touch(cycle)
    return success_object(db.serialize(cycle))


@bp.post("/plan-review/cycles/<cid>/approve")
def approve_cycle(cid):
    uid, _role = require_roles("Reviewer")
    body = get_json_body(required=True)
    reject_unknown_fields(body, {"load_path_confirmed", "lateral_system_confirmed"})
    require_fields(body, ["load_path_confirmed", "lateral_system_confirmed"])
    load_path_confirmed = require_bool(body, "load_path_confirmed")
    lateral_system_confirmed = require_bool(body, "lateral_system_confirmed")

    cycle = get_cycle_or_404(cid)
    engagement = db.engagements[cycle["engagement_id"]]

    # ownership
    require_assigned_reviewer(cycle, uid)

    # state
    if cycle["status"] != "IN_REVIEW":
        raise ApiError(ERR_CYCLE_NOT_IN_REVIEW, 409, "Cycle is not IN_REVIEW")

    # business gates
    refresh_engagement_counts(engagement)
    if engagement["unresolved_comment_count"] != 0:
        raise ApiError(ERR_UNRESOLVED_COMMENTS_REMAIN, 409,
                       "Unresolved comments remain on the engagement")
    if not (load_path_confirmed and lateral_system_confirmed):
        raise ApiError(ERR_VERIFICATION_INCOMPLETE, 422,
                       "load_path_confirmed and lateral_system_confirmed must both be true")

    now = db.clock_now()
    cycle["completed_at"] = now
    cycle["is_on_time"] = now <= cycle["due_at"]
    cycle["load_path_confirmed"] = True
    cycle["lateral_system_confirmed"] = True
    cycle["status"] = "APPROVED"
    db.touch(cycle)

    # cycle's ACTIVE assignments -> COMPLETED
    complete_active_assignments(cycle)

    # engagement cascade: IN_PROGRESS -> APPROVED; create or refresh DRAFT record
    engagement["status"] = "APPROVED"
    db.touch(engagement)
    refresh_engagement_counts(engagement)

    rec = record_for_engagement(engagement["id"])
    if rec is None:
        rec = db.stamp_new({
            "engagement_id": engagement["id"],
            "record_number": "RR-%s-%02d" % (
                engagement["pinned_state_code"], engagement["cycle_count"]
            ),
            "pinned_ibc_edition": engagement["pinned_ibc_edition"],
            "pinned_asce7_edition": engagement["pinned_asce7_edition"],
            "cycle_count_snapshot": engagement["cycle_count"],
            "sealed_by_reviewer_id": None,
            "sealed_at": None,
            "transmitted_at": None,
            "status": "DRAFT",
        })
        db.records[rec["id"]] = rec
    else:
        rec["pinned_ibc_edition"] = engagement["pinned_ibc_edition"]
        rec["pinned_asce7_edition"] = engagement["pinned_asce7_edition"]
        rec["cycle_count_snapshot"] = engagement["cycle_count"]
        db.touch(rec)

    return success_object(db.serialize(cycle))
