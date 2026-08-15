"""NonrenewalCase endpoints (PRD §3.6)."""

from datetime import timedelta

import clock
import db
import util
from errors import (
    err_invalid_request,
    err_invalid_state,
    err_nonrenewal_already_open,
    err_nonrenewal_content_incomplete,
    err_nonrenewal_deadline_passed,
    err_nonrenewal_notice_late,
    err_policy_not_active,
    err_segregation_of_duties,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from flask import Blueprint, request

bp = Blueprint("nonrenewal_cases", __name__)

ALL_READERS = ("ComplianceOfficer", "Underwriter", "Policyholder")


@bp.post("/carrier/nonrenewal-cases")
@require_roles("Underwriter")
def create_case(_user_id, _role):
    body = util.get_body()
    util.check_fields(
        body,
        required=["policy_id", "reason_code", "reason_text", "content_codes_present"],
    )
    policy_id = body["policy_id"]
    if not isinstance(policy_id, str):
        raise err_invalid_request("policy_id must be a string")
    reason_code = util.require_enum(body, "reason_code", domain.NONRENEWAL_REASON_CODES)
    reason_text = util.require_str(body, "reason_text")
    content_codes_present = util.require_str_list(
        body, "content_codes_present", domain.NONRENEWAL_CONTENT_CODES
    )

    policy = util.resolve(db.policies, policy_id)
    profile = domain.policy_profile(policy)

    if policy["status"] != "ACTIVE":
        raise err_policy_not_active()
    for existing in db.nonrenewal_cases.values():
        if (
            existing["policy_id"] == policy["id"]
            and existing["status"] in domain.OPEN_CASE_STATUSES
        ):
            raise err_nonrenewal_already_open()

    term_end = util.parse_date(policy["term_end_date"], "term_end_date")
    notice_deadline = term_end - timedelta(days=profile["nonrenewal_notice_days"])
    if clock.today() > notice_deadline:
        raise err_nonrenewal_deadline_passed()

    rec = util.stamp_new(
        {
            "policy_id": policy["id"],
            "reason_code": reason_code,
            "reason_text": reason_text,
            "content_codes_present": content_codes_present,
            "decided_on_date": None,
            "notice_deadline_date": notice_deadline.isoformat(),
            "status": "PENDING_APPROVAL",
            "rescinded_reason": "",
            "_created_by": _user_id,
        }
    )
    db.nonrenewal_cases[rec["id"]] = rec
    return success_object(util.public(rec), 201)


@bp.get("/carrier/nonrenewal-cases/<caseId>")
@require_roles(*ALL_READERS)
def get_case(caseId, _user_id, _role):
    rec = util.resolve(db.nonrenewal_cases, caseId)
    return success_object(util.public(rec), 200)


@bp.get("/carrier/nonrenewal-cases")
@require_roles(*ALL_READERS)
def list_cases(_user_id, _role):
    limit, offset = util.get_pagination()
    records = util.apply_filters(
        list(db.nonrenewal_cases.values()),
        {
            "policy_id": request.args.get("policy_id"),
            "status": request.args.get("status"),
        },
    )
    records = util.sort_chronological(records)
    page = records[offset : offset + limit]
    return success_list([util.public(r) for r in page], limit, offset, len(records))


@bp.post("/carrier/nonrenewal-cases/<caseId>/approve")
@require_roles("ComplianceOfficer")
def approve_case(caseId, _user_id, _role):
    rec = util.resolve(db.nonrenewal_cases, caseId)
    if rec["status"] != "PENDING_APPROVAL":
        raise err_invalid_state("Case is not PENDING_APPROVAL")
    if _user_id == rec["_created_by"]:
        raise err_segregation_of_duties()
    policy = db.policies[rec["policy_id"]]
    profile = domain.policy_profile(policy)
    required = set(profile["nonrenewal_content_codes"])
    present = set(rec["content_codes_present"])
    if not required.issubset(present):
        raise err_nonrenewal_content_incomplete()

    rec["status"] = "APPROVED"
    rec["decided_on_date"] = clock.today().isoformat()
    util.touch(rec)

    policy["status"] = "NONRENEWAL_PENDING"
    util.touch(policy)
    return success_object(util.public(rec), 200)


@bp.post("/carrier/nonrenewal-cases/<caseId>/rescind")
@require_roles("ComplianceOfficer")
def rescind_case(caseId, _user_id, _role):
    rec = util.resolve(db.nonrenewal_cases, caseId)
    if rec["status"] != "APPROVED":
        raise err_invalid_state("Only an APPROVED nonrenewal case can be rescinded")
    body = util.get_body()
    util.check_fields(body, required=["reason"])
    reason = util.require_str(body, "reason")

    rec["status"] = "RESCINDED"
    rec["rescinded_reason"] = reason
    util.touch(rec)

    policy = db.policies[rec["policy_id"]]
    policy["status"] = "ACTIVE"
    util.touch(policy)

    domain.bump_report(policy["state_profile_id"], clock.today().isoformat()[:7], "rescinded_count")
    return success_object(util.public(rec), 200)


@bp.post("/carrier/nonrenewal-cases/<caseId>/dispatch-notices")
@require_roles("Underwriter")
def dispatch_notices(caseId, _user_id, _role):
    rec = util.resolve(db.nonrenewal_cases, caseId)
    if rec["status"] != "APPROVED":
        raise err_invalid_state("Only an APPROVED case admits notice dispatch")
    body = util.get_body()
    util.check_fields(body, required=["notices"])
    policy = db.policies[rec["policy_id"]]

    plan = domain.validate_notice_set(body["notices"], policy, "nonrenewal")
    deadline = util.parse_date(rec["notice_deadline_date"], "notice_deadline_date")

    for item in plan:
        if item["mailed_on"] > deadline:
            raise err_nonrenewal_notice_late()

    created = []
    for item in plan:
        notice = util.stamp_new(
            {
                "cancellation_case_id": None,
                "nonrenewal_case_id": rec["id"],
                "recipient_kind": item["recipient_kind"],
                "insured_interest_id": item["insured_interest_id"],
                "mailed_on_date": item["mailed_on"].isoformat(),
                "tracking_code": item["tracking_code"],
                "status": "MAILED",
            }
        )
        db.notices[notice["id"]] = notice
        created.append(util.public(notice))

    rec["status"] = "NOTICE_SENT"
    util.touch(rec)

    limit, offset = util.get_pagination()
    page = created[offset : offset + limit]
    return success_list(page, limit, offset, len(created))
