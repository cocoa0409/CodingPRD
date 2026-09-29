"""Warranty transfer to a subsequent buyer (PRD 3.5)."""

from flask import Blueprint

import calc
import db
import listing
import response
import store
import validators as v
from errors import err
from middleware import (ROLE_ADJUSTER, ROLE_COMPLIANCE, ROLE_HOMEOWNER,
                        ROLE_UNDERWRITER, endpoint)

bp = Blueprint("transfers", __name__)

OPEN_TRANSFER_STATES = ("REQUESTED", "NEEDS_DOCUMENTATION")
TRANSFER_READERS = (ROLE_UNDERWRITER, ROLE_COMPLIANCE, ROLE_ADJUSTER, ROLE_HOMEOWNER)


def _bad_transfer_state(transfer):
    return err("ERR_INVALID_TRANSFER_STATE",
               "transfer is in status '%s'" % transfer["status"])


@bp.post("/policies/<policy_id>/transfers")
@endpoint(ROLE_HOMEOWNER)
def request_transfer(policy_id, user_id, role):
    policy = store.get_policy(policy_id)
    if policy["current_owner_id"] != user_id:
        raise err("ERR_NOT_POLICY_OWNER",
                  "X-User-ID is not the current owner of this policy")
    body = v.body()
    raw_new_owner = body.get("new_owner_id")
    if isinstance(raw_new_owner, str):
        store.get_homeowner(raw_new_owner)
    new_owner_id = v.req_str(body, "new_owner_id")
    transfer_date = v.req_date(body, "transfer_date")
    documents_reference = v.opt_str(body, "documents_reference", non_blank=False)
    expected = v.req_int(body, "expected_policy_version")
    if expected != policy["version"]:
        raise err("ERR_STALE_POLICY_VERSION",
                  "expected_policy_version %d does not match version %d"
                  % (expected, policy["version"]))
    if policy["coverage_status"] != "ACTIVE":
        raise err("ERR_POLICY_NOT_ACTIVE",
                  "only an ACTIVE policy can be transferred")
    structural = store.base_structural_term(policy_id)
    date_str = v.fmt_date(transfer_date)
    if (structural is None or date_str < structural["start_date"]
            or date_str > structural["end_date"]):
        raise err("ERR_COVERAGE_TERM_ELAPSED",
                  "transfer_date falls outside the structural coverage term")
    if new_owner_id == policy["current_owner_id"]:
        raise err("ERR_TRANSFEREE_IS_CURRENT_OWNER",
                  "the transferee is already the current owner")

    prior_id = None
    open_row = db.transfers.get(policy["pending_transfer_id"]) \
        if policy["pending_transfer_id"] else None
    if open_row is not None and open_row["status"] in OPEN_TRANSFER_STATES:
        open_row["status"] = "SUPERSEDED"
        db.mark(open_row)
        prior_id = open_row["id"]
    row = {
        "policy_id": policy_id,
        "new_owner_id": new_owner_id,
        "prior_transfer_id": prior_id,
        "requested_by_owner_id": user_id,
        "transfer_date": date_str,
        "transfer_fee_cents": calc.transfer_fee(policy["transfer_count"]),
        "documents_reference": documents_reference,
        "decision_reason": None,
        "status": "REQUESTED",
    }
    db.stamp_create(row)
    db.transfers[row["id"]] = row
    policy["pending_transfer_id"] = row["id"]
    db.mark(policy)
    return response.object_response(db.public(row), 201)


@bp.post("/transfers/<transfer_id>/documentation-request")
@endpoint(ROLE_UNDERWRITER)
def request_documentation(transfer_id, user_id, role):
    transfer = store.get_transfer(transfer_id)
    v.req_str(v.body(), "reason")
    if transfer["status"] != "REQUESTED":
        raise _bad_transfer_state(transfer)
    transfer["status"] = "NEEDS_DOCUMENTATION"
    db.mark(transfer)
    return response.object_response(db.public(transfer))


@bp.post("/transfers/<transfer_id>/resubmission")
@endpoint(ROLE_HOMEOWNER)
def resubmit_transfer(transfer_id, user_id, role):
    transfer = store.get_transfer(transfer_id)
    if transfer["requested_by_owner_id"] != user_id:
        raise err("ERR_NOT_POLICY_OWNER",
                  "X-User-ID did not request this transfer")
    documents_reference = v.req_str(v.body(), "documents_reference")
    if transfer["status"] != "NEEDS_DOCUMENTATION":
        raise _bad_transfer_state(transfer)
    transfer["documents_reference"] = documents_reference
    transfer["status"] = "REQUESTED"
    db.mark(transfer)
    return response.object_response(db.public(transfer))


@bp.post("/transfers/<transfer_id>/decision")
@endpoint(ROLE_UNDERWRITER)
def decide_transfer(transfer_id, user_id, role):
    transfer = store.get_transfer(transfer_id)
    body = v.body()
    outcome = v.req_enum(body, "outcome", ("APPROVE", "REJECT"))
    reason = v.opt_str(body, "decision_reason", non_blank=False)
    if transfer["status"] != "REQUESTED":
        raise _bad_transfer_state(transfer)
    if outcome == "APPROVE" and transfer["documents_reference"] is None:
        raise err("ERR_MISSING_TRANSFER_DOCUMENTATION",
                  "an undocumented transfer request may not be approved")
    transfer["decision_reason"] = reason
    if outcome == "APPROVE":
        transfer["status"] = "APPROVED"
    else:
        transfer["status"] = "REJECTED"
        policy = db.policies.get(transfer["policy_id"])
        if policy is not None:
            policy["pending_transfer_id"] = None
            db.mark(policy)
    db.mark(transfer)
    return response.object_response(db.public(transfer))


@bp.post("/transfers/<transfer_id>/recording")
@endpoint(ROLE_UNDERWRITER)
def record_transfer(transfer_id, user_id, role):
    transfer = store.get_transfer(transfer_id)
    if transfer["status"] != "APPROVED":
        raise _bad_transfer_state(transfer)
    policy = db.policies.get(transfer["policy_id"])
    for claim in store.claims_of_policy(transfer["policy_id"]):
        if claim["status"] in ("MEDIATION", "ARBITRATION"):
            raise err("ERR_OPEN_DISPUTE_BLOCKS_TRANSFER",
                      "a claim on this policy is in dispute")
    transfer["status"] = "RECORDED"
    if policy is not None:
        policy["current_owner_id"] = transfer["new_owner_id"]
        policy["transfer_count"] += 1
        policy["pending_transfer_id"] = None
        db.mark(policy)
    db.mark(transfer)
    return response.object_response(db.public(transfer))


@bp.get("/transfers/<transfer_id>")
@endpoint(*TRANSFER_READERS)
def read_transfer(transfer_id, user_id, role):
    return response.object_response(db.public(store.get_transfer(transfer_id)))


@bp.get("/transfers")
@endpoint(*TRANSFER_READERS)
def list_transfers(user_id, role):
    rows = store.all_rows(db.transfers)
    rows = listing.eq_filter(rows, "policy_id")
    rows = listing.eq_filter(rows, "new_owner_id")
    rows = listing.eq_filter(rows, "prior_transfer_id")
    rows = listing.eq_filter(rows, "status")
    return response.paginate(rows)
