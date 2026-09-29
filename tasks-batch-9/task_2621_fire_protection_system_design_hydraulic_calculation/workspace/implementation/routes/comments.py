"""Plan review comments: answering and disposal (PRD 3.8)."""
from flask import Blueprint

import cascades
import db
import guards
import helpers
import ledger
import response
import validate
from middleware import ALL_ROLES, authenticate

bp = Blueprint("comments", __name__)

COMMENT_TERMINAL = ("RESOLVED", "WITHDRAWN")
DISPOSITIONS = ["RESOLVED", "REJECT_RESPONSE", "WITHDRAWN"]


def _submittal_of(comment):
    return db.submittals[comment["submittal_id"]]


@bp.get("/review-comments/<comment_id>")
def get_comment(comment_id):
    authenticate(ALL_ROLES)
    return response.ok(response.public(guards.must("comment", comment_id)))


@bp.get("/review-comments")
def list_comments():
    authenticate(ALL_ROLES)
    rows = helpers.apply_filters(
        list(db.review_comments.values()),
        ["submittal_id", "raised_by_ahj_reviewer_id", "assigned_engineer_id", "severity", "state"],
    )
    return helpers.list_response(rows)


@bp.post("/review-comments/<comment_id>/respond")
def respond(comment_id):
    actor = authenticate(["DesignEngineer"])
    comment = guards.must("comment", comment_id)
    submittal = _submittal_of(comment)
    project = guards.project_of(submittal)
    guards.require_lead_engineer(actor, project)
    data = validate.body()
    note = validate.req_str(data, "response_note")

    if comment["state"] in COMMENT_TERMINAL:
        guards.terminal("This comment is in a terminal state and accepts no response.")
    guards.require_project_open(project)
    if comment["state"] != "OPEN":
        guards.invalid_transition("Only an OPEN comment can be answered.")
    if submittal["state"] != "COMMENTS_ISSUED":
        guards.invalid_transition(
            "A comment is answered only while its package is COMMENTS_ISSUED."
        )

    before_submittal = db.snapshot(submittal)
    comment["response_note"] = note
    comment["state"] = "RESPONDED"
    db.touch(comment)

    if not any(c["state"] == "OPEN" for c in ledger.comments_of(submittal["id"])):
        submittal["state"] = "RESPONSE_COMPLETE"
    ledger.recount_submittal_comments(submittal)
    db.touch_if_changed(submittal, before_submittal)
    return response.ok(response.public(comment))


@bp.post("/review-comments/<comment_id>/close")
def close_comment(comment_id):
    actor = authenticate(["AhjReviewer"])
    comment = guards.must("comment", comment_id)
    submittal = _submittal_of(comment)
    project = guards.project_of(submittal)
    guards.require_assigned_reviewer(actor, project)
    data = validate.body()
    disposition = validate.req_str(data, "disposition", enum=DISPOSITIONS)
    close_note = validate.opt_str(data, "close_note")

    if comment["state"] in COMMENT_TERMINAL:
        guards.terminal("This comment is in a terminal state and cannot be disposed of again.")
    guards.require_project_open(project)
    if disposition in ("RESOLVED", "REJECT_RESPONSE") and comment["state"] != "RESPONDED":
        guards.invalid_transition(
            "A comment is resolved or rejected only from RESPONDED."
        )
    if disposition == "WITHDRAWN" and comment["state"] != "OPEN":
        guards.invalid_transition("A comment is withdrawn only from OPEN.")

    before_submittal = db.snapshot(submittal)
    before_project = db.snapshot(project)
    comment["disposition"] = disposition
    comment["close_note"] = close_note
    if disposition == "RESOLVED":
        comment["state"] = "RESOLVED"
    elif disposition == "REJECT_RESPONSE":
        comment["state"] = "OPEN"
        comment["response_note"] = None
        if submittal["state"] == "RESPONSE_COMPLETE":
            submittal["state"] = "COMMENTS_ISSUED"
    else:
        comment["state"] = "WITHDRAWN"
    db.touch(comment)

    ledger.recount_submittal_comments(submittal)
    if disposition == "WITHDRAWN" and submittal["open_comment_count"] == 0:
        if submittal["state"] == "COMMENTS_ISSUED":
            submittal["state"] = "UNDER_REVIEW"
            cascades.compensate_major_comment(submittal, project)
    db.touch_if_changed(submittal, before_submittal)
    ledger.recount_project_major_comments(project)
    ledger.recompute_posture(project)
    db.touch_if_changed(project, before_project)
    return response.ok(response.public(comment))
