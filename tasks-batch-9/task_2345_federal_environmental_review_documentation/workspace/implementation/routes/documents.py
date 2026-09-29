"""NEPA documents, the comment period and response to comments (PRD 3.8)."""

from flask import Blueprint

import db
import response
import validation as v
from errors import fail
from middleware import endpoint
from routes.helpers import body_ref, list_response, of_action, office_of, path_row
from services import calc, record, rollups

bp = Blueprint("documents", __name__)

DOCUMENT_TYPES = ("CE_MEMORANDUM", "ENVIRONMENTAL_ASSESSMENT", "ENVIRONMENTAL_IMPACT_STATEMENT")

TYPE_FOR_CLASSIFICATION = {
    "CE_MEMORANDUM": "CATEGORICAL_EXCLUSION",
    "ENVIRONMENTAL_ASSESSMENT": "ENVIRONMENTAL_ASSESSMENT",
    "ENVIRONMENTAL_IMPACT_STATEMENT": "ENVIRONMENTAL_IMPACT_STATEMENT",
}

DOCUMENT_SPEC = {
    "document_type": {"required": True, "check": v.c_enum(DOCUMENT_TYPES)},
    "title": {"required": True, "check": v.c_str(1)},
}

COMMENT_SPEC = {
    "document_id": {"required": True, "check": v.c_str(1)},
    "assigned_issue_id": {"check": v.c_str(1), "default": None},
    "commenter_name": {"required": True, "check": v.c_str(1)},
    "resource_area": {"required": True, "check": v.c_enum(v.RESOURCE_AREAS)},
    "is_substantive": {"check": v.c_bool, "default": False},
    "body": {"required": True, "check": v.c_str(1)},
}

RESPONSE_CATEGORIES = (
    "FACTUAL_CORRECTION",
    "ANALYSIS_REVISED",
    "NO_CHANGE_NEEDED",
    "OUT_OF_SCOPE",
)

DOCUMENT_READ_ROLES = [
    "NepaCoordinator",
    "ReviewingOfficial",
    "DecidingOfficial",
    "ResourceSpecialist",
]
COMMENT_READ_ROLES = ["NepaCoordinator", "ReviewingOfficial", "PublicCommenter"]


@endpoint(bp, "/proposed-actions/<action_id>/documents", ["POST"], ["NepaCoordinator"])
def create_document(action_id):
    body = v.parse_body(DOCUMENT_SPEC)
    action = path_row("actions", action_id, "proposed action")
    if TYPE_FOR_CLASSIFICATION[body["document_type"]] != action["classification"]:
        fail(
            "ERR_REFERENCE_MISMATCH",
            "document_type does not match the action's classification",
        )
    row = db.new_row(
        "documents",
        {
            "action_id": action["id"],
            "document_type": body["document_type"],
            "title": body["title"],
            "publication_status": "DRAFT",
            "comment_status": "NOT_OPEN",
            "comment_period_start_at": None,
            "comment_period_end_at": None,
            "comment_period_days": 0,
            "substantive_comment_count": 0,
            "responded_substantive_count": 0,
            "unresolved_substantive_count": 0,
            "response_completeness_pct": 100.0,
        },
    )
    return response.created(db.public(row))


@endpoint(bp, "/proposed-actions/<action_id>/documents", ["GET"], DOCUMENT_READ_ROLES)
def list_documents(action_id):
    path_row("actions", action_id, "proposed action")
    return list_response(
        of_action("documents", action_id), "document_type", "publication_status", "comment_status"
    )


@endpoint(bp, "/documents/<document_id>", ["GET"], DOCUMENT_READ_ROLES + ["PublicCommenter"])
def get_document(document_id):
    document = path_row("documents", document_id, "document")
    return response.ok(db.public(document))


