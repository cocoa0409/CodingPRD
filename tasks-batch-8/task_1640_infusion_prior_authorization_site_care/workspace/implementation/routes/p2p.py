"""Peer-to-peer reviews: schedule, reschedule, complete with cascades (PRD 3.5)."""
from flask import Blueprint

from db import db, next_seq, touch
from errors import (
    raise_error,
    ERR_INVALID_STATE,
    ERR_REVIEWER_SLOT_CONFLICT,
    ERR_P2P_RESCHEDULE_LIMIT,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_appeal, get_p2p, list_response
from serializers import serialize
from services.transitions import cascade_appeal_closed
from util import new_id, CLOCK
from validate import get_body, req_str, req_dt, req_enum, check_window_order

bp = Blueprint("p2p", __name__)

DECIDED_APPEAL_LEVELS = {"LEVEL_1_DECIDED", "LEVEL_2_DECIDED"}
MAX_RESCHEDULES = 2


def _reviewer_conflict(reviewer_user_id, new_start, new_end, exclude_id=None):
    """Closed-interval overlap against the reviewer's non-COMPLETED reviews;
    windows that merely touch at an endpoint still conflict."""
    for other in db["peer_to_peer_reviews"].values():
        if other["reviewer_user_id"] != reviewer_user_id:
            continue
        if other["status"] == "COMPLETED":
            continue
        if exclude_id is not None and other["id"] == exclude_id:
            continue
        if new_start <= other["scheduled_end"] and other["scheduled_start"] <= new_end:
            return other
    return None


@bp.post("/infusion/appeals/<aid>/peer-to-peer-reviews")
def create_p2p(aid):
    authorized(["MedicalDirector"])
    body = get_body()
    reviewer_user_id = req_str(body, "reviewer_user_id")
    scheduled_start = req_dt(body, "scheduled_start")
    scheduled_end = req_dt(body, "scheduled_end")
    check_window_order(scheduled_start, scheduled_end)

    appeal = get_appeal(aid)
    if appeal["status"] not in DECIDED_APPEAL_LEVELS:
        raise_error(ERR_INVALID_STATE,
                    "peer-to-peer calls are scheduled on a decided appeal level "
                    f"(LEVEL_1_DECIDED or LEVEL_2_DECIDED), found {appeal['status']}")
    if _reviewer_conflict(reviewer_user_id, scheduled_start, scheduled_end) is not None:
        raise_error(ERR_REVIEWER_SLOT_CONFLICT,
                    f"reviewer {reviewer_user_id} already has a review in that window")

    now = CLOCK.now()
    rec = {
        "id": new_id(),
        "appeal_id": appeal["id"],
        "reviewer_user_id": reviewer_user_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "reschedule_count": 0,
        "outcome": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["peer_to_peer_reviews"][rec["id"]] = rec
    return success_object(serialize(rec), 201)


@bp.get("/infusion/appeals/<aid>/peer-to-peer-reviews")
def list_p2p(aid):
    authorized(["MedicalDirector", "AuthCoordinator"])
    get_appeal(aid)
    items = [r for r in db["peer_to_peer_reviews"].values() if r["appeal_id"] == aid]
    return list_response(items)


@bp.post("/infusion/peer-to-peer-reviews/<rid>/reschedules")
def reschedule_p2p(rid):
    authorized(["MedicalDirector"])
    body = get_body()
    scheduled_start = req_dt(body, "scheduled_start")
    scheduled_end = req_dt(body, "scheduled_end")
    check_window_order(scheduled_start, scheduled_end)

    review = get_p2p(rid)
    if review["status"] not in ("SCHEDULED", "NO_SHOW"):
        raise_error(ERR_INVALID_STATE,
                    f"peer-to-peer review is {review['status']}; only SCHEDULED or NO_SHOW can be rescheduled")
    if review["reschedule_count"] >= MAX_RESCHEDULES:
        raise_error(ERR_P2P_RESCHEDULE_LIMIT,
                    "the third reschedule attempt is rejected")
    if _reviewer_conflict(review["reviewer_user_id"], scheduled_start, scheduled_end,
                          exclude_id=review["id"]) is not None:
        raise_error(ERR_REVIEWER_SLOT_CONFLICT,
                    f"reviewer {review['reviewer_user_id']} already has a review in that window")

    review["scheduled_start"] = scheduled_start
    review["scheduled_end"] = scheduled_end
    review["reschedule_count"] += 1
    review["status"] = "SCHEDULED"
    touch(review, CLOCK.now())
    return success_object(serialize(review))


@bp.post("/infusion/peer-to-peer-reviews/<rid>/completions")
def complete_p2p(rid):
    authorized(["MedicalDirector"])
    body = get_body()
    outcome = req_enum(body, "outcome", ["UPHOLD", "OVERTURN"])

    review = get_p2p(rid)
    if review["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"peer-to-peer review is {review['status']}; only SCHEDULED can be completed")

    now = CLOCK.now()
    review["status"] = "COMPLETED"
    review["outcome"] = outcome
    touch(review, now)

    # Cascade: appeal resting at a decided level closes, then the appeal's own
    # cascade moves the authorization request.
    appeal = db["appeals"].get(review["appeal_id"])
    if appeal is not None and appeal["status"] in DECIDED_APPEAL_LEVELS:
        closed = "CLOSED_UPHELD" if outcome == "UPHOLD" else "CLOSED_OVERTURNED"
        appeal["status"] = closed
        touch(appeal, now)
        cascade_appeal_closed(appeal, closed, now)
    return success_object(serialize(review))
