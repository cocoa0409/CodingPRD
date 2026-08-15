"""ReinstatementRequest endpoints (PRD §3.7)."""

import clock
import db
import util
from datetime import date
from errors import (
    err_forbidden_for_role,
    err_invalid_request,
    err_invalid_state,
    err_policy_not_cancelled,
    err_reinstatement_limit_reached,
    err_reinstatement_window_closed,
    err_segregation_of_duties,
    err_stale_version,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from flask import Blueprint, request

bp = Blueprint("reinstatement_requests", __name__)

ALL_READERS = ("ComplianceOfficer", "Underwriter", "Policyholder")


@bp.post("/carrier/reinstatement-requests")
@require_roles("Underwriter", "Policyholder")
def create_request(_user_id, _role):
    body = util.get_body()
    util.check_fields(
        body, required=["policy_id", "cancellation_case_id", "expected_policy_version"]
    )
    policy_id = body["policy_id"]
    if not isinstance(policy_id, str):
        raise err_invalid_request("policy_id must be a string")
    cancellation_case_id = body["cancellation_case_id"]
    if not isinstance(cancellation_case_id, str):
        raise err_invalid_request("cancellation_case_id must be a string")
    expected_policy_version = util.require_int(body, "expected_policy_version")

    policy = util.resolve(db.policies, policy_id)
    case = util.resolve(db.cancellation_cases, cancellation_case_id)
    if case["policy_id"] != policy["id"]:
        raise err_invalid_request(
            "cancellation_case_id does not belong to the referenced policy"
        )

    # Policyholder ownership (§2.1).
    if _role == "Policyholder" and policy["policyholder_id"] != _user_id:
        raise err_forbidden_for_role()
    # Reinstatement exists only for CANCELLED policies (§3.7).
    if policy["status"] != "CANCELLED":
        raise err_policy_not_cancelled()
    # The named case must be the EFFECTIVE cancellation being reversed.
    if case["status"] != "EFFECTIVE":
        raise err_invalid_state(
            "cancellation_case_id must reference an EFFECTIVE cancellation"
        )

    profile = domain.policy_profile(policy)
    submitted_on = clock.today()
    cancel_date = date.fromisoformat(policy["cancellation_effective_date"])
    lapse_days = max(0, (submitted_on - cancel_date).days)

    # Eligibility FIRST, fee tier SECOND (SCAFFOLD §1.3 reinstatement_fee).
    if lapse_days > profile["reinstatement_window_days"]:
        raise err_reinstatement_window_closed()

    # OCC guard (tier 11 — last).
    if expected_policy_version != policy["version"]:
        raise err_stale_version()

    fee = domain.compute_reinstatement_fee(lapse_days)

    rec = util.stamp_new(
        {
            "policy_id": policy["id"],
            "cancellation_case_id": case["id"],
            "submitted_on_date": submitted_on.isoformat(),
            "lapse_days": lapse_days,
            "reinstatement_fee_cents": fee,
            "status": "SUBMITTED",
            "_created_by": _user_id,
        }
    )
    db.reinstatement_requests[rec["id"]] = rec
    # Submission bumps the policy's version (§1.5 side effect).
    util.touch(policy)
    return success_object(util.public(rec), 201)


@bp.get("/carrier/reinstatement-requests/<requestId>")
@require_roles(*ALL_READERS)
def get_request(requestId, _user_id, _role):
    rec = util.resolve(db.reinstatement_requests, requestId)
    return success_object(util.public(rec), 200)


@bp.get("/carrier/reinstatement-requests")
@require_roles(*ALL_READERS)
def list_requests(_user_id, _role):
    limit, offset = util.get_pagination()
    records = util.apply_filters(
        list(db.reinstatement_requests.values()),
        {
            "policy_id": request.args.get("policy_id"),
            "cancellation_case_id": request.args.get("cancellation_case_id"),
            "status": request.args.get("status"),
        },
    )
    records = util.sort_chronological(records)
    page = records[offset : offset + limit]
    return success_list([util.public(r) for r in page], limit, offset, len(records))


@bp.post("/carrier/reinstatement-requests/<requestId>/approve")
@require_roles("ComplianceOfficer")
def approve_request(requestId, _user_id, _role):
    rec = util.resolve(db.reinstatement_requests, requestId)
    if rec["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED reinstatement can be approved")
    if _user_id == rec["_created_by"]:
        raise err_segregation_of_duties()
    policy = db.policies[rec["policy_id"]]
    if policy["status"] != "CANCELLED":
        raise err_policy_not_cancelled()
    profile = domain.policy_profile(policy)
    if policy["reinstatements_used"] >= profile["max_reinstatements"]:
        raise err_reinstatement_limit_reached()

    rec["status"] = "APPROVED"
    util.touch(rec)

    policy["status"] = "ACTIVE"
    policy["reinstatements_used"] += 1
    policy["cancellation_effective_date"] = None
    util.touch(policy)

    domain.post_ledger_entry(
        policy["id"],
        "REINSTATEMENT_FEE",
        rec["reinstatement_fee_cents"],
        clock.today().isoformat(),
    )
    # Originating cancellation case deliberately stays EFFECTIVE (audit trail).
    return success_object(util.public(rec), 200)


@bp.post("/carrier/reinstatement-requests/<requestId>/deny")
@require_roles("ComplianceOfficer")
def deny_request(requestId, _user_id, _role):
    rec = util.resolve(db.reinstatement_requests, requestId)
    if rec["status"] != "SUBMITTED":
        raise err_invalid_state("Only a SUBMITTED reinstatement can be denied")
    rec["status"] = "DENIED"
    util.touch(rec)
    return success_object(util.public(rec), 200)
