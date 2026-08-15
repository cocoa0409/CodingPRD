"""Apprentice endpoints: intake, registration lifecycle, indenture, cancel, certify."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success_object, success_list
from services import ledger

bp = Blueprint("apprentices", __name__)

ALL_ROLES = ("TrustAdmin", "EmployerRep", "CommitteeMember", "Instructor")


def apprentice_view(a):
    return {
        "id": a["id"],
        "trust_fund_id": a["trust_fund_id"],
        "employer_id": a["employer_id"],
        "full_name": a["full_name"],
        "trade": a["trade"],
        "journeyman_base_rate_cents": a["journeyman_base_rate_cents"],
        "program_status": a["program_status"],
        "registration_status": a["registration_status"],
        "registration_agency": a["registration_agency"],
        "ojt_hours_accumulated": a["ojt_hours_accumulated"],
        "rti_credits_accumulated": a["rti_credits_accumulated"],
        "current_wage_step": a["current_wage_step"],
        "current_wage_rate_cents": a["current_wage_rate_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def get_apprentice_or_404(aid):
    a = db.apprentices.get(aid)
    if a is None:
        raise errors.err_apprentice_not_found()
    return a


@bp.route("/apprentices", methods=["POST"])
def create_apprentice():
    mw.require_roles("TrustAdmin")
    body = mw.get_body()
    mw.require_fields(body, ["trust_fund_id", "employer_id", "full_name", "trade",
                             "journeyman_base_rate_cents"])
    # Existence validated left-to-right: fund first, then employer
    if not mw.is_str(body["trust_fund_id"]):
        raise errors.err_invalid_request("trust_fund_id must be a string")
    if body["trust_fund_id"] not in db.trust_funds:
        raise errors.err_fund_not_found()
    if not mw.is_str(body["employer_id"]):
        raise errors.err_invalid_request("employer_id must be a string")
    if body["employer_id"] not in db.employers:
        raise errors.err_employer_not_found()
    if not mw.is_str(body["full_name"]):
        raise errors.err_invalid_request("full_name must be a string")
    if not mw.is_str(body["trade"]):
        raise errors.err_invalid_request("trade must be a string")
    base = body["journeyman_base_rate_cents"]
    if not mw.is_int(base) or base < 0:
        raise errors.err_invalid_request("journeyman_base_rate_cents must be a non-negative integer")

    aid = db.new_id()
    now = db.now_iso()
    a = {
        "id": aid,
        "trust_fund_id": body["trust_fund_id"],
        "employer_id": body["employer_id"],
        "full_name": body["full_name"],
        "trade": body["trade"],
        "journeyman_base_rate_cents": base,
        "program_status": "APPLICANT",
        "registration_status": "UNFILED",
        "registration_agency": None,
        "ojt_hours_accumulated": 0,
        "rti_credits_accumulated": 0,
        "current_wage_step": 1,
        "current_wage_rate_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    ledger.recompute_wage(a)
    db.apprentices[aid] = a
    return success_object(apprentice_view(a), 201)


@bp.route("/apprentices/<aid>", methods=["GET"])
def get_apprentice(aid):
    mw.require_roles(*ALL_ROLES)
    return success_object(apprentice_view(get_apprentice_or_404(aid)), 200)


@bp.route("/apprentices", methods=["GET"])
def list_apprentices():
    mw.require_roles(*ALL_ROLES)
    limit, offset = mw.parse_pagination(request.args)
    tf = request.args.get("trust_fund_id")
    emp = request.args.get("employer_id")
    ps = request.args.get("program_status")
    rs = request.args.get("registration_status")
    items = list(db.apprentices.values())
    if tf is not None:
        items = [a for a in items if a["trust_fund_id"] == tf]
    if emp is not None:
        items = [a for a in items if a["employer_id"] == emp]
    if ps is not None:
        items = [a for a in items if a["program_status"] == ps]
    if rs is not None:
        items = [a for a in items if a["registration_status"] == rs]
    items.sort(key=lambda a: (db._parse_iso(a["created_at"]), a["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([apprentice_view(a) for a in page], limit, offset, total)


@bp.route("/apprentices/<aid>/indenture", methods=["POST"])
def indenture(aid):
    mw.require_roles("TrustAdmin")
    a = get_apprentice_or_404(aid)
    if a["program_status"] != "APPLICANT":
        raise errors.err_invalid_state("indenture requires program_status APPLICANT")
    if a["registration_status"] != "REGISTERED":
        raise errors.err_registration_required()
    a["program_status"] = "INDENTURED"
    ledger.touch(a)
    return success_object(apprentice_view(a), 200)


@bp.route("/apprentices/<aid>/cancel", methods=["POST"])
def cancel(aid):
    mw.require_roles("TrustAdmin")
    a = get_apprentice_or_404(aid)
    if a["program_status"] in ("COMPLETED", "CANCELLED"):
        raise errors.err_invalid_state("cancel requires a non-terminal program state")
    a["program_status"] = "CANCELLED"
    if a["registration_status"] in ("SUBMITTED", "REGISTERED"):
        a["registration_status"] = "DEREGISTERED"
    ledger.touch(a)
    # Cascade: ENROLLED enrollments -> DROPPED; owning classes recompute count
    affected_classes = set()
    for e in db.class_enrollments.values():
        if e["apprentice_id"] == aid and e["status"] == "ENROLLED":
            e["status"] = "DROPPED"
            ledger.touch(e)
            affected_classes.add(e["class_id"])
    for cid in affected_classes:
        cls = db.training_classes.get(cid)
        if cls is not None:
            ledger.recompute_enrolled_count(cls)
    return success_object(apprentice_view(a), 200)


@bp.route("/apprentices/<aid>/certify-journeyman", methods=["POST"])
def certify(aid):
    mw.require_roles("TrustAdmin")
    a = get_apprentice_or_404(aid)
    if a["program_status"] != "INDENTURED":
        raise errors.err_invalid_state("certify-journeyman requires program_status INDENTURED")
    if (a["ojt_hours_accumulated"] < 8000
            or a["rti_credits_accumulated"] < 576
            or a["registration_status"] != "REGISTERED"):
        raise errors.err_certification_not_met()
    a["program_status"] = "COMPLETED"
    a["registration_status"] = "DEREGISTERED"
    ledger.touch(a)
    return success_object(apprentice_view(a), 200)


@bp.route("/apprentices/<aid>/submit-registration", methods=["POST"])
def submit_registration(aid):
    mw.require_roles("TrustAdmin")
    a = get_apprentice_or_404(aid)
    body = mw.get_body()
    mw.require_fields(body, ["agency"])
    agency = body["agency"]
    if agency not in ("STATE", "FEDERAL"):
        raise errors.err_invalid_request("agency must be STATE or FEDERAL")
    if a["program_status"] in ("COMPLETED", "CANCELLED"):
        raise errors.err_invalid_state("cannot file registration for a terminal program state")
    if a["registration_status"] not in ("UNFILED", "REJECTED", "REVOKED"):
        raise errors.err_invalid_state(
            "submit-registration requires registration UNFILED, REJECTED, or REVOKED")
    a["registration_status"] = "SUBMITTED"
    a["registration_agency"] = agency
    ledger.touch(a)
    return success_object(apprentice_view(a), 200)


@bp.route("/apprentices/<aid>/record-registration-decision", methods=["POST"])
def record_registration_decision(aid):
    mw.require_roles("TrustAdmin")
    a = get_apprentice_or_404(aid)
    body = mw.get_body()
    mw.require_fields(body, ["outcome"])
    outcome = body["outcome"]
    if outcome not in ("REGISTERED", "REJECTED", "REVOKED"):
        raise errors.err_invalid_registration_outcome()
    # From-state rules per PRD §3.2:
    #   REGISTERED/REJECTED only from SUBMITTED; REVOKED only from REGISTERED.
    valid = (
        (outcome in ("REGISTERED", "REJECTED") and a["registration_status"] == "SUBMITTED")
        or (outcome == "REVOKED" and a["registration_status"] == "REGISTERED")
    )
    if not valid:
        raise errors.err_registration_not_submitted()
    if outcome == "REGISTERED":
        a["registration_status"] = "REGISTERED"
        if a["program_status"] == "SUSPENDED":
            a["program_status"] = "INDENTURED"
    elif outcome == "REJECTED":
        a["registration_status"] = "REJECTED"
    else:  # REVOKED
        a["registration_status"] = "REVOKED"
        if a["program_status"] == "INDENTURED":
            a["program_status"] = "SUSPENDED"
    ledger.touch(a)
    return success_object(apprentice_view(a), 200)
