"""Staff and officiating assignments (official pay rail)."""

from flask import Blueprint, g, request

import errors as E
from domain import (staff_out, assignment_out, get_or_404, check_official_travel_buffer,
                    official_provisional_pay, official_final_pay, CLASS_TYPES)
from store import DB
from util import (body_json, req_str, req_int, req_enum, is_int, envelope_object,
                  list_response, require_role, stamp_new, touch)

bp = Blueprint("staff", __name__)

STAFF_ROLES = {"OFFICIAL", "INSTRUCTOR"}


@bp.route("/v1/staff", methods=["POST"])
def create_staff():
    require_role("RecAdmin")
    body = body_json()
    full_name = req_str(body, "full_name")
    staff_role = req_enum(body, "staff_role", STAFF_ROLES)
    base_rate = req_int(body, "base_hourly_rate_cents")
    if base_rate <= 0:
        raise E.err_validation("base_hourly_rate_cents must be > 0")
    cert_level = body.get("certification_level")
    class_types = body.get("certified_class_types")
    if staff_role == "OFFICIAL":
        if cert_level is None:
            raise E.err_validation("certification_level is required for OFFICIAL staff")
        if not is_int(cert_level) or not (1 <= cert_level <= 3):
            raise E.err_validation("certification_level must be an integer in 1..3")
        if class_types is not None:
            raise E.err_validation("certified_class_types is forbidden for OFFICIAL staff")
    else:  # INSTRUCTOR
        if class_types is None:
            raise E.err_validation("certified_class_types is required for INSTRUCTOR staff")
        if not isinstance(class_types, list) or not class_types or \
           not all(isinstance(c, str) and c in CLASS_TYPES for c in class_types):
            raise E.err_validation("certified_class_types must be a non-empty subset of class types")
        if cert_level is not None:
            raise E.err_validation("certification_level is forbidden for INSTRUCTOR staff")
    staff = stamp_new({
        "full_name": full_name,
        "staff_role": staff_role,
        "certification_level": cert_level,
        "certified_class_types": list(class_types) if class_types is not None else None,
        "base_hourly_rate_cents": base_rate,
        "payroll_pending_cents": 0,
        "payroll_paid_cents": 0,
    })
    DB.staff[staff["id"]] = staff
    return envelope_object(staff_out(staff), 201)


@bp.route("/v1/staff/<staff_id>", methods=["GET"])
def get_staff(staff_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    staff = get_or_404(DB.staff, staff_id)
    return envelope_object(staff_out(staff))


@bp.route("/v1/games/<game_id>/officiating-assignments", methods=["POST"])
def create_assignment(game_id):
    require_role("LeagueCoordinator")
    game = get_or_404(DB.games, game_id)
    body = body_json()
    staff_id = req_str(body, "staff_id")
    staff = get_or_404(DB.staff, staff_id)
    if game["status"] != "SCHEDULED":
        raise E.err_invalid_state("Officials can only be assigned to a SCHEDULED game")
    # Travel buffer (priority 9) runs before constraint/capacity checks.
    check_official_travel_buffer(staff_id, game["start_at"], game["end_at"])
    if staff["staff_role"] != "OFFICIAL":
        raise E.err_staff_not_official()
    if game["bracket_round"] in ("SEMIFINAL", "CHAMPIONSHIP") and \
       (staff["certification_level"] is None or staff["certification_level"] < 2):
        raise E.err_cert_too_low()
    live = sum(1 for a in DB.assignments.values()
               if a["game_id"] == game_id and a["status"] in ("ASSIGNED", "ACCEPTED", "WORKED"))
    if live >= 2:
        raise E.err_assignment_limit()
    provisional = official_provisional_pay(game["duration_minutes"], staff)
    assignment = stamp_new({
        "game_id": game_id,
        "staff_id": staff_id,
        "status": "ASSIGNED",
        "provisional_pay_cents": provisional,
        "final_pay_cents": None,
    })
    DB.assignments[assignment["id"]] = assignment
    staff["payroll_pending_cents"] += provisional
    touch(staff)
    return envelope_object(assignment_out(assignment), 201)


@bp.route("/v1/officiating-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    assignment = get_or_404(DB.assignments, assignment_id)
    return envelope_object(assignment_out(assignment))


@bp.route("/v1/officiating-assignments", methods=["GET"])
def list_assignments():
    require_role("RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff")
    game_id = request.args.get("game_id")
    staff_id = request.args.get("staff_id")
    status = request.args.get("status")
    records = [a for a in DB.assignments.values()
               if (game_id is None or a["game_id"] == game_id)
               and (staff_id is None or a["staff_id"] == staff_id)
               and (status is None or a["status"] == status)]
    return list_response(records, assignment_out)


@bp.route("/v1/officiating-assignments/<assignment_id>/respond", methods=["POST"])
def respond_assignment(assignment_id):
    require_role("Staff")
    assignment = get_or_404(DB.assignments, assignment_id)
    if assignment["staff_id"] != g.user_id:
        raise E.err_forbidden("Only the assigned official may respond")
    body = body_json()
    response = req_enum(body, "response", {"ACCEPT", "DECLINE"})
    if assignment["status"] != "ASSIGNED":
        raise E.err_invalid_state("Only an ASSIGNED assignment can be answered")
    if response == "ACCEPT":
        assignment["status"] = "ACCEPTED"
        touch(assignment)
    else:
        assignment["status"] = "DECLINED"
        touch(assignment)
        staff = DB.staff.get(assignment["staff_id"])
        if staff is not None:
            staff["payroll_pending_cents"] -= assignment["provisional_pay_cents"]
            touch(staff)
    return envelope_object(assignment_out(assignment))


@bp.route("/v1/officiating-assignments/<assignment_id>/settle", methods=["POST"])
def settle_assignment(assignment_id):
    require_role("LeagueCoordinator")
    assignment = get_or_404(DB.assignments, assignment_id)
    if assignment["status"] != "WORKED":
        raise E.err_invalid_state("Only a WORKED assignment can be settled")
    game = DB.games.get(assignment["game_id"])
    staff = DB.staff.get(assignment["staff_id"])
    if game is None or staff is None:
        raise E.err_not_found("Assignment references a missing game or staff member")
    final_pay = official_final_pay(game, staff)
    assignment["final_pay_cents"] = final_pay
    assignment["status"] = "PAID"
    touch(assignment)
    staff["payroll_pending_cents"] -= assignment["provisional_pay_cents"]
    staff["payroll_paid_cents"] += final_pay
    touch(staff)
    return envelope_object(assignment_out(assignment))
