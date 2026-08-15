"""CertificationReview routes."""

from datetime import timedelta
from flask import Blueprint, request

import db
import errors
import services.core as svc
from middleware import require_roles
from response import success_object, success_list
from routes.watch_groups import _pagination

bp = Blueprint("certification_reviews", __name__)

APPROVAL_THRESHOLD = 60
CONDITIONAL_FLOOR = 40
FULL_THRESHOLD = 80

VALID_DECISIONS = {"APPROVED", "REJECTED", "CONDITIONAL"}


def _serialize_review(r):
    return {
        "id": r["id"],
        "watch_group_id": r["watch_group_id"],
        "reviewing_officer_id": r["reviewing_officer_id"],
        "review_status": r["review_status"],
        "certification_points": r["certification_points"],
        "certification_grant_months": r["certification_grant_months"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def _get_latest_bias_trainer(group_id):
    """Get the trainer_officer_id of the group's most recent COMPLETED BIAS_AVOIDANCE session."""
    latest = None
    latest_time = None
    for ts in db.training_sessions.values():
        if (ts["watch_group_id"] == group_id
                and ts["session_status"] == "COMPLETED"
                and ts["curriculum"] == "BIAS_AVOIDANCE"):
            sched = ts["scheduled_at"]
            if latest_time is None or sched > latest_time:
                latest_time = sched
                latest = ts["trainer_officer_id"]
    return latest


@bp.route("/watch/certification-reviews", methods=["POST"])
def create_review():
    user_id, role = require_roles("ProgramCoordinator")
    body = request.get_json(force=True, silent=True) or {}

    watch_group_id = body.get("watch_group_id")
    reviewing_officer_id = body.get("reviewing_officer_id")

    if not watch_group_id or not reviewing_officer_id:
        raise errors.invalid_request("watch_group_id and reviewing_officer_id are required")

    # Existence
    g = db.watch_groups.get(watch_group_id)
    if not g:
        raise errors.not_found("WatchGroup not found")
    o = db.liaison_officers.get(reviewing_officer_id)
    if not o:
        raise errors.not_found("LiaisonOfficer not found")

    # Segregation of duties: reviewer != trainer of latest COMPLETED BIAS_AVOIDANCE session
    latest_trainer = _get_latest_bias_trainer(watch_group_id)
    if latest_trainer and latest_trainer == reviewing_officer_id:
        raise errors.segregation("Reviewing officer trained this group's latest BIAS_AVOIDANCE session")

    # Duplicate check: at most one PENDING or CONDITIONAL review per group
    for r in db.certification_reviews.values():
        if (r["watch_group_id"] == watch_group_id
                and r["review_status"] in ("PENDING", "CONDITIONAL")):
            raise errors.duplicate()

    # Compute certification points at creation
    points = svc.compute_certification_points(watch_group_id)

    record = {
        "watch_group_id": watch_group_id,
        "reviewing_officer_id": reviewing_officer_id,
        "review_status": "PENDING",
        "certification_points": points,
        "certification_grant_months": 0,
    }
    svc.stamp_new(record)
    db.certification_reviews[record["id"]] = record
    return success_object(_serialize_review(record), 201)


@bp.route("/watch/certification-reviews", methods=["GET"])
def list_reviews():
    user_id, role = require_roles("ProgramCoordinator", "LiaisonOfficer")

    items = list(db.certification_reviews.values())

    wg = request.args.get("watch_group_id")
    if wg:
        items = [r for r in items if r["watch_group_id"] == wg]
    ro = request.args.get("reviewing_officer_id")
    if ro:
        items = [r for r in items if r["reviewing_officer_id"] == ro]
    rs = request.args.get("review_status")
    if rs:
        items = [r for r in items if r["review_status"] == rs]

    items.sort(key=lambda r: r["created_at"])
    limit, offset = _pagination()
    total = len(items)
    items = items[offset:offset + limit]
    return success_list([_serialize_review(r) for r in items], limit, offset, total)


@bp.route("/watch/certification-reviews/<id>", methods=["GET"])
def get_review(id):
    user_id, role = require_roles("ProgramCoordinator", "LiaisonOfficer")
    r = db.certification_reviews.get(id)
    if not r:
        raise errors.not_found("CertificationReview not found")
    return success_object(_serialize_review(r))


@bp.route("/watch/certification-reviews/<id>/decide", methods=["POST"])
def decide_review(id):
    user_id, role = require_roles("LiaisonOfficer")
    r = db.certification_reviews.get(id)
    if not r:
        raise errors.not_found("CertificationReview not found")

    if r["review_status"] not in ("PENDING", "CONDITIONAL"):
        raise errors.invalid_state("Review is not in PENDING or CONDITIONAL state")

    body = request.get_json(force=True, silent=True) or {}
    decision = body.get("decision")
    if not decision or decision not in VALID_DECISIONS:
        raise errors.invalid_request("decision must be APPROVED, REJECTED, or CONDITIONAL")

    # Acting officer must be the reviewing officer
    if user_id != r["reviewing_officer_id"]:
        raise errors.unauthorized("Only the reviewing officer may decide")

    gid = r["watch_group_id"]
    g = db.watch_groups.get(gid)
    if not g:
        raise errors.not_found("WatchGroup not found")

    # Segregation of duties (re-checked at decision time)
    latest_trainer = _get_latest_bias_trainer(gid)
    if latest_trainer and latest_trainer == r["reviewing_officer_id"]:
        raise errors.segregation("Reviewing officer trained this group's latest BIAS_AVOIDANCE session")

    # Recompute points fresh
    points = svc.compute_certification_points(gid)
    r["certification_points"] = points

    from_status = r["review_status"]
    was_previously_certified = g["certification_status"] == "CERTIFIED"

    if decision == "APPROVED":
        if from_status == "PENDING":
            if points < APPROVAL_THRESHOLD:
                raise errors.invalid_state(
                    f"Certification points {points} below approval threshold {APPROVAL_THRESHOLD}"
                )
        elif from_status == "CONDITIONAL":
            if points < APPROVAL_THRESHOLD:
                raise errors.invalid_state(
                    f"Certification points {points} below approval threshold {APPROVAL_THRESHOLD}"
                )

        # Determine grant
        if points >= FULL_THRESHOLD:
            g["certification_status"] = "CERTIFIED"
            r["certification_grant_months"] = 24
        else:
            g["certification_status"] = "PROVISIONAL"
            r["certification_grant_months"] = 12

        # Set certification_valid_until = now + grant months
        now_dt = db.get_clock()
        months = r["certification_grant_months"]
        # Approximate month addition
        year = now_dt.year
        month = now_dt.month + months
        year += (month - 1) // 12
        month = ((month - 1) % 12) + 1
        # Clamp day to avoid overflow
        import calendar
        max_day = calendar.monthrange(year, month)[1]
        day = min(now_dt.day, max_day)
        valid_until = now_dt.replace(year=year, month=month, day=day)
        g["certification_valid_until"] = db.to_iso(valid_until)

        r["review_status"] = "APPROVED"
        svc.touch(g)
        svc.touch(r)
        svc.recompute_posture(gid)

    elif decision == "REJECTED":
        r["review_status"] = "REJECTED"
        r["certification_grant_months"] = 0

        if was_previously_certified:
            g["certification_status"] = "REVOKED"
        else:
            g["certification_status"] = "UNCERTIFIED"
        g["certification_valid_until"] = None
        svc.touch(g)
        svc.touch(r)
        svc.recompute_posture(gid)

    elif decision == "CONDITIONAL":
        if from_status == "PENDING":
            if not (CONDITIONAL_FLOOR <= points < APPROVAL_THRESHOLD):
                raise errors.invalid_state(
                    f"CONDITIONAL requires points in [{CONDITIONAL_FLOOR}, {APPROVAL_THRESHOLD})"
                )
            r["review_status"] = "CONDITIONAL"
            r["certification_grant_months"] = 0
            g["certification_status"] = "PROVISIONAL"
            svc.touch(g)
            svc.touch(r)
            svc.recompute_posture(gid)
        else:
            raise errors.invalid_state("CONDITIONAL decision only valid from PENDING")

    # Re-fetch review in case it was updated
    r = db.certification_reviews[id]
    return success_object(_serialize_review(r))
