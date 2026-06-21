"""Section 83(b) Election routes. PRD §3.9."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, request

import db
from common import (
    get_body, pagination_params, paginate_and_sort, require_datetime,
    require_string, stamp_common_fields, touch,
)
from errors import (
    APIError, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE,
)
from middleware import require_roles
from response import created, success, list_response
from services import core

bp = Blueprint("elections", __name__)

WINDOW_DAYS = 30


@bp.post("/section-83b-elections")
@require_roles("Stakeholder", "Administrator")
def file_election():
    body = get_body()
    cap_table_id = require_string(body, "cap_table_id")
    core.get_cap_table(cap_table_id)
    exercise_id = require_string(body, "exercise_id")
    ex = core.get_exercise(exercise_id)
    if ex["cap_table_id"] != cap_table_id:
        raise APIError(ERR_NOT_FOUND, "Exercise not found.", 404)
    filed_date = require_datetime(body, "filed_date")

    # Stakeholder may only file against its own exercises (PRD §2.1)
    if g.user_role == "Stakeholder":
        grant = core.get_option_grant(ex["option_grant_id"])
        if grant["shareholder_id"] != g.user_id:
            raise APIError(ERR_FORBIDDEN, "Stakeholder may only file against its own exercises.", 403)

    # anchor: the exercise's date (created_at = when the exercise was recorded)
    exercise_date = ex["created_at"]

    now = db.now_utc()
    el = {
        "cap_table_id": cap_table_id,
        "exercise_id": exercise_id,
        "filed_date": filed_date,
        "exercise_date": exercise_date,
        "status": "PENDING",
    }
    stamp_common_fields(el, now)
    db.section_83b_elections[el["id"]] = el
    return created(core.serialize(el))


@bp.get("/section-83b-elections/<cid>")
@require_roles("Administrator", "Auditor", "Stakeholder")
def get_election(cid):
    el = core.get_election(cid)
    return success(core.serialize(el))


@bp.get("/section-83b-elections")
@require_roles("Administrator", "Auditor", "Stakeholder")
def list_elections():
    limit, offset = pagination_params()
    items = list(db.section_83b_elections.values())
    for key in ("cap_table_id", "exercise_id"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i[key] == val]
    if g.user_role == "Stakeholder":
        own_ex = set()
        own_grants = {gr["id"] for gr in db.option_grants.values() if gr["shareholder_id"] == g.user_id}
        for x in db.exercises.values():
            if x["option_grant_id"] in own_grants:
                own_ex.add(x["id"])
        items = [i for i in items if i["exercise_id"] in own_ex]
    page, total = paginate_and_sort(items, limit, offset)
    return list_response(
        [core.serialize(i) for i in page],
        limit=limit, offset=offset, total_count=total,
    )


@bp.post("/section-83b-elections/<cid>/process")
@require_roles("Administrator")
def process_election(cid):
    el = core.get_election(cid)
    if el["status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, "Election must be PENDING to process.", 409)
    now = db.now_utc()
    deadline = el["exercise_date"] + timedelta(days=WINDOW_DAYS)
    if el["filed_date"] <= deadline:
        el["status"] = "ACCEPTED"
        touch(el, now)
        return success(core.serialize(el))
    else:
        # PRD §3.9 / scaffold endpoint (code 200): the fork's late branch is the
        # outcome -- process succeeds and records PENDING -> REJECTED_LATE.
        el["status"] = "REJECTED_LATE"
        touch(el, now)
        return success(core.serialize(el))
