"""ConflictCheck resolution (PRD section 3.3)."""
from flask import Blueprint, g

from db import db, now
from errors import (ERR_CONFLICT_UNRESOLVED, ERR_ETHICS_RECUSAL,
                    ERR_INVALID_REQUEST, fail)
from middleware import require_roles
from response import ok_object
from services.common import create_unmet_record, get_or_404, touch
from services.serialize import conflict_check_json
from validators import body, check_allowed, opt_str, req_enum

bp = Blueprint("conflict_checks", __name__)

_READ_ROLES = ["IntakeSpecialist", "SupervisingAttorney", "EthicsOfficer",
               "ProgramDirector"]


@bp.route("/conflict-checks/<cid>", methods=["GET"])
@require_roles(_READ_ROLES)
def get_conflict_check(cid):
    return ok_object(conflict_check_json(get_or_404(db.conflict_checks, cid)))


@bp.route("/conflict-checks/<cid>/resolve", methods=["POST"])
@require_roles(["EthicsOfficer"])
def resolve_conflict_check(cid):
    check = get_or_404(db.conflict_checks, cid)
    b = body()
    check_allowed(b, ["resolution", "waiver_reason"])
    resolution = req_enum(b, "resolution", ["CONFIRMED_CONFLICT", "WAIVED"])
    waiver_reason = opt_str(b, "waiver_reason")
    # State legality.
    if check["result"] != "POTENTIAL_CONFLICT":
        fail(ERR_CONFLICT_UNRESOLVED,
             "Only a POTENTIAL_CONFLICT check can be resolved")
    # Segregation of duties: resolver must differ from the checker.
    if g.user_id == check["checked_by_staff_id"]:
        fail(ERR_ETHICS_RECUSAL,
             "The officer who ran this check may not resolve it")
    if resolution == "WAIVED" and not (waiver_reason
                                       and waiver_reason.strip()):
        fail(ERR_INVALID_REQUEST,
             "waiver_reason is required when resolution is WAIVED")
    check["result"] = resolution
    check["resolved_by_staff_id"] = g.user_id
    check["resolved_at"] = now()
    if resolution == "WAIVED":
        check["waiver_reason"] = waiver_reason
    touch(check)
    if resolution == "CONFIRMED_CONFLICT":
        app = db.applications.get(check["application_id"])
        if app is not None:
            create_unmet_record(app, "CONFLICT_CONFIRMED")
    return ok_object(conflict_check_json(check))
