"""GrantReport lifecycle (PRD section 3.9)."""
from flask import Blueprint

from db import db
from errors import ERR_INVALID_REPORT_STATE, ERR_INVALID_REQUEST, fail
from middleware import require_roles
from response import ok_object
from services.common import get_or_404, touch
from services.serialize import grant_report_json
from validators import body, check_allowed, req_str

bp = Blueprint("reports", __name__)

_READ_ROLES = ["SupervisingAttorney", "GrantsManager", "ProgramDirector"]


def _get_report(rid):
    return get_or_404(db.grant_reports, rid)


def _require_report_state(report, states):
    if report["status"] not in states:
        fail(ERR_INVALID_REPORT_STATE,
             "Report is {} and cannot perform this transition".format(
                 report["status"]))


@bp.route("/grant-reports/<rid>", methods=["GET"])
@require_roles(_READ_ROLES)
def get_report(rid):
    return ok_object(grant_report_json(_get_report(rid)))


@bp.route("/grant-reports/<rid>/submit", methods=["POST"])
@require_roles(["GrantsManager"])
def submit_report(rid):
    report = _get_report(rid)
    b = body()
    check_allowed(b, [])
    _require_report_state(report, ["DRAFT"])
    report["status"] = "SUBMITTED"
    touch(report)
    return ok_object(grant_report_json(report))


@bp.route("/grant-reports/<rid>/accept", methods=["POST"])
@require_roles(["ProgramDirector"])
def accept_report(rid):
    report = _get_report(rid)
    b = body()
    check_allowed(b, [])
    _require_report_state(report, ["SUBMITTED"])
    report["status"] = "ACCEPTED"
    touch(report)
    return ok_object(grant_report_json(report))


@bp.route("/grant-reports/<rid>/return", methods=["POST"])
@require_roles(["ProgramDirector"])
def return_report(rid):
    report = _get_report(rid)
    b = body()
    check_allowed(b, ["return_reason"])
    return_reason = req_str(b, "return_reason")
    if not return_reason.strip():
        fail(ERR_INVALID_REQUEST, "return_reason must be non-empty")
    _require_report_state(report, ["SUBMITTED"])
    report["status"] = "RETURNED"
    report["return_reason"] = return_reason
    touch(report)
    return ok_object(grant_report_json(report))


@bp.route("/grant-reports/<rid>/revise", methods=["POST"])
@require_roles(["GrantsManager"])
def revise_report(rid):
    report = _get_report(rid)
    b = body()
    check_allowed(b, [])
    _require_report_state(report, ["RETURNED"])
    from routes.grants import _compute_aggregates
    program = db.grant_programs.get(report["grant_program_id"])
    if program is not None:
        report.update(_compute_aggregates(program))
    report["status"] = "DRAFT"
    touch(report)
    return ok_object(grant_report_json(report))
