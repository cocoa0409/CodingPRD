"""Disputes (PRD 3.8): OPEN -> UNDER_REVIEW -> UPHELD/OVERTURNED -> CLOSED.

Filing moves the call OPEN -> DISPUTED (expiry clock pauses). An UPHELD
decision returns the call DISPUTED -> OPEN with due_at unchanged; OVERTURNED
moves it DISPUTED -> WAIVED with cure_method WAIVER and a posture recheck.
The decided states are momentary: the dispute closes itself immediately.
"""
from flask import Blueprint, request

from authz import ANALYST, ANY_ROLE, CUSTOMER, SUPERVISOR, check_customer_ownership, require_roles
from cascades import posture_recheck
from db import store
from errors import (
    call_not_open,
    dispute_invalid_state,
    dispute_not_found,
    duplicate_dispute,
    segregation_of_duties,
)
from response import success
from serialize import ser_dispute
from store_ops import (
    json_body,
    new_id,
    paginate,
    req_enum,
    req_str,
    sorted_by_creation,
    stamp_new,
    touch,
)
from routes.accounts import get_account_or_404
from routes.calls import get_call_or_404

bp = Blueprint("disputes", __name__)


def get_dispute_or_404(dispute_id):
    dispute = store.disputes.get(dispute_id)
    if dispute is None:
        raise dispute_not_found()
    return dispute


@bp.route("/margin/disputes", methods=["POST"])
def create_dispute():
    data = json_body()
    call_id = req_str(data, "call_id")
    reason = req_str(data, "reason")
    uid, _ = require_roles([CUSTOMER])
    call = get_call_or_404(call_id)  # body reference resolves (PRD 2.9)
    account = store.accounts[call["account_id"]]
    check_customer_ownership(uid, account["customer_id"])
    # At most one in-flight (OPEN/UNDER_REVIEW) dispute per call: a second
    # filing against a call already carrying one fails ERR_DUPLICATE_DISPUTE
    # (a DISPUTED call always carries an in-flight dispute, so this check
    # precedes the call-state check).
    if any(d["call_id"] == call_id and d["dispute_status"] in ("OPEN", "UNDER_REVIEW")
           for d in store.disputes.values()):
        raise duplicate_dispute()
    # Filing is only possible while the call is OPEN.
    if call["call_status"] != "OPEN":
        raise call_not_open()

    dispute = {
        "id": new_id(),
        "account_id": account["id"],
        "call_id": call_id,
        "reason": reason,
        "dispute_status": "OPEN",
        "reviewed_by_user_id": None,
        "decided_by_user_id": None,
        "decision": None,
    }
    stamp_new(dispute)
    store.disputes[dispute["id"]] = dispute
    call["call_status"] = "DISPUTED"
    touch(call)
    return success(ser_dispute(dispute), status=201)


@bp.route("/margin/disputes/<did>", methods=["GET"])
def get_dispute(did):
    require_roles(ANY_ROLE)
    return success(ser_dispute(get_dispute_or_404(did)))


@bp.route("/margin/disputes", methods=["GET"])
def list_disputes():
    require_roles(ANY_ROLE)
    account_id = request.args.get("account_id")
    call_id = request.args.get("call_id")
    items = list(store.disputes.values())
    if account_id is not None:
        items = [d for d in items if d["account_id"] == account_id]
    if call_id is not None:
        items = [d for d in items if d["call_id"] == call_id]
    items = sorted_by_creation(items)
    page, pagination = paginate(items)
    return success([ser_dispute(d) for d in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/accounts/<aid>/disputes", methods=["GET"])
def list_account_disputes(aid):
    require_roles(ANY_ROLE)
    get_account_or_404(aid)
    items = sorted_by_creation(
        [d for d in store.disputes.values() if d["account_id"] == aid])
    page, pagination = paginate(items)
    return success([ser_dispute(d) for d in page], response_type="array",
                   pagination=pagination)


@bp.route("/margin/disputes/<did>/start-review", methods=["POST"])
def start_review(did):
    uid, _ = require_roles([ANALYST])
    dispute = get_dispute_or_404(did)
    if dispute["dispute_status"] != "OPEN":
        raise dispute_invalid_state()
    dispute["dispute_status"] = "UNDER_REVIEW"
    dispute["reviewed_by_user_id"] = uid
    touch(dispute)
    return success(ser_dispute(dispute))


@bp.route("/margin/disputes/<did>/request-info", methods=["POST"])
def request_info(did):
    require_roles([ANALYST])
    dispute = get_dispute_or_404(did)
    if dispute["dispute_status"] != "UNDER_REVIEW":
        raise dispute_invalid_state()
    # Cycle back to the customer; the review attribution resets.
    dispute["dispute_status"] = "OPEN"
    dispute["reviewed_by_user_id"] = None
    touch(dispute)
    return success(ser_dispute(dispute))


@bp.route("/margin/disputes/<did>/decide", methods=["POST"])
def decide_dispute(did):
    data = json_body()
    decision = req_enum(data, "decision", ("UPHELD", "OVERTURNED"))
    uid, _ = require_roles([SUPERVISOR])
    dispute = get_dispute_or_404(did)
    if dispute["dispute_status"] != "UNDER_REVIEW":
        raise dispute_invalid_state()
    if uid == dispute["reviewed_by_user_id"]:
        raise segregation_of_duties()
    dispute["decision"] = decision
    dispute["decided_by_user_id"] = uid
    # UPHELD/OVERTURNED are momentary: the dispute auto-transitions to CLOSED.
    dispute["dispute_status"] = "CLOSED"
    touch(dispute)

    call = store.calls[dispute["call_id"]]
    if decision == "UPHELD":
        # Call returns DISPUTED -> OPEN; due_at is NOT extended, so a clock
        # already past due lets the next daily sweep expire it.
        call["call_status"] = "OPEN"
        touch(call)
    else:
        # OVERTURNED: the call is waived outright, then posture recheck.
        call["call_status"] = "WAIVED"
        call["cure_method"] = "WAIVER"
        call["resolved_at"] = store.clock
        touch(call)
        posture_recheck(store.accounts[call["account_id"]])
    return success(ser_dispute(dispute))