@endpoint(bp, "/documents/<document_id>/publish", ["POST"], ["NepaCoordinator"])
def publish_document(document_id):
    body = v.parse_body(
        {"comment_period_end_at": {"required": True, "check": v.c_datetime}}
    )
    document = path_row("documents", document_id, "document")
    action = db.find("actions", document["action_id"])
    office = office_of(action)

    if document["publication_status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "only a DRAFT document may be published")
    if action["review_stage"] != "ANALYSIS":
        fail("ERR_INVALID_STATE", "the action's review_stage must be ANALYSIS")

    if action["unaddressed_issue_count"] != 0:
        fail(
            "ERR_UNADDRESSED_ISSUES",
            "every significant scoping issue must have a finalized analysis behind it",
        )

    required = calc.required_consultation_types(action)
    if required:
        satisfied = set()
        for consultation in of_action("consultations", action["id"]):
            if consultation["status"] in ("CONCURRED", "CONDITIONAL_CONCURRENCE"):
                satisfied.add(consultation["consultation_type"])
        missing = sorted(required - satisfied)
        if missing:
            fail(
                "ERR_REQUIRED_CONSULTATION_INCOMPLETE",
                "required consultation track(s) not concluded: %s" % ", ".join(missing),
            )

    if TYPE_FOR_CLASSIFICATION[document["document_type"]] != action["classification"]:
        fail(
            "ERR_REFERENCE_MISMATCH",
            "document_type no longer matches the action's classification",
        )

    document_type = document["document_type"]
    if document_type != "CE_MEMORANDUM":
        if document_type == "ENVIRONMENTAL_ASSESSMENT":
            minimum_alternatives = office["min_screened_in_alternatives_ea"]
            minimum_days = office["min_ea_comment_days"]
        else:
            minimum_alternatives = office["min_screened_in_alternatives_eis"]
            minimum_days = office["min_eis_comment_days"]
        if action["alternatives_screened_in_count"] < minimum_alternatives:
            fail(
                "ERR_INSUFFICIENT_ALTERNATIVES",
                "at least %d screened-in alternative(s) are required" % minimum_alternatives,
            )
        if db.floor_days(db.logical_now(), db.parse_dt(body["comment_period_end_at"])) < minimum_days:
            fail(
                "ERR_COMMENT_PERIOD_TOO_SHORT",
                "the comment period must run at least %d whole days" % minimum_days,
            )

    now = db.logical_now()
    document["publication_status"] = "PUBLISHED"
    document["comment_status"] = "OPEN"
    document["comment_period_start_at"] = db.iso(now)
    document["comment_period_end_at"] = body["comment_period_end_at"]
    document["comment_period_days"] = db.floor_days(
        now, db.parse_dt(body["comment_period_end_at"])
    )
    db.touch(document)

    if action["review_stage"] == "ANALYSIS":
        action["review_stage"] = "DRAFT_PUBLISHED"
        db.touch(action)
    record.add_entry(
        action,
        "DOCUMENT_PUBLISHED",
        "NepaDocument",
        document["id"],
        "Document published and comment period opened",
    )
    return response.ok(db.public(document))


@endpoint(bp, "/documents/<document_id>/close-comment-period", ["POST"], ["NepaCoordinator"])
def close_comment_period(document_id):
    v.no_body()
    document = path_row("documents", document_id, "document")
    action = db.find("actions", document["action_id"])

    if document["comment_status"] != "OPEN":
        fail("ERR_INVALID_STATE", "the comment period is not OPEN")
    end = db.parse_dt(document["comment_period_end_at"])
    if db.logical_now() < end:
        fail("ERR_COMMENT_PERIOD_NOT_ENDED", "the comment period has not reached its end")

    document["comment_status"] = "CLOSED"
    db.touch(document)

    if action["review_stage"] == "DRAFT_PUBLISHED":
        action["review_stage"] = "COMMENT_CLOSED"
        db.touch(action)
    record.add_entry(
        action,
        "COMMENT_PERIOD_CLOSED",
        "NepaDocument",
        document["id"],
        "Comment period closed",
    )
    return response.ok(db.public(document))


@endpoint(bp, "/documents/<document_id>/finalize", ["POST"], ["NepaCoordinator"])
def finalize_document(document_id):
    v.no_body()
    document = path_row("documents", document_id, "document")
    action = db.find("actions", document["action_id"])

    if document["publication_status"] != "PUBLISHED":
        fail("ERR_INVALID_STATE", "only a PUBLISHED document may be finalized")
    if document["comment_status"] != "CLOSED":
        fail("ERR_INVALID_STATE", "the comment period must be CLOSED")
    if document["unresolved_substantive_count"] != 0:
        fail("ERR_UNRESOLVED_COMMENTS", "every substantive comment must be answered")

    document["publication_status"] = "FINAL"
    db.touch(document)
    record.add_entry(
        action,
        "DOCUMENT_FINALIZED",
        "NepaDocument",
        document["id"],
        "Document finalized",
    )
    return response.ok(db.public(document))


# ---------------------------------------------------------------- comments


@endpoint(bp, "/comments", ["POST"], ["PublicCommenter"])
def create_comment():
    body = v.parse_body(COMMENT_SPEC)
    document = body_ref("documents", body["document_id"], "document_id")
    issue = None
    if body["assigned_issue_id"] is not None:
        issue = body_ref("issues", body["assigned_issue_id"], "assigned_issue_id")

    if document["comment_status"] != "OPEN":
        fail("ERR_COMMENT_PERIOD_NOT_OPEN", "the document's comment period is not OPEN")
    if issue is not None and issue["action_id"] != document["action_id"]:
        fail(
            "ERR_REFERENCE_MISMATCH",
            "the assigned issue belongs to a different action than the document",
        )

    row = db.new_row(
        "comments",
        {
            "document_id": document["id"],
            "assigned_issue_id": body["assigned_issue_id"],
            "commenter_name": body["commenter_name"],
            "resource_area": body["resource_area"],
            "is_substantive": body["is_substantive"],
            "body": body["body"],
            "response_text": None,
            "response_category": None,
            "disposition": "RECEIVED",
        },
    )
    rollups.refresh_document(document)
    return response.created(db.public(row))


@endpoint(bp, "/comments/<comment_id>", ["GET"], COMMENT_READ_ROLES)
def get_comment(comment_id):
    comment = path_row("comments", comment_id, "comment")
    return response.ok(db.public(comment))


@endpoint(bp, "/comments", ["GET"], COMMENT_READ_ROLES)
def list_comments():
    return list_response(db.rows("comments"), "document_id", "assigned_issue_id", "disposition")


@endpoint(bp, "/comments/<comment_id>/respond", ["POST"], ["NepaCoordinator"])
def respond_comment(comment_id):
    body = v.parse_body(
        {
            "response_text": {"required": True, "check": v.c_str(1)},
            "response_category": {"required": True, "check": v.c_enum(RESPONSE_CATEGORIES)},
        }
    )
    comment = path_row("comments", comment_id, "comment")
    document = db.find("documents", comment["document_id"])

    if comment["disposition"] != "RECEIVED":
        fail("ERR_INVALID_STATE", "only a RECEIVED comment may be answered")
    if document["comment_status"] != "CLOSED":
        fail("ERR_INVALID_STATE", "responses are prepared after the comment period closes")

    comment["response_text"] = body["response_text"]
    comment["response_category"] = body["response_category"]
    comment["disposition"] = (
        "DUPLICATE" if body["response_category"] == "OUT_OF_SCOPE" else "RESPONDED"
    )
    db.touch(comment)
    rollups.refresh_document(document)
    return response.ok(db.public(comment))
