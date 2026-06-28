"""ProgramAssignment endpoints + lifecycle (PRD §3.7)."""

from flask import Blueprint, g, request

import errors
from db import db, new_id, now_ts
from helpers import (get_json_body, require_fields, require_string,
                     require_positive_int, pagination_params, paginate)
from middleware import require_roles
from response import success, list_success
from serializers import program_view
from services import domain

bp = Blueprint("program_assignments", __name__)


@bp.route("/program-assignments", methods=["POST"])
@require_roles("Trainer")
def create_program():
    body = get_json_body()
    require_fields(body, "engagement_id", "title", "planned_workouts_per_week", "habit_checks_target")

    engagement = domain.get_engagement(body["engagement_id"])
    domain.assert_owns_engagement(engagement)

    title = require_string(body["title"], "title")
    planned = require_positive_int(body["planned_workouts_per_week"], "planned_workouts_per_week")
    target = require_positive_int(body["habit_checks_target"], "habit_checks_target")

    # Creating a program requires the parent engagement to be ACTIVE.
    if engagement["status"] != "ACTIVE":
        raise errors.invalid_state(errors.ERR_ENGAGEMENT_NOT_ACTIVE, "Engagement is not ACTIVE")

    pid = new_id()
    ts = now_ts()
    program = {
        "id": pid,
        "engagement_id": engagement["id"],
        "title": title,
        "planned_workouts_per_week": planned,
        "habit_checks_target": target,
        "status": "DRAFT",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.program_assignments[pid] = program
    return success(program_view(program), 201)


@bp.route("/program-assignments/<program_id>", methods=["GET"])
@require_roles("Trainer", "Client")
def get_program(program_id):
    program = domain.get_program(program_id)
    engagement = domain.get_engagement(program["engagement_id"])
    domain.assert_owns_engagement(engagement)
    return success(program_view(program), 200)


@bp.route("/program-assignments", methods=["GET"])
@require_roles("Trainer", "Client", "PlatformAdmin")
def list_programs():
    limit, offset = pagination_params()
    engagement_filter = request.args.get("engagement_id")
    items = list(db.program_assignments.values())
    if engagement_filter is not None:
        items = [p for p in items if p["engagement_id"] == engagement_filter]
    if g.user_role in ("Trainer", "Client"):
        items = [p for p in items if _owns_program(p)]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, total = paginate(items, limit, offset)
    return list_success([program_view(p) for p in page], limit, offset, total, 200)


def _owns_program(program):
    engagement = db.engagements.get(program["engagement_id"])
    if engagement is None:
        return False
    if g.user_role == "Trainer":
        return engagement["trainer_id"] == g.user_id
    if g.user_role == "Client":
        return engagement["client_id"] == g.user_id
    return True


@bp.route("/program-assignments/<program_id>/publish", methods=["POST"])
@require_roles("Trainer")
def publish_program(program_id):
    program = domain.get_program(program_id)
    engagement = domain.get_engagement(program["engagement_id"])
    domain.assert_owns_engagement(engagement)
    if program["status"] != "DRAFT":
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Program is not DRAFT")
    if engagement["status"] != "ACTIVE":
        raise errors.invalid_state(errors.ERR_ENGAGEMENT_NOT_ACTIVE, "Engagement is not ACTIVE")
    program["status"] = "PUBLISHED"
    domain.touch(program)
    return success(program_view(program), 200)


@bp.route("/program-assignments/<program_id>/archive", methods=["POST"])
@require_roles("Trainer")
def archive_program(program_id):
    program = domain.get_program(program_id)
    engagement = domain.get_engagement(program["engagement_id"])
    domain.assert_owns_engagement(engagement)
    if program["status"] not in ("DRAFT", "PUBLISHED"):
        raise errors.invalid_state(errors.ERR_INVALID_STATE, "Program is not DRAFT or PUBLISHED")
    program["status"] = "ARCHIVED"
    domain.touch(program)
    return success(program_view(program), 200)
