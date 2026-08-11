"""ChapterProgram endpoints."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    err_budget_exceeded, err_group_not_active, err_invalid_request,
    err_invalid_state, err_not_found, err_referential, err_spend_overrun,
    err_unauthorized, err_venue_conflict,
)
from middleware import require_roles
from response import success_list, success_object
from services.common import (
    apply_pagination, format_ts, json_body, new_entity, pagination_args,
    parse_iso, req_int, req_str, touch,
)
from services.serializers import PROGRAM_FIELDS, serialize
from routes.groups import get_group_or_404, rederive_budget_remaining

bp = Blueprint("programs", __name__)

STAFF_OR_DIRECTOR = ("AlumniRelationsStaff", "AlumniRelationsDirector")
PROGRAM_READ = ("AlumniRelationsStaff", "AlumniRelationsDirector", "AffinityGroupLeader")
LEADER = ("AffinityGroupLeader",)
BUFFER = timedelta(minutes=60)


def get_program_or_404(pid):
    p = db.programs.get(pid)
    if p is None:
        raise err_not_found("ChapterProgram not found")
    return p


def _check_leader_ownership(program, user_id):
    if program["leader_id"] != user_id:
        raise err_unauthorized("Acting user is not the program leader")


@bp.route("/alumni/groups/<gid>/programs", methods=["POST"])
@require_roles("AffinityGroupLeader", "AlumniRelationsStaff", "AlumniRelationsDirector")
def create_program(gid, _role, _user_id):
    group = get_group_or_404(gid)
    body = json_body(required=["title", "venue_slot_start", "venue_slot_end",
                               "budget_allocated_cents", "leader_id"])
    title = req_str(body["title"], "title")
    start_dt = parse_iso(body["venue_slot_start"])
    end_dt = parse_iso(body["venue_slot_end"])
    if not start_dt <= end_dt:
        raise err_invalid_request("venue_slot_start must be <= venue_slot_end")
    budget = req_int(body["budget_allocated_cents"], "budget_allocated_cents")
    if budget < 0:
        raise err_invalid_request("budget_allocated_cents must be >= 0")
    leader_id = req_str(body["leader_id"], "leader_id")
    leader = db.records.get(leader_id)
    if leader is None:
        raise err_referential("Leader AlumniRecord not found")
    if leader["status"] != "ACTIVE":
        raise err_referential("Leader must be an ACTIVE alumnus")

    program = new_entity({
        "group_id": gid,
        "title": title,
        "venue_slot_start": format_ts(start_dt),
        "venue_slot_start_dt": start_dt,
        "venue_slot_end": format_ts(end_dt),
        "venue_slot_end_dt": end_dt,
        "budget_allocated_cents": budget,
        "actual_spend_cents": None,
        "status": "DRAFT",
        "leader_id": leader_id,
    })
    db.programs[program["id"]] = program
    return success_object(serialize(program, PROGRAM_FIELDS), status=201)


@bp.route("/alumni/groups/<gid>/programs", methods=["GET"])
@require_roles(*PROGRAM_READ)
def list_group_programs(gid, _role, _user_id):
    get_group_or_404(gid)
    limit, offset = pagination_args()
    rows = [p for p in db.programs.values() if p["group_id"] == gid]
    status = request.args.get("status")
    if status:
        rows = [p for p in rows if p["status"] == status]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(p, PROGRAM_FIELDS) for p in page], limit, offset, total)


@bp.route("/alumni/programs/<pid>", methods=["GET"])
@require_roles(*PROGRAM_READ)
def get_program(pid, _role, _user_id):
    return success_object(serialize(get_program_or_404(pid), PROGRAM_FIELDS))


@bp.route("/alumni/programs", methods=["GET"])
@require_roles(*PROGRAM_READ)
def list_programs(_role, _user_id):
    limit, offset = pagination_args()
    rows = list(db.programs.values())
    leader_id = request.args.get("leader_id")
    if leader_id:
        rows = [p for p in rows if p["leader_id"] == leader_id]
    group_id = request.args.get("group_id")
    if group_id:
        rows = [p for p in rows if p["group_id"] == group_id]
    status = request.args.get("status")
    if status:
        rows = [p for p in rows if p["status"] == status]
    page, total = apply_pagination(rows, limit, offset)
    return success_list([serialize(p, PROGRAM_FIELDS) for p in page], limit, offset, total)


@bp.route("/alumni/programs/<pid>/propose", methods=["POST"])
@require_roles(*LEADER)
def propose(pid, _role, _user_id):
    program = get_program_or_404(pid)
    _check_leader_ownership(program, _user_id)
    if program["status"] != "DRAFT":
        raise err_invalid_state("Program must be DRAFT to propose")
    group = get_group_or_404(program["group_id"])
    if group["status"] != "ACTIVE":
        raise err_group_not_active()
    program["status"] = "PROPOSED"
    touch(program)
    return success_object(serialize(program, PROGRAM_FIELDS))


@bp.route("/alumni/programs/<pid>/withdraw", methods=["POST"])
@require_roles(*LEADER)
def withdraw(pid, _role, _user_id):
    program = get_program_or_404(pid)
    _check_leader_ownership(program, _user_id)
    if program["status"] != "PROPOSED":
        raise err_invalid_state("Program must be PROPOSED to withdraw")
    program["status"] = "DRAFT"
    touch(program)
    return success_object(serialize(program, PROGRAM_FIELDS))


@bp.route("/alumni/programs/<pid>/approve", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def approve(pid, _role, _user_id):
    program = get_program_or_404(pid)
    if program["status"] != "PROPOSED":
        raise err_invalid_state("Program must be PROPOSED to approve")
    group = get_group_or_404(program["group_id"])
    if group["status"] != "ACTIVE":
        raise err_group_not_active()
    rederive_budget_remaining(group)
    if program["budget_allocated_cents"] > group["budget_remaining_cents"]:
        raise err_budget_exceeded()

    # venue conflict: closed interval [start, end+60min] overlap with other
    # APPROVED/PUBLISHED/COMPLETED programs of the same group
    my_start = program["venue_slot_start_dt"]
    my_end = program["venue_slot_end_dt"] + BUFFER
    for other in db.programs.values():
        if other["id"] == program["id"] or other["group_id"] != program["group_id"]:
            continue
        if other["status"] not in ("APPROVED", "PUBLISHED", "COMPLETED"):
            continue
        o_start = other["venue_slot_start_dt"]
        o_end = other["venue_slot_end_dt"] + BUFFER
        if my_start <= o_end and o_start <= my_end:
            raise err_venue_conflict()

    program["status"] = "APPROVED"
    touch(program)
    group["budget_committed_cents"] += program["budget_allocated_cents"]
    rederive_budget_remaining(group)
    touch(group)
    return success_object(serialize(program, PROGRAM_FIELDS))


@bp.route("/alumni/programs/<pid>/publish", methods=["POST"])
@require_roles(*LEADER)
def publish(pid, _role, _user_id):
    program = get_program_or_404(pid)
    _check_leader_ownership(program, _user_id)
    if program["status"] != "APPROVED":
        raise err_invalid_state("Program must be APPROVED to publish")
    program["status"] = "PUBLISHED"
    touch(program)
    return success_object(serialize(program, PROGRAM_FIELDS))


@bp.route("/alumni/programs/<pid>/complete", methods=["POST"])
@require_roles(*LEADER)
def complete(pid, _role, _user_id):
    program = get_program_or_404(pid)
    _check_leader_ownership(program, _user_id)
    if program["status"] != "PUBLISHED":
        raise err_invalid_state("Program must be PUBLISHED to complete")
    body = json_body(required=["actual_spend_cents"])
    actual = req_int(body["actual_spend_cents"], "actual_spend_cents")
    if actual < 0:
        raise err_invalid_request("actual_spend_cents must be >= 0")
    if actual > program["budget_allocated_cents"]:
        raise err_spend_overrun()

    program["status"] = "COMPLETED"
    program["actual_spend_cents"] = actual
    touch(program)
    group = get_group_or_404(program["group_id"])
    group["budget_committed_cents"] -= program["budget_allocated_cents"]
    group["budget_spent_cents"] += actual
    rederive_budget_remaining(group)
    touch(group)
    return success_object(serialize(program, PROGRAM_FIELDS))


@bp.route("/alumni/programs/<pid>/cancel", methods=["POST"])
@require_roles(*STAFF_OR_DIRECTOR)
def cancel_program(pid, _role, _user_id):
    program = get_program_or_404(pid)
    if program["status"] not in ("APPROVED", "PUBLISHED"):
        raise err_invalid_state("Program must be APPROVED or PUBLISHED to cancel")
    program["status"] = "CANCELLED"
    touch(program)
    group = get_group_or_404(program["group_id"])
    group["budget_committed_cents"] -= program["budget_allocated_cents"]
    rederive_budget_remaining(group)
    touch(group)
    return success_object(serialize(program, PROGRAM_FIELDS))
