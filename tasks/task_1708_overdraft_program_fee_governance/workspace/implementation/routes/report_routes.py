from flask import Blueprint, request

import db
from errors import (ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_REPORT_OVERLAP, ERR_REPORT_GAP,
                    ERR_SELF_SUBMISSION)
from helpers import (auth, require_role, require_body, ok, ok_list, v_str,
                     v_date, parse_date_str, ALL_ROLES, sort_created)
from serializers import report_to_dict
from services import compute_report_metrics, parse_d

bp = Blueprint("reports", __name__)


def get_report_or_404(rid):
    r = db.store["reports"].get(rid)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Report %s not found" % rid)
    return r


@bp.post("/v1/reports")
def create_report():
    _, role = auth()
    require_role(role, ["ProgramAdmin", "ComplianceOfficer"])
    body = require_body()
    program_id = v_str(body, "program_id")
    period_start = v_date(body, "period_start")
    period_end = v_date(body, "period_end")
    if parse_date_str(period_end) < parse_date_str(period_start):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "period_end must not be earlier than period_start")
    program = db.store["programs"].get(program_id)
    if program is None:
        raise ApiError(ERR_NOT_FOUND, 404, "Program %s not found" % program_id)
    # Tier 9: overlap check runs BEFORE the gap check (closed intervals).
    start = parse_d(period_start)
    end = parse_d(period_end)
    existing = [r for r in db.store["reports"].values() if r["program_id"] == program_id]
    for r in existing:
        rs = parse_d(r["period_start"])
        re_ = parse_d(r["period_end"])
        if not (end < rs or start > re_):
            raise ApiError(ERR_REPORT_OVERLAP, 409,
                           "Period intersects an existing report's period")
    if existing:
        prev_end = max(parse_d(r["period_end"]) for r in existing)
        from datetime import timedelta
        if start != prev_end + timedelta(days=1):
            raise ApiError(ERR_REPORT_GAP, 409,
                           "period_start must be exactly the previous period_end + 1 day")
    r = db.new_entity({
        "program_id": program_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "revenue_provisional_cents": None,
        "revenue_final_cents": None,
        "waiver_ratio_bps": None,
        "avg_fees_per_overdrafter_centi": None,
        "scrutiny_flag": None,
        "finalized_by_user_id": None,
    })
    db.store["reports"][r["id"]] = r
    return ok(report_to_dict(r), status=201)


@bp.get("/v1/reports")
def list_reports():
    _, role = auth()
    require_role(role, ALL_ROLES)
    items = list(db.store["reports"].values())
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    if program_id is not None:
        items = [r for r in items if r["program_id"] == program_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return ok_list([report_to_dict(r) for r in sort_created(items)])


@bp.get("/v1/reports/<rid>")
def get_report(rid):
    _, role = auth()
    require_role(role, ALL_ROLES)
    return ok(report_to_dict(get_report_or_404(rid)))


@bp.post("/v1/reports/<rid>/finalize")
def finalize_report(rid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    r = get_report_or_404(rid)
    if r["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OPEN report can be finalized")
    compute_report_metrics(r)
    r["finalized_by_user_id"] = uid
    r["status"] = "FINALIZED"
    db.touch(r)
    return ok(report_to_dict(r))


@bp.post("/v1/reports/<rid>/submit")
def submit_report(rid):
    uid, role = auth()
    require_role(role, ["ComplianceOfficer"])
    r = get_report_or_404(rid)
    if r["status"] != "FINALIZED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only a FINALIZED report can be submitted")
    if uid == r["finalized_by_user_id"]:
        raise ApiError(ERR_SELF_SUBMISSION, 409,
                       "Submitter must differ from the finalizer")
    r["status"] = "SUBMITTED"
    db.touch(r)
    return ok(report_to_dict(r))
