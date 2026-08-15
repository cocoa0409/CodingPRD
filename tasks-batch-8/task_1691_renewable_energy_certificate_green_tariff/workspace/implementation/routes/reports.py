"""Claim report endpoints: pin, submit, adjudicate, revise."""

from flask import Blueprint, request

from errors import raise_err, ERR_REPORT_STATE_INVALID, ERR_SELF_APPROVAL, \
    ERR_DOUBLE_COUNT, ERR_DUPLICATE_REPORT, ERR_REPORT_EMPTY, \
    ERR_CLAIM_CAP_EXCEEDED
from store import STORE, new_id, next_seq, now_ts
from util import auth, require_role, forbidden, ok_object, body_json, req_str, \
    req_int, req_enum, opt_str, get_or_404
from services import repin_report, accepted_report_exists, touch
from routes.generators import list_with_serializer

bp = Blueprint("reports", __name__)

SCOPE_ROLE = {
    "VOLUNTARY_PROGRAM": "ProgramManager",
    "COMPLIANCE_OBLIGATION": "ComplianceOfficer",
}


def serialize_report(r):
    return {k: v for k, v in r.items() if not k.startswith("_")}


def _check_scope_role(report, role):
    required = SCOPE_ROLE.get(report["scope"])
    if required and role != required:
        forbidden("Report scope %s requires role %s" % (report["scope"], required))


@bp.post("/greenpower/claim-reports")
def create_report():
    uid, role = auth()
    require_role(role, "ProgramManager", "ComplianceOfficer")
    body = body_json()
    scope = body.get("scope")
    if scope in SCOPE_ROLE and role != SCOPE_ROLE[scope]:
        forbidden("Report scope %s requires role %s" % (scope, SCOPE_ROLE[scope]))
    scope = req_enum(body, "scope", set(SCOPE_ROLE))
    report_year = req_int(body, "report_year")
    program_id = None
    obligation_id = None
    if scope == "VOLUNTARY_PROGRAM":
        program_id = req_str(body, "program_id")
    else:
        obligation_id = req_str(body, "obligation_id")
    if program_id is not None:
        get_or_404(STORE["programs"], program_id, "Program")
    if obligation_id is not None:
        get_or_404(STORE["obligations"], obligation_id, "ComplianceObligation")
    if accepted_report_exists(scope, program_id, obligation_id, report_year):
        raise_err(ERR_DUPLICATE_REPORT,
                  "An ACCEPTED report already exists for this scope and year")

    now = now_ts()
    report = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "scope": scope,
        "program_id": program_id,
        "obligation_id": obligation_id,
        "report_year": report_year,
        "status": "DRAFT",
        "retirement_ids": [],
        "total_mwh": 0,
        "totals_by_technology": {},
        "totals_by_region": {},
        "submitted_by_user_id": None,
        "rejection_reason": None,
        "_seq": next_seq(),
    }
    repin_report(report)
    STORE["reports"][report["id"]] = report
    return ok_object(serialize_report(report), 201)


@bp.get("/greenpower/claim-reports")
def list_reports():
    auth()
    filters = {
        "program_id": request.args.get("program_id"),
        "obligation_id": request.args.get("obligation_id"),
        "status": request.args.get("status"),
        "report_year": request.args.get("report_year"),
    }
    return list_with_serializer(list(STORE["reports"].values()), filters,
                                serialize_report)


@bp.get("/greenpower/claim-reports/<rid>")
def get_report(rid):
    auth()
    report = get_or_404(STORE["reports"], rid, "ClaimReport")
    return ok_object(serialize_report(report))


