"""The taxpayer and representative registries plus the enforcement case file."""

from flask import Blueprint, request

import clock
import db
import middleware as mw
import response
import services
import validate
from errors import err
from middleware import (COMPLIANCE_AUDITOR, DISCLOSURE_OFFICER,
                        PROGRAM_ADMINISTRATOR, REPRESENTATIVE, TAXPAYER)

bp = Blueprint("registry", __name__)

STAFF = [PROGRAM_ADMINISTRATOR, DISCLOSURE_OFFICER, COMPLIANCE_AUDITOR]


# =============================================================================
# taxpayers
# =============================================================================
@bp.post("/amnesty/taxpayers")
def create_taxpayer():
    mw.identity([PROGRAM_ADMINISTRATOR])
    body = validate.get_body()
    legal_name = validate.vstr(body, "legal_name")
    taxpayer_type = validate.venum(body, "taxpayer_type", validate.TAXPAYER_TYPES)
    tin_last4 = validate.vtin_last4(body, "tin_last4")
    is_registered = validate.vbool(body, "is_registered", required=False, default=True)

    rec = db.insert(db.taxpayers, {
        "legal_name": legal_name,
        "taxpayer_type": taxpayer_type,
        "tin_last4": tin_last4,
        "is_registered": is_registered,
        "nonparticipant_flag": False,
    })
    return response.created(services.taxpayer_out(rec))


@bp.get("/amnesty/taxpayers")
def list_taxpayers():
    mw.identity(STAFF)
    limit, offset = response.pagination()
    rows = mw.filter_flag(db.ordered(list(db.taxpayers.values())), "nonparticipant_flag")
    wanted_tier = request.args.get("escalation_tier")
    if wanted_tier is not None:
        rows = [r for r in rows if services.escalation_tier(r) == wanted_tier]
    return response.paginate(rows, limit, offset, services.taxpayer_out)


@bp.get("/amnesty/taxpayers/<taxpayer_id>")
def read_taxpayer(taxpayer_id):
    user_id, role = mw.identity(STAFF + [TAXPAYER])
    taxpayer = mw.find(db.taxpayers, taxpayer_id, "ERR_TAXPAYER_NOT_FOUND")
    mw.require_taxpayer_self(taxpayer, user_id, role)
    return response.ok(services.taxpayer_out(taxpayer))


@bp.get("/amnesty/taxpayers/<taxpayer_id>/compliance-behavior")
def read_behavior(taxpayer_id):
    mw.identity(STAFF)
    taxpayer = mw.find(db.taxpayers, taxpayer_id, "ERR_TAXPAYER_NOT_FOUND")
    return response.ok(services.compliance_behavior_report(taxpayer))


@bp.get("/amnesty/taxpayers/<taxpayer_id>/enforcement-cases")
def list_taxpayer_cases(taxpayer_id):
    mw.identity(STAFF)
    mw.find(db.taxpayers, taxpayer_id, "ERR_TAXPAYER_NOT_FOUND")
    limit, offset = response.pagination()
    rows = mw.filter_equals(services.taxpayer_cases(taxpayer_id), "status")
    rows = mw.filter_equals(rows, "case_type")
    return response.paginate(rows, limit, offset, services.case_out)


# =============================================================================
# enforcement cases
# =============================================================================
@bp.post("/amnesty/enforcement-cases")
def create_case():
    user_id, _ = mw.identity([COMPLIANCE_AUDITOR])
    body = validate.get_body()
    mw.body_fk(body, "taxpayer_id", db.taxpayers, "ERR_TAXPAYER_NOT_FOUND")

    taxpayer_id = validate.vid(body, "taxpayer_id")
    case_type = validate.venum(body, "case_type", validate.CASE_TYPES)
    tax_type = validate.venum(body, "tax_type", validate.TAX_TYPES)
    validate.vdate(body, "opened_at")

    rec = db.insert(db.enforcement_cases, {
        "taxpayer_id": taxpayer_id,
        "case_type": case_type,
        "tax_type": tax_type,
        "opened_at": body["opened_at"],
        "status": "OPEN",
        "closed_at": None,
        "opened_by_user_id": user_id,
    })
    return response.created(services.case_out(rec))


@bp.get("/amnesty/enforcement-cases/<case_id>")
def read_case(case_id):
    mw.identity(STAFF)
    case = mw.find(db.enforcement_cases, case_id, "ERR_ENFORCEMENT_CASE_NOT_FOUND")
    return response.ok(services.case_out(case))


@bp.post("/amnesty/enforcement-cases/<case_id>/close")
def close_case(case_id):
    mw.identity([COMPLIANCE_AUDITOR])
    case = mw.find(db.enforcement_cases, case_id, "ERR_ENFORCEMENT_CASE_NOT_FOUND")
    if case["status"] != "OPEN":
        raise err("ERR_CASE_NOT_OPEN")
    case["status"] = "CLOSED"
    case["closed_at"] = clock.now_iso()
    db.touch(case)
    return response.ok(services.case_out(case))


@bp.post("/amnesty/enforcement-cases/<case_id>/refer")
def refer_case(case_id):
    mw.identity([COMPLIANCE_AUDITOR])
    case = mw.find(db.enforcement_cases, case_id, "ERR_ENFORCEMENT_CASE_NOT_FOUND")
    if case["status"] != "OPEN":
        raise err("ERR_CASE_NOT_OPEN")
    case["status"] = "REFERRED"
    db.touch(case)
    return response.ok(services.case_out(case))


# =============================================================================
# representatives
# =============================================================================
@bp.post("/amnesty/representatives")
def create_representative():
    mw.identity([PROGRAM_ADMINISTRATOR])
    body = validate.get_body()
    firm_name = validate.vstr(body, "firm_name")
    bar_number = validate.vstr(body, "bar_number")
    rec = db.insert(db.representatives, {
        "firm_name": firm_name,
        "bar_number": bar_number,
        "status": "ACTIVE",
    })
    return response.created(services.representative_out(rec))


@bp.get("/amnesty/representatives/<representative_id>")
def read_representative(representative_id):
    mw.identity(STAFF + [REPRESENTATIVE])
    rec = mw.find(db.representatives, representative_id, "ERR_REPRESENTATIVE_NOT_FOUND")
    return response.ok(services.representative_out(rec))


@bp.post("/amnesty/representatives/<representative_id>/suspend")
def suspend_representative(representative_id):
    mw.identity([PROGRAM_ADMINISTRATOR])
    rec = mw.find(db.representatives, representative_id, "ERR_REPRESENTATIVE_NOT_FOUND")
    rec["status"] = "SUSPENDED"
    db.touch(rec)
    return response.ok(services.representative_out(rec))
