"""AppealCase endpoints (PRD §3.8)."""

import clock
import db
import util
from errors import (
    err_forbidden_for_role,
    err_invalid_request,
    err_invalid_state,
    err_segregation_of_duties,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from flask import Blueprint, request

bp = Blueprint("appeals", __name__)

ALL_READERS = ("ComplianceOfficer", "Underwriter", "Policyholder")


@bp.post("/carrier/appeals")
@require_roles("Policyholder", "Underwriter")
def create_appeal(_user_id, _role):
    body = util.get_body()
    util.check_fields(body, required=["cancellation_case_id", "filed_by", "grounds_text"])
    cancellation_case_id = body["cancellation_case_id"]
    if not isinstance(cancellation_case_id, str):
        raise err_invalid_request("cancellation_case_id must be a string")
    filed_by = util.require_enum(body, "filed_by", domain.APPEAL_FILED_BY)
    grounds_text = util.require_str(body, "grounds_text")

    # filed_by chooses the actor (§3.8): Policyholder files POLICYHOLDER,
    # Underwriter files on a mortgagee's behalf.
    if _role == "Policyholder" and filed_by != "POLICYHOLDER":
        raise err_forbidden_for_role()
    if _role == "Underwriter" and filed_by != "MORTGAGEE":
        raise err_forbidden_for_role()

    case = util.resolve(db.cancellation_cases, cancellation_case_id)
    if _role == "Policyholder":
        policy = db.policies[case["policy_id"]]
        if policy["policyholder_id"] != _user_id:
            raise err_forbidden_for_role()
    if case["status"] not in ("NOTICE_SENT", "EFFECTIVE"):
        raise err_invalid_state(
            "Appeals require the linked cancellation case to be NOTICE_SENT or EFFECTIVE"
        )

    rec = util.stamp_new(
        {
            "cancellation_case_id": case["id"],
            "policy_id": case["policy_id"],
            "filed_by": filed_by,
            "filed_on_date": clock.today().isoformat(),
            "grounds_text": grounds_text,
            "status": "FILED",
            "decided_on_date": None,
            "_filed_by_user": _user_id,
            "_accepted_by": None,
        }
    )
    db.appeals[rec["id"]] = rec
    return success_object(util.public(rec), 201)


@bp.get("/carrier/appeals/<appealId>")
@require_roles(*ALL_READERS)
def get_appeal(appealId, _user_id, _role):
    rec = util.resolve(db.appeals, appealId)
    return success_object(util.public(rec), 200)


@bp.get("/carrier/appeals")
@require_roles(*ALL_READERS)
def list_appeals(_user_id, _role):
    limit, offset = util.get_pagination()
    records = util.apply_filters(
        list(db.appeals.values()),
        {
            "cancellation_case_id": request.args.get("cancellation_case_id"),
            "policy_id": request.args.get("policy_id"),
            "status": request.args.get("status"),
        },
    )
    records = util.sort_chronological(records)
    page = records[offset : offset + limit]
    return success_list([util.public(r) for r in page], limit, offset, len(records))


@bp.post("/carrier/appeals/<appealId>/accept-for-review")
@require_roles("ComplianceOfficer")
def accept_for_review(appealId, _user_id, _role):
    rec = util.resolve(db.appeals, appealId)
    if rec["status"] != "FILED":
        raise err_invalid_state("Only a FILED appeal can be accepted for review")
    rec["status"] = "UNDER_REVIEW"
    rec["_accepted_by"] = _user_id
    util.touch(rec)
    return success_object(util.public(rec), 200)


@bp.post("/carrier/appeals/<appealId>/decide")
@require_roles("ComplianceOfficer")
def decide_appeal(appealId, _user_id, _role):
    rec = util.resolve(db.appeals, appealId)
    if rec["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Only an UNDER_REVIEW appeal can be decided")
    body = util.get_body()
    util.check_fields(body, required=["decision"])
    decision = util.require_enum(body, "decision", {"UPHELD", "OVERTURNED"})
    if _user_id == rec["_accepted_by"]:
        raise err_segregation_of_duties()

    rec["status"] = decision
    rec["decided_on_date"] = clock.today().isoformat()
    util.touch(rec)

    if decision == "OVERTURNED":
        case = db.cancellation_cases[rec["cancellation_case_id"]]
        if case["status"] == "EFFECTIVE":
            policy = db.policies[case["policy_id"]]
            original = domain.find_return_entry(case["id"])
            if original is not None:
                domain.post_ledger_entry(
                    policy["id"],
                    "RETURN_PRO_RATA",
                    -original["amount_cents"],
                    clock.today().isoformat(),
                    cancellation_case_id=case["id"],
                )
            case["status"] = "RESCINDED"
            util.touch(case)
            policy["status"] = "ACTIVE"
            policy["cancellation_effective_date"] = None
            util.touch(policy)
            domain.bump_report(
                policy["state_profile_id"], clock.today().isoformat()[:7], "rescinded_count"
            )
    return success_object(util.public(rec), 200)
