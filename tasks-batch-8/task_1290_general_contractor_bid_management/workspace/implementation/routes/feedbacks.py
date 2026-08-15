from flask import Blueprint

import errors
from db import DB, touch, iso_now
from middleware import get_context, require_role, get_json_body, reject_unexpected
from response import success_object

bp = Blueprint("feedbacks", __name__)


def serialize_feedback(fb):
    return {
        "id": fb["id"],
        "bid_id": fb["bid_id"],
        "leveled_rank": fb["leveled_rank"],
        "leveled_amount_cents": fb["leveled_amount_cents"],
        "winning_leveled_amount_cents": fb["winning_leveled_amount_cents"],
        "notes": fb["notes"],
        "sent_at": fb["sent_at"],
        "status": fb["status"],
        "created_at": fb["created_at"],
        "updated_at": fb["updated_at"],
        "version": fb["version"],
    }


@bp.post("/bidder-feedbacks/<fb_id>/send")
def send_feedback(fb_id):
    _, role = get_context()
    require_role(role, {"LeadEstimator"})
    fb = DB.feedbacks.get(fb_id)
    if fb is None:
        raise errors.err_resource_not_found()
    body = get_json_body()
    reject_unexpected(body, {"notes"})
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise errors.err_invalid_request("notes must be a string")
    if fb["status"] != "DRAFT":
        raise errors.err_invalid_resource_state("Send requires DRAFT")
    if notes is not None:
        fb["notes"] = notes
    fb["status"] = "SENT"
    fb["sent_at"] = iso_now()
    touch(fb)
    return success_object(serialize_feedback(fb))