@bp.post("/greenpower/claim-reports/<rid>/submit")
def submit_report(rid):
    uid, role = auth()
    require_role(role, "ProgramManager", "ComplianceOfficer")
    report = get_or_404(STORE["reports"], rid, "ClaimReport")
    _check_scope_role(report, role)
    if report["status"] != "DRAFT":
        raise_err(ERR_REPORT_STATE_INVALID, "Submission requires a DRAFT report")
    # Safety before fiscal: double-count guard first.
    for ret_id in report["retirement_ids"]:
        ret = STORE["retirements"].get(ret_id)
        if ret is not None and ret.get("claimed_in_report_id") is not None:
            raise_err(ERR_DOUBLE_COUNT,
                      "A pinned retirement is already claimed by another ACCEPTED report")
    if accepted_report_exists(report["scope"], report.get("program_id"),
                              report.get("obligation_id"), report["report_year"],
                              exclude_id=report["id"]):
        raise_err(ERR_DUPLICATE_REPORT,
                  "An ACCEPTED report already exists for this scope and year")
    if not report["retirement_ids"]:
        raise_err(ERR_REPORT_EMPTY, "A submitting report must pin at least one retirement")
    if report["scope"] == "VOLUNTARY_PROGRAM":
        program = STORE["programs"].get(report["program_id"])
        if program is not None and report["total_mwh"] > program["annual_claim_cap_mwh"]:
            raise_err(ERR_CLAIM_CAP_EXCEEDED,
                      "Report total exceeds the program annual claim cap")
    report["submitted_by_user_id"] = uid
    # Recompute totals from the pinned set.
    pinned = [STORE["retirements"][i] for i in report["retirement_ids"]
              if i in STORE["retirements"]]
    from services import totalize
    total, by_tech, by_region = totalize(pinned)
    report["total_mwh"] = total
    report["totals_by_technology"] = by_tech
    report["totals_by_region"] = by_region
    report["status"] = "SUBMITTED"
    touch(report)
    return ok_object(serialize_report(report))


@bp.post("/greenpower/claim-reports/<rid>/accept")
def accept_report(rid):
    uid, role = auth()
    require_role(role, "Auditor")
    report = get_or_404(STORE["reports"], rid, "ClaimReport")
    if report["status"] != "SUBMITTED":
        raise_err(ERR_REPORT_STATE_INVALID, "Acceptance requires a SUBMITTED report")
    if uid == report["submitted_by_user_id"]:
        raise_err(ERR_SELF_APPROVAL,
                  "An auditor may not decide a report they submitted")
    for ret_id in report["retirement_ids"]:
        ret = STORE["retirements"].get(ret_id)
        if ret is not None:
            ret["claimed_in_report_id"] = report["id"]
    report["status"] = "ACCEPTED"
    touch(report)
    return ok_object(serialize_report(report))


@bp.post("/greenpower/claim-reports/<rid>/reject")
def reject_report(rid):
    uid, role = auth()
    require_role(role, "Auditor")
    report = get_or_404(STORE["reports"], rid, "ClaimReport")
    if report["status"] != "SUBMITTED":
        raise_err(ERR_REPORT_STATE_INVALID, "Rejection requires a SUBMITTED report")
    if uid == report["submitted_by_user_id"]:
        raise_err(ERR_SELF_APPROVAL,
                  "An auditor may not decide a report they submitted")
    body = body_json()
    report["rejection_reason"] = opt_str(body, "reason")
    report["status"] = "REJECTED"
    touch(report)
    return ok_object(serialize_report(report))


@bp.post("/greenpower/claim-reports/<rid>/revise")
def revise_report(rid):
    uid, role = auth()
    require_role(role, "ProgramManager", "ComplianceOfficer")
    report = get_or_404(STORE["reports"], rid, "ClaimReport")
    _check_scope_role(report, role)
    if report["status"] != "REJECTED":
        raise_err(ERR_REPORT_STATE_INVALID, "Revision requires a REJECTED report")
    repin_report(report)
    report["rejection_reason"] = None
    report["submitted_by_user_id"] = None
    report["status"] = "DRAFT"
    touch(report)
    return ok_object(serialize_report(report))
