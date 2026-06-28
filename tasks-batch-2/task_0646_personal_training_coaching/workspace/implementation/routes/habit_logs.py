"""HabitLog endpoints (append-only) (PRD §3.8)."""

from flask import Blueprint, g, request

import errors
from db import db, new_id, now_ts
from clock import format_iso8601_ms
from helpers import (get_json_body, require_fields, require_enum,
                     parse_required_datetime, pagination_params, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import habit_log_view
from services import domain

bp = Blueprint("habit_logs", __name__)

KINDS = {"WORKOUT_COMPLETED", "NUTRITION_LOGGED", "HABIT_CHECK"}


@bp.route("/habit-logs", methods=["POST"])
@require_roles("Client", "Trainer")
def create_habit_log():
    body = get_json_body()
    require_fields(body, "engagement_id", "program_assignment_id", "kind", "logged_at")

    engagement = domain.get_engagement(body["engagement_id"])
    domain.assert_owns_engagement(engagement)
    program = domain.get_program(body["program_assignment_id"])

    kind = require_enum(body["kind"], KINDS, "kind")
    logged_at = parse_required_datetime(body["logged_at"], "logged_at")

    # Priority 14: program must be PUBLISHED in the same engagement.
    if program["engagement_id"] != engagement["id"] or program["status"] != "PUBLISHED":
        raise errors.invalid_state(errors.ERR_PROGRAM_NOT_PUBLISHED,
                                   "Program is not PUBLISHED in this engagement")

    hid = new_id()
    ts = now_ts()
    log = {
        "id": hid,
        "engagement_id": engagement["id"],
        "program_assignment_id": program["id"],
        "kind": kind,
        "logged_at": format_iso8601_ms(logged_at),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    db.habit_logs[hid] = log
    return success(habit_log_view(log), 201)


@bp.route("/habit-logs/<habit_log_id>", methods=["GET"])
@require_roles("Trainer", "Client")
def get_habit_log(habit_log_id):
    log = domain.get_habit_log(habit_log_id)
    engagement = domain.get_engagement(log["engagement_id"])
    domain.assert_owns_engagement(engagement)
    return success(habit_log_view(log), 200)


@bp.route("/habit-logs", methods=["GET"])
@require_roles("Trainer", "Client")
def list_habit_logs():
    limit, offset = pagination_params()
    engagement_filter = request.args.get("engagement_id")
    program_filter = request.args.get("program_assignment_id")
    items = list(db.habit_logs.values())
    if engagement_filter is not None:
        items = [h for h in items if h["engagement_id"] == engagement_filter]
    if program_filter is not None:
        items = [h for h in items if h["program_assignment_id"] == program_filter]
    # Ownership scoping.
    items = [h for h in items if _owns_log(h)]
    items.sort(key=lambda h: (h["created_at"], h["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_success([habit_log_view(h) for h in page], limit, offset, total, 200)


def _owns_log(log):
    engagement = db.engagements.get(log["engagement_id"])
    if engagement is None:
        return False
    if g.user_role == "Trainer":
        return engagement["trainer_id"] == g.user_id
    if g.user_role == "Client":
        return engagement["client_id"] == g.user_id
    return True
