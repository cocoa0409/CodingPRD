"""Immutable feedback reads (PRD §3.9)."""

from flask import Blueprint

import db
import validators as v
from middleware import get_feedback, roles
from response import ok, paged
from store import public

bp = Blueprint("feedback", __name__)


@bp.get("/feedback")
@roles("BureauAdmin", "BookingAgent", "Speaker", "Client")
def list_feedback():
    engagement_id = v.query_string("engagement_id")
    rows = []
    for row in db.feedbacks.values():
        if engagement_id is not None and row["engagement_id"] != engagement_id:
            continue
        rows.append(row)
    return paged(rows)


@bp.get("/feedback/<feedback_id>")
@roles("BureauAdmin", "BookingAgent", "Speaker", "Client")
def read_feedback(feedback_id):
    return ok(public(get_feedback(feedback_id)))
