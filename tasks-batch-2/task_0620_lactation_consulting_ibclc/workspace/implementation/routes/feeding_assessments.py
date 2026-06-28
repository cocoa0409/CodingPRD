"""Feeding assessments (PRD §3.7). Lightweight, immutable record (id + created_at
only)."""
from flask import Blueprint, request

import db
from errors import err, ERR_INVALID_REQUEST
from middleware import get_auth, require_roles
from response import object_response, array_response
from services.common import (
    init_lightweight, serialize, get_body,
    require_str, require_int, paginate,
)
from services.lookups import get_or_404, get_fk_or_404

bp = Blueprint("feeding_assessments", __name__)

READ_ROLES = {"PracticeAdmin", "BillingSpecialist", "Consultant", "FrontDesk"}


@bp.post("/feeding-assessments")
def create_feeding_assessment():
    # PRD §3.7 / §4: Consultant only.
    _, role = get_auth()
    require_roles(role, {"Consultant"})
    body = get_body()
    consult_id = require_str(body, "consult_id")
    # FK existence.
    get_fk_or_404(db.consults, consult_id)
    # Well-formedness: latch_score 0..10, pre > 0, post >= pre (PRD §3.7).
    latch_score = require_int(body, "latch_score")
    if latch_score < 0 or latch_score > 10:
        raise err(ERR_INVALID_REQUEST, "latch_score must be 0..10")
    pre = require_int(body, "pre_feed_weight_grams", min_value=1)
    post = require_int(body, "post_feed_weight_grams")
    if post < pre:
        raise err(ERR_INVALID_REQUEST,
                  "post_feed_weight_grams must be >= pre_feed_weight_grams")
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise err(ERR_INVALID_REQUEST, "notes must be a string")

    record = {
        "consult_id": consult_id,
        "latch_score": latch_score,
        "pre_feed_weight_grams": pre,
        "post_feed_weight_grams": post,
        "notes": notes,
    }
    init_lightweight(record)
    db.feeding_assessments[record["id"]] = record
    return object_response(serialize(record), 201)


@bp.get("/feeding-assessments/<rid>")
def get_feeding_assessment(rid):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    record = get_or_404(db.feeding_assessments, rid)
    return object_response(serialize(record), 200)


@bp.get("/feeding-assessments")
def list_feeding_assessments():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    consult_id = request.args.get("consult_id")
    records = [
        r for r in db.feeding_assessments.values()
        if consult_id is None or r["consult_id"] == consult_id
    ]
    items, limit, offset, total = paginate(records)
    return array_response(items, limit, offset, total, 200)
