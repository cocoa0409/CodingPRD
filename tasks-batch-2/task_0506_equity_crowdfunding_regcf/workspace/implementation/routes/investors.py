"""Investor + accreditation-request endpoints (PRD 3.4)."""
from flask import Blueprint, request

from calculations import investor_annual_limit
from db import db, new_id, now_iso
from derive import touch
from errors import err
from middleware import get_auth, get_auth_optional, require_role
from pagination import paginate
from response import success
from serializers import investor_out, accreditation_request_out
from validation import require_body, require_str, require_int, require_enum

bp = Blueprint("investors", __name__)

ACC_METHODS = {"INCOME", "NET_WORTH", "THIRD_PARTY_LETTER"}


# --------------------------------------------------------------------------
# Investor
# --------------------------------------------------------------------------
@bp.post("/investors")
def create_investor():
    uid, role = get_auth_optional()
    if role is not None:
        require_role(role, {"Anonymous", "ComplianceOfficer"})

    body = require_body()
    email = require_str(body, "email")
    legal_name = require_str(body, "legal_name")
    annual_income = require_int(body, "annual_income_cents", minimum=0)
    net_worth = require_int(body, "net_worth_cents", minimum=0)

    for existing in db.investors.values():
        if existing["email"] == email:
            raise err("ERR_DUPLICATE_RESOURCE", "An investor with this email already exists")

    ts = now_iso()
    iid = new_id()
    rec = {
        "id": iid,
        "email": email,
        "legal_name": legal_name,
        "annual_income_cents": annual_income,
        "net_worth_cents": net_worth,
        "accreditation_status": "UNACCREDITED",
        "annual_limit_cents": investor_annual_limit(annual_income, net_worth),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.investors[iid] = rec
    return success(investor_out(rec), status=201)


@bp.get("/investors/<id>")
def get_investor(id):
    uid, role = get_auth_optional()
    if role is not None:
        require_role(role, {"Anonymous", "Investor", "ComplianceOfficer"})
    rec = db.investors.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Investor not found")
    return success(investor_out(rec))


# --------------------------------------------------------------------------
# Accreditation requests
# --------------------------------------------------------------------------
@bp.post("/accreditation-requests")
def create_accreditation_request():
    uid, role = get_auth()
    require_role(role, {"Investor"})

    body = require_body()
    investor_id = require_str(body, "investor_id")
    method = require_enum(body, "method", ACC_METHODS)

    investor = db.investors.get(investor_id)
    if investor is None:
        raise err("ERR_NOT_FOUND", "Investor not found")
    if investor_id != uid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Caller may only file accreditation for itself")

    ts = now_iso()
    rid = new_id()
    rec = {
        "id": rid,
        "investor_id": investor_id,
        "method": method,
        "status": "PENDING",
        "reviewed_by_user_id": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.accreditation_requests[rid] = rec
    return success(accreditation_request_out(rec), status=201)


@bp.get("/accreditation-requests/<id>")
def get_accreditation_request(id):
    uid, role = get_auth()
    require_role(role, {"Investor", "ComplianceOfficer"})
    rec = db.accreditation_requests.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Accreditation request not found")
    return success(accreditation_request_out(rec))


@bp.get("/accreditation-requests")
def list_accreditation_requests():
    uid, role = get_auth()
    require_role(role, {"Investor", "ComplianceOfficer"})
    rows = list(db.accreditation_requests.values())
    for field in ("investor_id", "status"):
        val = request.args.get(field)
        if val is not None:
            rows = [r for r in rows if r[field] == val]
    page, meta = paginate(rows)
    return success([accreditation_request_out(r) for r in page], pagination=meta)


@bp.post("/accreditation-requests/<id>/approve")
def approve_accreditation_request(id):
    uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    rec = db.accreditation_requests.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Accreditation request not found")
    if rec["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Accreditation request is not PENDING")
    rec["status"] = "APPROVED"
    rec["reviewed_by_user_id"] = uid
    investor = db.investors.get(rec["investor_id"])
    if investor is not None:
        investor["accreditation_status"] = "ACCREDITED"
        touch(investor)
    touch(rec)
    return success(accreditation_request_out(rec))


@bp.post("/accreditation-requests/<id>/deny")
def deny_accreditation_request(id):
    uid, role = get_auth()
    require_role(role, {"ComplianceOfficer"})
    rec = db.accreditation_requests.get(id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Accreditation request not found")
    if rec["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Accreditation request is not PENDING")
    rec["status"] = "DENIED"
    rec["reviewed_by_user_id"] = uid
    touch(rec)
    return success(accreditation_request_out(rec))
