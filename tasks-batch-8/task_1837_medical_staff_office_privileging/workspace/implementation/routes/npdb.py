from datetime import timedelta

from flask import Blueprint

import db
import errors
import serializers
import services
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from util import get_body, paginate, require_enum, require_fields

bp = Blueprint("npdb", __name__)

COORD = "MedicalStaffCoordinator"
CHAIR = "CredentialsCommitteeChair"

REPORT_KINDS = ("QUERY_INITIAL", "QUERY_REAPPOINTMENT",
                "REPORT_ADVERSE_ACTION", "REPORT_CORRECTION", "REPORT_VOID")


def _get_report(rid):
    rec = db.npdb_reports.get(rid)
    if rec is None:
        errors.raise_err(errors.ERR_NOT_FOUND, "NpdbReport not found")
    return rec


@bp.route("/mso/npdb-reports", methods=["POST"])
@require_roles(COORD)
def create_report():
    body = get_body()
    # Rung 3: existence.
    member_id = body.get("member_id")
    if member_id is not None and member_id not in db.members:
        errors.raise_err(errors.ERR_NOT_FOUND, "MedicalStaffMember not found")
    case_id = body.get("case_id")
    if case_id is not None and case_id not in db.cases:
        errors.raise_err(errors.ERR_NOT_FOUND, "AdverseActionCase not found")
    # Rung 11: input shape (incl. REPORT_* kinds requiring case_id).
    require_fields(body, ["member_id", "report_kind"])
    kind = require_enum(body, "report_kind", REPORT_KINDS)
    if kind.startswith("REPORT_") and not case_id:
        errors.raise_err(errors.ERR_NPDB_CASE_REQUIRED,
                         "REPORT_* kinds require case_id")

    # Deadline inheritance by kind.
    deadline_dt = None
    if kind == "REPORT_ADVERSE_ACTION":
        deadline_dt = db.clock_now() + timedelta(
            days=services.NPDB_REPORT_WINDOW_DAYS)
    elif kind in ("REPORT_CORRECTION", "REPORT_VOID"):
        # Inherit the deadline of the report they correct / void: the most
        # recent filing for the same case carrying a deadline.
        candidates = [r for r in db.npdb_reports.values()
                      if r.get("case_id") == case_id
                      and r.get("submission_deadline")]
        if candidates:
            candidates.sort(key=lambda r: r["_seq"])
            from util import parse_dt
            deadline_dt = parse_dt(candidates[-1]["submission_deadline"])
    rec = services.spawn_npdb_report(member_id, case_id, kind, deadline_dt)
    return ok_object(serializers.npdb_report(rec), 201)


@bp.route("/mso/npdb-reports", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_reports():
    items, limit, offset, total = paginate(
        db.npdb_reports.values(), serializers.npdb_report,
        ["member_id", "case_id", "report_kind", "report_status"])
    return ok_list(items, limit, offset, total)


@bp.route("/mso/npdb-reports/<rid>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_report(rid):
    return ok_object(serializers.npdb_report(_get_report(rid)))


@bp.route("/mso/npdb-reports/<rid>/acknowledge", methods=["POST"])
@require_roles(COORD)
def acknowledge_report(rid):
    get_body()
    rec = _get_report(rid)
    if rec["report_status"] not in ("SUBMITTED", "LATE"):
        errors.raise_err(errors.ERR_NPDB_NOT_ACKNOWLEDGEABLE,
                         "Report is not in SUBMITTED or LATE")
    rec["report_status"] = "ACKNOWLEDGED"
    return ok_object(serializers.npdb_report(rec))


@bp.route("/mso/npdb-reports/<rid>/void", methods=["POST"])
@require_roles(CHAIR)
def void_report(rid):
    body = get_body()
    rec = _get_report(rid)
    # Rung 3: the correction reference is a body FK.
    correction_id = body.get("correction_report_id")
    correction = None
    if correction_id is not None:
        correction = db.npdb_reports.get(correction_id)
        if correction is None:
            errors.raise_err(errors.ERR_NOT_FOUND,
                             "correction_report_id does not exist")
    # Rung 5: state.
    if rec["report_status"] not in ("SUBMITTED", "LATE"):
        errors.raise_err(errors.ERR_NPDB_NOT_VOIDABLE,
                         "Report is not in SUBMITTED or LATE")
    # Rung 9: a void is never without its replacement correction.
    if (correction is None
            or correction["report_kind"] != "REPORT_CORRECTION"
            or correction.get("case_id") != rec.get("case_id")):
        errors.raise_err(errors.ERR_CORRECTION_REQUIRED,
                         "Voiding requires a replacement REPORT_CORRECTION "
                         "for the same case_id")
    rec["report_status"] = "VOIDED"
    return ok_object(serializers.npdb_report(rec))
