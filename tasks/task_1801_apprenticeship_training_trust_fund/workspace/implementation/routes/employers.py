"""Employer endpoints: create, get, list, patch (rate)."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success_object, success_list

bp = Blueprint("employers", __name__)

ALL_ROLES = ("TrustAdmin", "EmployerRep", "CommitteeMember", "Instructor")


def employer_view(e):
    return {
        "id": e["id"],
        "trust_fund_id": e["trust_fund_id"],
        "legal_name": e["legal_name"],
        "agreement_rate_cents_per_hour": e["agreement_rate_cents_per_hour"],
        "status": e["status"],
        "outstanding_cents": e["outstanding_cents"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def get_employer_or_404(eid):
    e = db.employers.get(eid)
    if e is None:
        raise errors.err_employer_not_found()
    return e


@bp.route("/employers", methods=["POST"])
def create_employer():
    mw.require_roles("TrustAdmin")
    body = mw.get_body()
    mw.require_fields(body, ["trust_fund_id", "legal_name", "agreement_rate_cents_per_hour"])
    if not mw.is_str(body["trust_fund_id"]):
        raise errors.err_invalid_request("trust_fund_id must be a string")
    if body["trust_fund_id"] not in db.trust_funds:
        raise errors.err_fund_not_found()
    if not mw.is_str(body["legal_name"]):
        raise errors.err_invalid_request("legal_name must be a string")
    rate = body["agreement_rate_cents_per_hour"]
    if not mw.is_int(rate) or rate < 0:
        raise errors.err_invalid_request("agreement_rate_cents_per_hour must be a non-negative integer")
    eid = db.new_id()
    now = db.now_iso()
    emp = {
        "id": eid,
        "trust_fund_id": body["trust_fund_id"],
        "legal_name": body["legal_name"],
        "agreement_rate_cents_per_hour": rate,
        "status": "ACTIVE",
        "outstanding_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.employers[eid] = emp
    return success_object(employer_view(emp), 201)


@bp.route("/employers/<eid>", methods=["GET"])
def get_employer(eid):
    mw.require_roles(*ALL_ROLES)
    return success_object(employer_view(get_employer_or_404(eid)), 200)


@bp.route("/employers", methods=["GET"])
def list_employers():
    mw.require_roles(*ALL_ROLES)
    limit, offset = mw.parse_pagination(request.args)
    tf = request.args.get("trust_fund_id")
    status = request.args.get("status")
    items = list(db.employers.values())
    if tf is not None:
        items = [e for e in items if e["trust_fund_id"] == tf]
    if status is not None:
        items = [e for e in items if e["status"] == status]
    items.sort(key=lambda e: (db._parse_iso(e["created_at"]), e["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([employer_view(e) for e in page], limit, offset, total)


@bp.route("/employers/<eid>", methods=["PATCH"])
def patch_employer(eid):
    mw.require_roles("TrustAdmin")
    emp = get_employer_or_404(eid)
    body = mw.get_body()
    if "agreement_rate_cents_per_hour" in body and body["agreement_rate_cents_per_hour"] is not None:
        rate = body["agreement_rate_cents_per_hour"]
        if not mw.is_int(rate) or rate < 0:
            raise errors.err_invalid_request("agreement_rate_cents_per_hour must be a non-negative integer")
        emp["agreement_rate_cents_per_hour"] = rate
        emp["updated_at"] = db.now_iso()
        emp["version"] += 1
    return success_object(employer_view(emp), 200)
