"""Reviewer invitation, response, review submission and withdrawal."""

from flask import Blueprint

import calc
import serializers as ser
import services as svc
import validate as v
from auth import authorise, require_editor_journal
from db import (
    add_days,
    fmt_ts,
    now,
    now_iso,
    ordered,
    parse_ts,
    stamp_new,
    store,
    touch,
)
from errors import ApiError
from response import list_response, object_response

bp = Blueprint("invitations", __name__)

RESPONSES = ("ACCEPT", "DECLINE")
RECOMMENDATIONS = ("ACCEPT", "MINOR_REVISION", "MAJOR_REVISION", "REJECT")
EDITORIAL_ROLES = ("SystemAdmin", "EditorInChief", "HandlingEditor")


def find_invitation(iid):
    invitation = store.invitations.get(iid)
    if invitation is None:
        raise ApiError("ERR_REVIEW_INVITATION_NOT_FOUND")
    return invitation


@bp.post("/review-invitations")
def create_invitation():
    actor = authorise("HandlingEditor")
    data = v.body()

    manuscript_id = v.req_id(data, "manuscript_id")
    manuscript = store.manuscripts.get(manuscript_id)
    if manuscript is None:
        raise ApiError("ERR_MANUSCRIPT_NOT_FOUND")
    reviewer_id = v.opt_id(data, "reviewer_id")
    reviewer = None
    if reviewer_id is not None:
        reviewer = store.reviewers.get(reviewer_id)
        if reviewer is None:
            raise ApiError("ERR_REVIEWER_NOT_FOUND")
    require_editor_journal(actor, manuscript)

    journal = calc.journal_of(manuscript)
    raw_due_days = data.get("due_days")
    if raw_due_days is None:
        due_days = int(journal["review_target_days"])
    else:
        if not isinstance(raw_due_days, int) or isinstance(raw_due_days, bool):
            raise ApiError("ERR_INVALID_INTERVAL", "due_days must be a positive integer.")
        due_days = raw_due_days
    if due_days < 1:
        raise ApiError("ERR_INVALID_INTERVAL", "due_at must be strictly after invited_at.")

    svc.guard_manuscript_terminal(manuscript)
    assignment = svc.require_active_assignment(manuscript, actor)
    handling_editor = store.editors.get(assignment["editor_id"])

    invited_at = now()
    due_at = add_days(invited_at, due_days)
    window_limit = int(journal["reviewer_concurrent_window_limit"])

    if reviewer is not None:
        if reviewer["status"] == "RETIRED" or calc.reviewer_conflict(
            reviewer, manuscript, handling_editor
        ):
            raise ApiError("ERR_REVIEWER_CONFLICT")
        if calc.overlapping_open_windows(reviewer["id"], invited_at, due_at) >= window_limit:
            raise ApiError("ERR_REVIEWER_WINDOW_CAPACITY")
        selected_by = "EXPLICIT"
    else:
        reviewer = calc.select_reviewer(
            manuscript, handling_editor, invited_at, due_at, window_limit
        )
        if reviewer is None:
            raise ApiError("ERR_NO_ELIGIBLE_REVIEWER")
        selected_by = "SELECTOR"

    row = {
        "manuscript_id": manuscript_id,
        "reviewer_id": reviewer["id"],
        "round": manuscript["revision_round"],
        "state": "INVITED",
        "selected_by": selected_by,
        "invited_at": fmt_ts(invited_at),
        "due_at": fmt_ts(due_at),
        "responded_at": None,
        "decline_reason": None,
        "reminder_count": 0,
        "last_reminder_at": None,
        "closed_reason": None,
    }
    stamp_new(row)
    store.invitations[row["id"]] = row

    reviewer["invited_count"] = int(reviewer["invited_count"]) + 1
    reviewer["open_invitation_count"] = int(reviewer["open_invitation_count"]) + 1
    svc.recompute_reliability(reviewer)
    return object_response(ser.invitation_out(row), 201)


