"""The logical clock control endpoint (PRD 2.4).

Setting the clock mutates nothing else: it never auto-closes a ballot and never
auto-closes a review. The one side effect it does have is promoting SCHEDULED
public reviews whose start date has been reached.
"""

from flask import Blueprint

from core import auth, envelope
from core.store import db, rows, touch
from core.util import date_part, iso
from core.validation import Body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.authenticate((auth.STANDARDS_STAFF,))
    body = Body(("to_iso8601",))
    target = body.instant("to_iso8601", required=True)

    db.clock = target

    promoted = []
    today = date_part(target)
    for review in rows("public_reviews"):
        if review["status"] == "SCHEDULED" and review["_start_date"] <= today:
            review["status"] = "OPEN"
            touch(review)
            promoted.append(review["id"])

    return envelope.object_response({
        "current_utc": iso(target),
        "promoted_public_review_ids": promoted,
    })
