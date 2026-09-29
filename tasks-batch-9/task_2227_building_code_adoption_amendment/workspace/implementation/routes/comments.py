"""Public comments (PRD 3.4)."""
from flask import Blueprint

import clock
import config
import db
import middleware
import response
import validate
from errors import ApiError
from routes.common import apply_filters, as_str, paged
from services import derive, lookup, serialize

bp = Blueprint("comments", __name__)


@bp.post("/amendment-proposals/<proposal_id>/comments")
def create_comment(proposal_id):
    user_id, _ = middleware.require((config.ROLE_COUNCIL_ADMIN, config.ROLE_TECHNICAL_STAFF,
                                     config.ROLE_JURISDICTION_OFFICIAL, config.ROLE_PETITIONER))
    body = validate.body()
    commenter_sector = validate.req_enum(body, "commenter_sector", config.SECTORS)
    position = validate.req_enum(body, "position", config.COMMENT_POSITIONS)
    text = validate.req_string(body, "body")
    proposal = lookup.proposal(proposal_id)

    now = clock.now()
    if (proposal["comment_window_status"] != "OPEN"
            or proposal["comment_opens_at"] is None
            or proposal["comment_closes_at"] is None
            or now < proposal["comment_opens_at"]
            or now >= proposal["comment_closes_at"]):
        raise ApiError("ERR_COMMENT_WINDOW_CLOSED")

    record = db.new_record({
        "proposal_id": proposal["id"],
        "commenter_sector": commenter_sector,
        "position": position,
        "body": text,
        "submitted_by_user_id": user_id,
        "comment_round": proposal["comment_round"],
        "received_at": now,
    }, versioned=False)
    db.public_comments[record["id"]] = record
    return response.object_response(serialize.public_comment(record), 201)


@bp.get("/amendment-proposals/<proposal_id>/comments")
def list_proposal_comments(proposal_id):
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    proposal = lookup.proposal(proposal_id)
    rows = derive.comments_of_proposal(proposal["id"])
    return paged(rows, serialize.public_comment, limit, offset)


@bp.get("/public-comments")
def list_comments():
    middleware.require(config.ALL_ROLES)
    limit, offset = validate.pagination()
    rows = apply_filters(list(db.public_comments.values()), {
        "proposal_id": ("proposal_id", as_str),
        "position": ("position", as_str),
        "commenter_sector": ("commenter_sector", as_str),
    })
    return paged(rows, serialize.public_comment, limit, offset)


@bp.get("/public-comments/<comment_id>")
def get_comment(comment_id):
    middleware.require(config.ALL_ROLES)
    record = lookup.comment(comment_id)
    return response.object_response(serialize.public_comment(record))
