"""DeadlinePolicy endpoints (PRD section 2.9)."""

from flask import Blueprint, request

import db
import errors
from auth import require_roles
from envelope import (paginate, parse_bool_param, parse_pagination,
                      success_list, success_object)
from serializers import policy_out
from validate import (get_body, opt_bool, opt_int, req_enum, req_int)

bp = Blueprint("policies", __name__)

PROGRAMS = {"MEDICARE", "MEDI_CAL", "DUAL"}
CASE_KINDS = {"GRIEVANCE", "ORG_DETERMINATION", "APPEAL"}
PRIORITY_TRACKS = {"STANDARD", "EXPEDITED"}


@bp.route("/appeals/deadline-policies", methods=["POST"])
@require_roles({"PlatformAdmin"})
def create_policy(_user_id, _role):
    body = get_body()
    program = req_enum(body, "program", PROGRAMS)
    case_kind = req_enum(body, "case_kind", CASE_KINDS)
    priority_track = req_enum(body, "priority_track", PRIORITY_TRACKS)
    resolution_hours = req_int(body, "resolution_hours")
    if not (0 < resolution_hours <= 720):
        raise errors.validation("resolution_hours must be > 0 and <= 720")
    extension_hours = opt_int(body, "extension_hours", 0)
    if not (0 <= extension_hours <= 336):
        raise errors.validation("extension_hours must be >= 0 and <= 336")
    effectuation_hours = req_int(body, "effectuation_hours")
    if not (0 < effectuation_hours <= 720):
        raise errors.validation("effectuation_hours must be > 0 and <= 720")
    business_hours_only = opt_bool(body, "business_hours_only", False)
    active = opt_bool(body, "active", True)
    p = db.make_common()
    p.update({
        "program": program,
        "case_kind": case_kind,
        "priority_track": priority_track,
        "resolution_hours": resolution_hours,
        "extension_hours": extension_hours,
        "effectuation_hours": effectuation_hours,
        "business_hours_only": business_hours_only,
        "active": active,
    })
    db.policies[p["id"]] = p
    if active:
        # Only one active policy per (program, case_kind, priority_track).
        for other in db.policies.values():
            if (other["id"] != p["id"] and other["active"]
                    and other["program"] == program
                    and other["case_kind"] == case_kind
                    and other["priority_track"] == priority_track):
                other["active"] = False
                db.touch(other)
    return success_object(policy_out(p), status=201)


@bp.route("/appeals/deadline-policies", methods=["GET"])
@require_roles({"PlatformAdmin", "ComplianceOfficer"})
def list_policies(_user_id, _role):
    limit, offset = parse_pagination(request.args)
    rows = list(db.policies.values())
    program = request.args.get("program")
    if program is not None:
        rows = [p for p in rows if p["program"] == program]
    case_kind = request.args.get("case_kind")
    if case_kind is not None:
        rows = [p for p in rows if p["case_kind"] == case_kind]
    priority_track = request.args.get("priority_track")
    if priority_track is not None:
        rows = [p for p in rows if p["priority_track"] == priority_track]
    active = parse_bool_param(request.args, "active")
    if active is not None:
        rows = [p for p in rows if p["active"] == active]
    rows.sort(key=lambda p: (p["created_at"], p["_seq"]))
    page, total = paginate(rows, limit, offset)
    return success_list([policy_out(p) for p in page], total, limit, offset)
