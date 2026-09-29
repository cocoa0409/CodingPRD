"""Plan-of-care reviews and their three disjoint completion outcomes."""
from flask import Blueprint

import serialize
from auth import authenticate, require_own_indirect, rep_scope
from constants import POC_OUTCOMES, POC_STATUSES
from db import db, sort_created, touch
from errors import api_error
from response import ok, ok_list
from routes.common import CS, DSM, PA, RD, RR, get_review
from services import derive
from shape import body_json, opt_str, paginate, q_enum, q_str, req_enum

bp = Blueprint("reviews", __name__)

REVIEW_READ_ROLES = [PA, CS, RD, DSM, RR]


@bp.get("/plan-of-care-reviews/<review_id>")
def read_review(review_id):
    ctx = authenticate(REVIEW_READ_ROLES)
    row = get_review(review_id)
    require_own_indirect(ctx, row)
    return ok(serialize.review(row))


@bp.get("/plan-of-care-reviews")
def list_reviews():
    ctx = authenticate(REVIEW_READ_ROLES)
    resident_id = q_str("resident_id")
    trigger_observation_id = q_str("trigger_observation_id")
    status = q_enum("status", POC_STATUSES)
    outcome = q_enum("outcome", POC_OUTCOMES)

    scope = rep_scope(ctx)
    if scope is not None and resident_id is not None and resident_id != scope:
        raise api_error(
            "ERR_FORBIDDEN_ROLE",
            "A ResidentRepresentative may only list its own resident's reviews",
        )

    rows = list(db.reviews.values())
    if scope is not None:
        rows = [r for r in rows if r["resident_id"] == scope]
    if resident_id is not None:
        rows = [r for r in rows if r["resident_id"] == resident_id]
    if trigger_observation_id is not None:
        rows = [r for r in rows if r["trigger_observation_id"] == trigger_observation_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.review, window), pagination)


@bp.post("/plan-of-care-reviews/<review_id>/complete")
def complete_review(review_id):
    ctx = authenticate([RD])
    body = body_json()
    outcome = req_enum(body, "outcome", POC_OUTCOMES)
    note = opt_str(body, "note")

    row = get_review(review_id)

    if row["status"] != "OPEN":
        raise api_error("ERR_INVALID_STATE", "Only an OPEN review may be completed")

    observation = db.observations.get(row["trigger_observation_id"])
    if observation is not None and observation["recorded_by_user_id"] == ctx["user_id"]:
        raise api_error(
            "ERR_SEGREGATION_OF_DUTIES",
            "The completing dietitian must differ from the triggering observation's recorder",
        )

    resident = db.residents.get(row["resident_id"])
    order = None
    if outcome == "DIET_ORDER_REREVIEW":
        order = derive.find_active_order(row["resident_id"])
        if order is None:
            raise api_error(
                "ERR_DIET_ORDER_NOT_VERIFIED",
                "DIET_ORDER_REREVIEW requires the resident to hold an ACTIVE diet order",
            )

    row["status"] = "COMPLETED"
    row["outcome"] = outcome
    row["note"] = note
    row["completed_by_user_id"] = ctx["user_id"]
    touch(row)

    if outcome == "DIET_ORDER_REREVIEW":
        if order["review_status"] != "REREVIEW_REQUIRED":
            order["review_status"] = "REREVIEW_REQUIRED"
            touch(order)
        if resident is not None and resident["tray_card_state"] != "HOLD_PENDING_REVIEW":
            resident["tray_card_state"] = "HOLD_PENDING_REVIEW"
            touch(resident)
    elif outcome == "ESCALATED":
        if resident is not None and resident["tray_card_state"] != "BLOCKED":
            resident["tray_card_state"] = "BLOCKED"
            touch(resident)

    return ok(serialize.review(row))
