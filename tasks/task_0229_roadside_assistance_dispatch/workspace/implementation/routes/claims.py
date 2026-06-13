"""ReimbursementClaim routes (PRD §3.10)."""
from flask import Blueprint, request

import db
import errors
import serializers
import validation
from listing import sort_and_window
from middleware import authenticate, require_roles
from response import object_response, array_response

bp = Blueprint("claims", __name__)


@bp.route("/reimbursement-claims", methods=["POST"])
def create_claim():
    ident = authenticate()
    require_roles(ident, {"Member", "DispatchOperator"})
    body = validation.get_body()

    validation.require_present(body, ["member_id", "service_call_id", "claimed_amount_cents"])

    member_id = body["member_id"]
    if not isinstance(member_id, str):
        raise errors.invalid_request("member_id must be a string.")
    member = db.members.get(member_id)
    if member is None:
        raise errors.not_found("Member not found.")

    service_call_id = body["service_call_id"]
    if not isinstance(service_call_id, str):
        raise errors.invalid_request("service_call_id must be a string.")
    call = db.service_calls.get(service_call_id)
    if call is None:
        raise errors.not_found("Service call not found.")

    # ownership: a member may only file on its own behalf.
    if ident.is_member and ident.user_id != member_id:
        raise errors.not_resource_owner("A member may only file its own claims.")

    claimed = body["claimed_amount_cents"]

    # ERR_INVALID_CLAIM_TARGET: claim references a call not owned by the member,
    # or claimed_amount_cents < 1.
    if not validation.is_int(claimed) or claimed < 1 or call["member_id"] != member_id:
        raise errors.ApiError(errors.ERR_INVALID_CLAIM_TARGET, 422,
                              "Claim references a foreign call or claimed amount < 1.")

    record = {
        "member_id": member_id,
        "service_call_id": service_call_id,
        "claimed_amount_cents": claimed,
        "status": "SUBMITTED",
        "approved_amount_cents": 0,
    }
    db.stamp_create(record)
    db.reimbursement_claims[record["id"]] = record
    return object_response(serializers.reimbursement_claim(record), 201)


@bp.route("/reimbursement-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "Member"})
    c = db.reimbursement_claims.get(claim_id)
    if c is None:
        raise errors.not_found("Claim not found.")
    if ident.is_member and ident.user_id != c["member_id"]:
        raise errors.not_resource_owner("A member may only fetch its own claims.")
    return object_response(serializers.reimbursement_claim(c), 200)


@bp.route("/reimbursement-claims", methods=["GET"])
def list_claims():
    ident = authenticate()
    require_roles(ident, {"DispatchOperator", "Member"})
    limit, offset = validation.parse_pagination()
    member_id = request.args.get("member_id")
    service_call_id = request.args.get("service_call_id")
    status = request.args.get("status")
    records = list(db.reimbursement_claims.values())
    if ident.is_member:
        records = [c for c in records if c["member_id"] == ident.user_id]
    if member_id is not None:
        records = [c for c in records if c["member_id"] == member_id]
    if service_call_id is not None:
        records = [c for c in records if c["service_call_id"] == service_call_id]
    if status is not None:
        records = [c for c in records if c["status"] == status]
    page, total = sort_and_window(records, limit, offset)
    return array_response([serializers.reimbursement_claim(c) for c in page],
                          limit, offset, total, 200)


@bp.route("/reimbursement-claims/<claim_id>/begin-review", methods=["POST"])
def begin_review(claim_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    c = db.reimbursement_claims.get(claim_id)
    if c is None:
        raise errors.not_found("Claim not found.")
    if c["status"] != "SUBMITTED":
        raise errors.invalid_state("begin-review is only allowed from SUBMITTED.")
    c["status"] = "UNDER_REVIEW"
    db.touch(c)
    return object_response(serializers.reimbursement_claim(c), 200)


@bp.route("/reimbursement-claims/<claim_id>/request-info", methods=["POST"])
def request_info(claim_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    c = db.reimbursement_claims.get(claim_id)
    if c is None:
        raise errors.not_found("Claim not found.")
    if c["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("request-info is only allowed from UNDER_REVIEW.")
    c["status"] = "INFO_REQUESTED"
    db.touch(c)
    return object_response(serializers.reimbursement_claim(c), 200)


@bp.route("/reimbursement-claims/<claim_id>/resubmit", methods=["POST"])
def resubmit(claim_id):
    ident = authenticate()
    require_roles(ident, {"Member"})
    c = db.reimbursement_claims.get(claim_id)
    if c is None:
        raise errors.not_found("Claim not found.")
    if ident.user_id != c["member_id"]:
        raise errors.not_resource_owner("A member may only resubmit its own claim.")
    if c["status"] != "INFO_REQUESTED":
        raise errors.invalid_state("resubmit is only allowed from INFO_REQUESTED.")
    c["status"] = "SUBMITTED"
    db.touch(c)
    return object_response(serializers.reimbursement_claim(c), 200)


@bp.route("/reimbursement-claims/<claim_id>/approve", methods=["POST"])
def approve(claim_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    c = db.reimbursement_claims.get(claim_id)
    if c is None:
        raise errors.not_found("Claim not found.")
    if c["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("approve is only allowed from UNDER_REVIEW.")

    call = db.service_calls.get(c["service_call_id"])
    if call is None or call["status"] != "COMPLETED":
        raise errors.ApiError(errors.ERR_CALL_NOT_COMPLETED, 409,
                              "Linked call must be COMPLETED before approval.")

    payout = min(c["claimed_amount_cents"], call["member_out_of_pocket_cents"])
    c["approved_amount_cents"] = payout
    c["status"] = "APPROVED"
    db.touch(c)

    member = db.members.get(c["member_id"])
    if member is not None:
        member["outstanding_balance_cents"] -= payout
        db.touch(member)

    return object_response(serializers.reimbursement_claim(c), 200)


@bp.route("/reimbursement-claims/<claim_id>/reject", methods=["POST"])
def reject(claim_id):
    ident = authenticate()
    require_roles(ident, {"DispatchOperator"})
    c = db.reimbursement_claims.get(claim_id)
    if c is None:
        raise errors.not_found("Claim not found.")
    if c["status"] != "UNDER_REVIEW":
        raise errors.invalid_state("reject is only allowed from UNDER_REVIEW.")
    c["status"] = "REJECTED"
    db.touch(c)
    return object_response(serializers.reimbursement_claim(c), 200)
