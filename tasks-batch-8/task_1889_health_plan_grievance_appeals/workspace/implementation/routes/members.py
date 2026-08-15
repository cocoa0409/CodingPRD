"""Member endpoints (PRD section 3.1)."""

from flask import Blueprint, request

import calc
import db
import errors
from auth import require_roles
from envelope import (paginate, parse_pagination, success_list,
                      success_object)
from serializers import case_out, member_out
from services import get_or_404
from validate import get_body, req_enum, req_str

bp = Blueprint("members", __name__)

PROGRAMS = {"MEDICARE", "MEDI_CAL", "DUAL"}
ALL_ROLES = {"PlatformAdmin", "IntakeSpecialist", "CaseAnalyst",
             "MedicalDirector", "MemberServicesRep", "ComplianceOfficer",
             "ClaimsProcessor"}


@bp.route("/appeals/members", methods=["POST"])
@require_roles({"PlatformAdmin"})
def create_member(_user_id, _role):
    body = get_body()
    member_ref = req_str(body, "member_ref")
    if not (1 <= len(member_ref) <= 64):
        raise errors.validation("member_ref must be 1..64 characters")
    full_name = req_str(body, "full_name")
    program = req_enum(body, "program", PROGRAMS)
    for m in db.members.values():
        if m["member_ref"] == member_ref:
            raise errors.validation("member_ref must be unique across the plan")
    m = db.make_common()
    m.update({
        "member_ref": member_ref,
        "full_name": full_name,
        "program": program,
        "enrollment_status": "ACTIVE",
    })
    db.members[m["id"]] = m
    return success_object(member_out(m), status=201)


@bp.route("/appeals/members/<mid>", methods=["GET"])
@require_roles(ALL_ROLES)
def get_member(mid, _user_id, _role):
    m = get_or_404(db.members, mid, "member")
    return success_object(member_out(m))


@bp.route("/appeals/members", methods=["GET"])
@require_roles({"PlatformAdmin", "ComplianceOfficer"})
def list_members(_user_id, _role):
    limit, offset = parse_pagination(request.args)
    rows = list(db.members.values())
    program = request.args.get("program")
    if program is not None:
        rows = [m for m in rows if m["program"] == program]
    rows.sort(key=lambda m: (m["created_at"], m["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([member_out(m) for m in page], total, limit, offset)


@bp.route("/appeals/members/<mid>/ctm-exposure", methods=["GET"])
@require_roles({"PlatformAdmin", "ComplianceOfficer", "MemberServicesRep"})
def ctm_exposure(mid, _user_id, _role):
    get_or_404(db.members, mid, "member")
    return success_object(calc.ctm_exposure(mid))


@bp.route("/appeals/members/<mid>/cases", methods=["GET"])
@require_roles({"PlatformAdmin", "IntakeSpecialist", "CaseAnalyst",
                "ComplianceOfficer", "MemberServicesRep"})
def member_cases(mid, _user_id, _role):
    get_or_404(db.members, mid, "member")
    limit, offset = parse_pagination(request.args)
    rows = [c for c in db.cases.values() if c["member_id"] == mid]
    status = request.args.get("status")
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows.sort(key=lambda c: (c["created_at"], c["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([case_out(c) for c in page], total, limit, offset)
