"""ProgramEnrollment creation, listing, and voluntary exit (PRD §3.4)."""

from flask import Blueprint, request

import db
from db import store, new_entity, touch, public
from errors import (err_not_found, err_state, err_reference, ApiError,
                    ERR_MEMBER_NOT_ACTIVE, ERR_PROGRAM_NOT_OPEN, ERR_FUTURE_QUARTER)
from middleware import require_roles, body_json, req_str
from response import success_object, success_list, parse_pagination, paginate

bp = Blueprint("enrollments", __name__)

READ_ROLES = ("CoopAdmin", "FinanceOfficer", "ProgramAuditor", "MemberRep", "SupplierRep")


def get_enrollment_or_404(enrollment_id):
    enr = store.enrollments.get(enrollment_id)
    if enr is None:
        raise err_not_found("ProgramEnrollment not found")
    return enr


def _arg(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.route("/coop/enrollments", methods=["POST"])
@require_roles("CoopAdmin", "MemberRep")
def create_enrollment(uid, role):
    body = body_json(required=True)
    member_id = req_str(body, "member_id")
    program_id = req_str(body, "program_id")
    member = store.members.get(member_id)
    if member is None:
        raise err_reference("member_id does not resolve to an existing Member")
    program = store.programs.get(program_id)
    if program is None:
        raise err_reference("program_id does not resolve to an existing SupplierProgram")
    if member["status"] != "ACTIVE":
        raise ApiError(ERR_MEMBER_NOT_ACTIVE, 409, "Member must be ACTIVE to enroll")
    if program["status"] not in ("OPEN", "REOPENED"):
        raise ApiError(ERR_PROGRAM_NOT_OPEN, 409,
                       "SupplierProgram must be OPEN or REOPENED to accept enrollments")
    enr = new_entity()
    enr.update({
        "member_id": member["id"],
        "program_id": program["id"],
        "enrolled_quarter_index": db.get_coop()["current_quarter_index"],
        "exit_quarter_index": None,
        "status": "ACTIVE",
        "exclusivity_share_pct": 0,
        "exclusivity_status": ("COMPLIANT" if program["exclusivity_required"]
                               else "NOT_APPLICABLE"),
    })
    store.enrollments[enr["id"]] = enr
    return success_object(public(enr), code=201)


@bp.route("/coop/enrollments/<enrollment_id>", methods=["GET"])
@require_roles(*READ_ROLES)
def get_enrollment(uid, role, enrollment_id):
    return success_object(public(get_enrollment_or_404(enrollment_id)), code=200)


@bp.route("/coop/enrollments", methods=["GET"])
@require_roles(*READ_ROLES)
def list_enrollments(uid, role):
    limit, offset = parse_pagination()
    items = list(store.enrollments.values())
    member_id = _arg("member_id")
    if member_id is not None:
        items = [e for e in items if e["member_id"] == member_id]
    program_id = _arg("program_id")
    if program_id is not None:
        items = [e for e in items if e["program_id"] == program_id]
    status = _arg("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([public(e) for e in page], limit, offset, total)


@bp.route("/coop/enrollments/<enrollment_id>/exit", methods=["POST"])
@require_roles("CoopAdmin", "MemberRep")
def exit_enrollment(uid, role, enrollment_id):
    enr = get_enrollment_or_404(enrollment_id)
    if enr["status"] != "ACTIVE":
        raise err_state("Only an ACTIVE enrollment can be exited")
    current = db.get_coop()["current_quarter_index"]
    if enr["enrolled_quarter_index"] is not None and enr["enrolled_quarter_index"] > current:
        raise ApiError(ERR_FUTURE_QUARTER, 409,
                       "Cannot exit an enrollment that starts in a future quarter")
    enr["status"] = "EXITED"
    enr["exit_quarter_index"] = current
    touch(enr)
    return success_object(public(enr), code=200)
