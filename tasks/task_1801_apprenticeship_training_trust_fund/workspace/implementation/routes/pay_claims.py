"""InstructorPayClaim endpoints: create, get, list, approve, reject, pay."""

from flask import Blueprint, request

import db
import errors
import middleware as mw
from response import success_object, success_list
from services import ledger

bp = Blueprint("pay_claims", __name__)

ALL_ROLES = ("TrustAdmin", "EmployerRep", "CommitteeMember", "Instructor")


def claim_view(c):
    return {
        "id": c["id"],
        "class_id": c["class_id"],
        "instructor_user_id": c["instructor_user_id"],
        "pay_basis": c["pay_basis"],
        "actual_minutes": c["actual_minutes"],
        "payable_cents": c["payable_cents"],
        "status": c["status"],
        "approved_by_user_id": c["approved_by_user_id"],
        "paid_at": c["paid_at"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def get_claim_or_404(cid):
    c = db.instructor_pay_claims.get(cid)
    if c is None:
        raise errors.err_claim_not_found()
    return c


@bp.route("/pay-claims", methods=["POST"])
def create_claim():
    user_id, _ = mw.require_roles("Instructor")
    body = mw.get_body()
    mw.require_fields(body, ["class_id", "pay_basis"])
    if not mw.is_str(body["class_id"]):
        raise errors.err_invalid_request("class_id must be a string")
    cls = db.training_classes.get(body["class_id"])
    if cls is None:
        raise errors.err_class_not_found()
    # Ownership: X-User-ID must equal the class's instructor_user_id
    if user_id != cls["instructor_user_id"]:
        raise errors.err_not_owner()

    basis = body["pay_basis"]
    if basis not in ("SCHEDULED", "ACTUAL"):
        raise errors.err_invalid_request("pay_basis must be SCHEDULED or ACTUAL")
    actual_minutes = body.get("actual_minutes")
    if basis == "ACTUAL":
        if actual_minutes is None:
            raise errors.err_invalid_request("actual_minutes is required for ACTUAL claims")
        if not mw.is_int(actual_minutes) or actual_minutes < 0:
            raise errors.err_invalid_request("actual_minutes must be a non-negative integer")
    else:
        if actual_minutes is not None and not mw.is_int(actual_minutes):
            raise errors.err_invalid_request("actual_minutes must be an integer")

    # Class must be COMPLETED
    if cls["status"] != "COMPLETED":
        raise errors.err_invalid_state("pay claims require a COMPLETED class")
    # One open claim per class
    for c in db.instructor_pay_claims.values():
        if c["class_id"] == cls["id"] and c["status"] in ("SUBMITTED", "APPROVED"):
            raise errors.err_duplicate_claim()

    payable = ledger.compute_payable_cents(cls, basis, actual_minutes)

    cid = db.new_id()
    now = db.now_iso()
    claim = {
        "id": cid,
        "class_id": cls["id"],
        "instructor_user_id": cls["instructor_user_id"],
        "pay_basis": basis,
        "actual_minutes": actual_minutes if basis == "ACTUAL" else actual_minutes,
        "payable_cents": payable,
        "status": "SUBMITTED",
        "approved_by_user_id": None,
        "paid_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.instructor_pay_claims[cid] = claim
    return success_object(claim_view(claim), 201)


@bp.route("/pay-claims/<cid>", methods=["GET"])
def get_claim(cid):
    mw.require_roles(*ALL_ROLES)
    return success_object(claim_view(get_claim_or_404(cid)), 200)


@bp.route("/pay-claims", methods=["GET"])
def list_claims():
    mw.require_roles(*ALL_ROLES)
    limit, offset = mw.parse_pagination(request.args)
    cid = request.args.get("class_id")
    iid = request.args.get("instructor_user_id")
    status = request.args.get("status")
    items = list(db.instructor_pay_claims.values())
    if cid is not None:
        items = [c for c in items if c["class_id"] == cid]
    if iid is not None:
        items = [c for c in items if c["instructor_user_id"] == iid]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda c: (db._parse_iso(c["created_at"]), c["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([claim_view(c) for c in page], limit, offset, total)


def _fund_for_claim(claim):
    cls = db.training_classes.get(claim["class_id"])
    if cls is None:
        return None
    return db.trust_funds.get(cls["trust_fund_id"])


@bp.route("/pay-claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    user_id, _ = mw.require_roles("CommitteeMember")
    claim = get_claim_or_404(cid)
    if claim["status"] != "SUBMITTED":
        raise errors.err_claim_not_approvable()
    fund = _fund_for_claim(claim)
    if fund is not None:
        ledger.recompute_fund_posture(fund)
        if fund["posture"] != "OPERATING":
            raise errors.err_fund_on_compliance_hold()
    claim["status"] = "APPROVED"
    claim["approved_by_user_id"] = user_id
    ledger.touch(claim)
    return success_object(claim_view(claim), 200)


@bp.route("/pay-claims/<cid>/reject", methods=["POST"])
def reject_claim(cid):
    mw.require_roles("CommitteeMember")
    claim = get_claim_or_404(cid)
    if claim["status"] != "SUBMITTED":
        raise errors.err_claim_not_approvable()
    claim["status"] = "REJECTED"
    ledger.touch(claim)
    return success_object(claim_view(claim), 200)


@bp.route("/pay-claims/<cid>/pay", methods=["POST"])
def pay_claim(cid):
    mw.require_roles("TrustAdmin")
    claim = get_claim_or_404(cid)
    if claim["status"] != "APPROVED":
        raise errors.err_claim_not_payable()
    claim["status"] = "PAID"
    claim["paid_at"] = db.now_iso()
    ledger.touch(claim)
    fund = _fund_for_claim(claim)
    if fund is not None:
        ledger.recompute_fund(fund, bump_version=True)
    return success_object(claim_view(claim), 200)
