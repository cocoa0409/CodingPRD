"""Campus and career-fair brand presences, the second claim on the budget."""

from datetime import timedelta

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import require
from services import budget, calc, serialize

bp = Blueprint("presences", __name__)

READ_ROLES = ("BrandProgramLead", "MediaBuyer", "RecruitingOps", "CommunityManager")
BUFFER = timedelta(hours=48)


@bp.route("/event-presences", methods=["POST"])
@require("MediaBuyer")
def plan_presence():
    data = V.body()
    program_id = V.field(data, "program_id", "string", required=True)
    job_family_id = V.field(data, "job_family_id", "string", required=True)
    venue_code = V.field(data, "venue_code", "string", required=True,
                         min_len=2, max_len=40)
    start_at = V.field(data, "start_at", "datetime", required=True)
    end_at = V.field(data, "end_at", "datetime", required=True)
    booth_cost_cents = V.field(data, "booth_cost_cents", "integer", required=True,
                               min_value=1)
    program = calc.must_get(db.programs, program_id, "ERR_PROGRAM_NOT_FOUND")
    family = calc.must_get(db.job_families, job_family_id, "ERR_JOB_FAMILY_NOT_FOUND")
    row = {
        "id": db.new_id(),
        "program_id": program["id"],
        "job_family_id": family["id"],
        "venue_code": venue_code,
        "start_at": start_at,
        "end_at": end_at,
        "booth_cost_cents": booth_cost_cents,
        "state": "PLANNED",
        "reserved_cents": 0,
        "confirmed_at": None,
    }
    stamp = db.wall_now()
    row.update({"created_at": stamp, "updated_at": stamp, "version": 1})
    db.presences[row["id"]] = row
    return response.ok(serialize.presence(row), 201)


@bp.route("/event-presences/<presence_id>/confirm", methods=["POST"])
@require("MediaBuyer")
def confirm_presence(presence_id):
    presence = calc.must_get(db.presences, presence_id, "ERR_PRESENCE_NOT_FOUND")
    if presence["state"] != "PLANNED":
        raise ApiError("ERR_PRESENCE_NOT_PLANNED", "The presence is not PLANNED.")
    for other in db.presences.values():
        if other["id"] == presence["id"] or other["state"] not in ("CONFIRMED", "COMPLETED"):
            continue
        if other["job_family_id"] != presence["job_family_id"]:
            continue
        after = presence["start_at"] >= other["end_at"] + BUFFER
        before = presence["end_at"] + BUFFER <= other["start_at"]
        if not (after or before):
            raise ApiError("ERR_EVENT_BUFFER_CONFLICT",
                           "The recruiter-team 48 hour buffer is not respected.")
    family = db.job_families[presence["job_family_id"]]
    program = db.programs[presence["program_id"]]
    budget.reserve(program, family, presence["booth_cost_cents"], "EVENT_PRESENCE",
                   presence["id"], "EVENT_RESERVATION")
    presence["reserved_cents"] = presence["booth_cost_cents"]
    presence["confirmed_at"] = db.clock()
    presence["state"] = "CONFIRMED"
    db.touch(presence)
    db.touch(program)
    return response.ok(serialize.presence(presence))


@bp.route("/event-presences/<presence_id>/complete", methods=["POST"])
@require("MediaBuyer")
def complete_presence(presence_id):
    presence = calc.must_get(db.presences, presence_id, "ERR_PRESENCE_NOT_FOUND")
    if presence["state"] != "CONFIRMED":
        raise ApiError("ERR_PRESENCE_NOT_CONFIRMED", "The presence is not CONFIRMED.")
    if db.clock() <= presence["end_at"]:
        raise ApiError("ERR_EVENT_WINDOW_OPEN", "The event window is still open.")
    presence["state"] = "COMPLETED"
    db.touch(presence)
    return response.ok(serialize.presence(presence))


@bp.route("/event-presences/<presence_id>/cancel", methods=["POST"])
@require("MediaBuyer")
def cancel_presence(presence_id):
    data = V.body()
    V.field(data, "reason", "string", nullable=True, min_len=0, max_len=500)
    presence = calc.must_get(db.presences, presence_id, "ERR_PRESENCE_NOT_FOUND")
    if presence["state"] not in ("PLANNED", "CONFIRMED"):
        raise ApiError("ERR_PRESENCE_ALREADY_TERMINAL",
                       "The presence is already terminal.")
    was_confirmed = presence["state"] == "CONFIRMED"
    presence["state"] = "CANCELLED"
    if was_confirmed:
        program = db.programs[presence["program_id"]]
        presence["reserved_cents"] = 0
        if budget.release(program, presence["id"], "EVENT_CANCELLED"):
            db.touch(program)
    db.touch(presence)
    return response.ok(serialize.presence(presence))


@bp.route("/event-presences/<presence_id>", methods=["GET"])
@require(*READ_ROLES)
def get_presence(presence_id):
    presence = calc.must_get(db.presences, presence_id, "ERR_PRESENCE_NOT_FOUND")
    return response.ok(serialize.presence(presence))


@bp.route("/event-presences", methods=["GET"])
@require(*READ_ROLES)
def list_presences():
    limit, offset = V.pagination()
    rows = sorted(db.presences.values(), key=lambda r: (r["start_at"], r["created_at"]))
    for name in ("program_id", "job_family_id", "state", "venue_code"):
        value = V.qs(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    page, meta = V.window(rows, limit, offset)
    return response.ok_list([serialize.presence(r) for r in page], meta)