@bp.post("/review-invitations/<iid>/response")
def invitation_response(iid):
    actor = authorise("Reviewer")
    invitation = find_invitation(iid)
    data = v.body()
    answer = v.req_enum(data, "response", RESPONSES)
    decline_reason = v.opt_string(data, "decline_reason")

    if invitation["reviewer_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    svc.guard_invitation_terminal(invitation)
    if invitation["state"] != "INVITED":
        raise ApiError("ERR_INVALID_INVITATION_STATE")

    reviewer = store.reviewers.get(invitation["reviewer_id"])
    manuscript = store.manuscripts.get(invitation["manuscript_id"])

    if answer == "ACCEPT":
        due_at = parse_ts(invitation["due_at"])
        if due_at is not None and now() >= due_at:
            raise ApiError("ERR_INVITATION_EXPIRED")
        invitation["state"] = "ACCEPTED"
        invitation["responded_at"] = now_iso()
        touch(invitation)
        if reviewer is not None:
            reviewer["accepted_count"] = int(reviewer["accepted_count"]) + 1
            svc.recompute_reliability(reviewer)
    else:
        invitation["state"] = "DECLINED"
        invitation["closed_reason"] = "REVIEWER_DECLINED"
        invitation["responded_at"] = now_iso()
        invitation["decline_reason"] = decline_reason
        touch(invitation)
        if reviewer is not None:
            reviewer["declined_count"] = int(reviewer["declined_count"]) + 1
            svc.release_open_load(reviewer)
            svc.recompute_reliability(reviewer)
        if manuscript is not None:
            svc.recompute_shortfall(manuscript)
    return object_response(ser.invitation_out(invitation), 200)


@bp.post("/review-invitations/<iid>/reviews")
def submit_review(iid):
    actor = authorise("Reviewer")
    invitation = find_invitation(iid)
    data = v.body()
    recommendation = v.req_enum(data, "recommendation", RECOMMENDATIONS)
    novelty = v.req_int(data, "novelty_score", minimum=1, maximum=5)
    rigor = v.req_int(data, "rigor_score", minimum=1, maximum=5)
    clarity = v.req_int(data, "clarity_score", minimum=1, maximum=5)
    comments = v.opt_string(data, "comments")

    if invitation["reviewer_id"] != actor.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # rule 13 carve-out B: any non-ACCEPTED state answers with rule 27
    if invitation["state"] != "ACCEPTED":
        raise ApiError("ERR_INVITATION_NOT_ACCEPTED")

    manuscript = store.manuscripts.get(invitation["manuscript_id"])
    if manuscript is None or manuscript["status"] not in ("UNDER_REVIEW", "DECISION_PENDING"):
        raise ApiError("ERR_INVALID_MANUSCRIPT_STATE")

    submitted_at = now()
    due_at = parse_ts(invitation["due_at"])
    days_late = calc.days_late_for(submitted_at, due_at) if due_at is not None else 0
    row = {
        "invitation_id": invitation["id"],
        "recommendation": recommendation,
        "novelty_score": novelty,
        "rigor_score": rigor,
        "clarity_score": clarity,
        "comments": comments,
        "submitted_at": now_iso(),
        "days_late": days_late,
        "reliability_weight": None,
    }
    stamp_new(row, versioned=False)
    store.reviews[row["id"]] = row

    invitation["state"] = "SUBMITTED"
    invitation["closed_reason"] = "REVIEW_SUBMITTED"
    touch(invitation)

    reviewer = store.reviewers.get(invitation["reviewer_id"])
    if reviewer is not None:
        reviewer["submitted_count"] = int(reviewer["submitted_count"]) + 1
        reviewer["late_days_total"] = int(reviewer["late_days_total"]) + days_late
        svc.release_open_load(reviewer)
        # contractual order: recompute the scores, then freeze the weight
        svc.recompute_reliability(reviewer)
        row["reliability_weight"] = calc.reliability_weight(reviewer["reliability_score_rolling"])
    else:
        row["reliability_weight"] = calc.reliability_weight(calc.NEUTRAL_SEED)

    journal = calc.journal_of(manuscript)
    if manuscript["status"] == "UNDER_REVIEW" and calc.submitted_review_count(manuscript) >= int(
        journal["min_completed_reviews_for_decision"]
    ):
        manuscript["status"] = "DECISION_PENDING"
    touch(manuscript)
    return object_response(ser.review_out(row), 201)


@bp.post("/review-invitations/<iid>/withdraw")
def withdraw_invitation(iid):
    actor = authorise("HandlingEditor")
    invitation = find_invitation(iid)
    manuscript = store.manuscripts.get(invitation["manuscript_id"])
    data = v.body()
    v.opt_string(data, "reason")

    require_editor_journal(actor, manuscript)
    svc.guard_invitation_terminal(invitation)
    if invitation["state"] not in ("INVITED", "ACCEPTED"):
        raise ApiError("ERR_INVALID_INVITATION_STATE")
    if manuscript is not None:
        svc.guard_manuscript_terminal(manuscript)
        svc.require_active_assignment(manuscript, actor)

    svc.close_invitation(invitation, "WITHDRAWN", "EDITOR_WITHDRAWN")
    reviewer = store.reviewers.get(invitation["reviewer_id"])
    if reviewer is not None:
        svc.release_open_load(reviewer)
        svc.recompute_reliability(reviewer)
    return object_response(ser.invitation_out(invitation), 200)


# ==========================================================================
# reads
# ==========================================================================
@bp.get("/review-invitations/<iid>")
def get_invitation(iid):
    authorise("SystemAdmin", "EditorInChief", "HandlingEditor", "Reviewer")
    return object_response(ser.invitation_out(find_invitation(iid)), 200)


@bp.get("/review-invitations")
def list_invitations():
    authorise("SystemAdmin", "EditorInChief", "HandlingEditor", "Reviewer")
    limit, offset = v.pagination()
    manuscript_id = v.query_str("manuscript_id")
    reviewer_id = v.query_str("reviewer_id")
    round_no = v.query_int("round")
    state = v.query_str("state")
    rows = []
    for row in store.invitations.values():
        if manuscript_id is not None and row["manuscript_id"] != manuscript_id:
            continue
        if reviewer_id is not None and row["reviewer_id"] != reviewer_id:
            continue
        if round_no is not None and row["round"] != round_no:
            continue
        if state is not None and row["state"] != state:
            continue
        rows.append(row)
    rows = ordered(rows)
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.invitation_out), limit, offset, len(rows))


@bp.get("/review-invitations/<iid>/reviews")
def list_invitation_reviews(iid):
    authorise("SystemAdmin", "EditorInChief", "HandlingEditor", "Reviewer")
    find_invitation(iid)
    limit, offset = v.pagination()
    rows = ordered([r for r in store.reviews.values() if r["invitation_id"] == iid])
    page = v.window(rows, limit, offset)
    return list_response(ser.many(page, ser.review_out), limit, offset, len(rows))
