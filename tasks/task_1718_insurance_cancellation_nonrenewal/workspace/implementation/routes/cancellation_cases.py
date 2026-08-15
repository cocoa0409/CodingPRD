"""CancellationCase endpoints (PRD §3.3-§3.5)."""

from datetime import timedelta

import clock
import db
import util
from errors import (
    err_already_effective,
    err_cancellation_already_open,
    err_effective_date_too_early,
    err_forbidden_for_role,
    err_ground_not_permitted,
    err_ground_role_mismatch,
    err_invalid_request,
    err_invalid_state,
    err_mailing_date_in_future,
    err_notice_period_shortfall,
    err_policy_not_active,
    err_segregation_of_duties,
    err_stale_version,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from flask import Blueprint, request

bp = Blueprint("cancellation_cases", __name__)

ALL_READERS = ("ComplianceOfficer", "Underwriter", "Policyholder")


def serialize_case(case):
    return util.public(case)


@bp.post("/carrier/cancellation-cases")
@require_roles("Underwriter", "Policyholder")
def create_case(_user_id, _role):
    body = util.get_body()
    util.check_fields(body, required=["policy_id", "ground_code", "expected_policy_version"])
    policy_id = body["policy_id"]
    if not isinstance(policy_id, str):
        raise err_invalid_request("policy_id must be a string")
    ground_code = util.require_enum(body, "ground_code", domain.ALL_GROUND_CODES)
    expected_policy_version = util.require_int(body, "expected_policy_version")

    policy = util.resolve(db.policies, policy_id)
    profile = domain.policy_profile(policy)

    # Ground/role pairing (ERR_GROUND_ROLE_MISMATCH 422).
    if ground_code == "INSURED_REQUEST" and _role != "Policyholder":
        raise err_ground_role_mismatch()
    if ground_code in domain.PERMISSIBLE_GROUND_CODES and _role != "Underwriter":
        raise err_ground_role_mismatch()
    # Policyholder ownership: a policyholder acts only on its own policies (§2.1).
    if _role == "Policyholder" and policy["policyholder_id"] != _user_id:
        raise err_forbidden_for_role()
    # Statutory ground permissibility (tier 6).
    if (
        ground_code in domain.PERMISSIBLE_GROUND_CODES
        and ground_code not in profile["permissible_grounds"]
    ):
        raise err_ground_not_permitted()
    # State admissibility on the policy.
    if policy["status"] != "ACTIVE":
        raise err_policy_not_active()
    # One open case per policy (tier 9).
    for existing in db.cancellation_cases.values():
        if (
            existing["policy_id"] == policy["id"]
            and existing["status"] in domain.OPEN_CASE_STATUSES
        ):
            raise err_cancellation_already_open()
    # OCC guard (tier 11 — last).
    if expected_policy_version != policy["version"]:
        raise err_stale_version()

    requested_on = clock.today()
    return_method = domain.resolve_return_method(profile, ground_code)
    earliest = domain.compute_earliest_effective_date(profile, policy, ground_code, requested_on)

    rec = util.stamp_new(
        {
            "policy_id": policy["id"],
            "ground_code": ground_code,
            "requested_by_role": _role,
            "requested_on_date": requested_on.isoformat(),
            "return_method": return_method,
            "earliest_effective_date": earliest.isoformat(),
            "scheduled_effective_date": None,
            "return_premium_cents": None,
            "status": "PENDING_APPROVAL",
            "rescinded_reason": "",
            "_created_by": _user_id,
        }
    )
    db.cancellation_cases[rec["id"]] = rec
    # Creation bumps the policy's version (§1.5 side effect).
    util.touch(policy)
    return success_object(serialize_case(rec), 201)


@bp.get("/carrier/cancellation-cases/<caseId>")
@require_roles(*ALL_READERS)
def get_case(caseId, _user_id, _role):
    rec = util.resolve(db.cancellation_cases, caseId)
    return success_object(serialize_case(rec), 200)


@bp.get("/carrier/cancellation-cases")
@require_roles(*ALL_READERS)
def list_cases(_user_id, _role):
    limit, offset = util.get_pagination()
    records = util.apply_filters(
        list(db.cancellation_cases.values()),
        {
            "policy_id": request.args.get("policy_id"),
            "status": request.args.get("status"),
        },
    )
    records = util.sort_chronological(records)
    page = records[offset : offset + limit]
    return success_list([serialize_case(r) for r in page], limit, offset, len(records))


@bp.post("/carrier/cancellation-cases/<caseId>/approve")
@require_roles("ComplianceOfficer")
def approve_case(caseId, _user_id, _role):
    rec = util.resolve(db.cancellation_cases, caseId)
    if rec["status"] != "PENDING_APPROVAL":
        raise err_invalid_state("Case is not PENDING_APPROVAL")
    if _user_id == rec["_created_by"]:
        raise err_segregation_of_duties()
    body = util.get_body()
    util.check_fields(body, required=["scheduled_effective_date"])
    scheduled = util.parse_date(body["scheduled_effective_date"], "scheduled_effective_date")
    earliest = util.parse_date(rec["earliest_effective_date"], "earliest_effective_date")
    if scheduled < earliest:
        raise err_effective_date_too_early()

    rec["scheduled_effective_date"] = body["scheduled_effective_date"]
    rec["status"] = "APPROVED"
    util.touch(rec)

    policy = db.policies[rec["policy_id"]]
    policy["status"] = "CANCEL_PENDING"
    util.touch(policy)
    return success_object(serialize_case(rec), 200)


@bp.post("/carrier/cancellation-cases/<caseId>/withdraw")
@require_roles("Underwriter", "Policyholder")
def withdraw_case(caseId, _user_id, _role):
    rec = util.resolve(db.cancellation_cases, caseId)
    if rec["status"] != "PENDING_APPROVAL":
        raise err_invalid_state("Only a PENDING_APPROVAL case can be withdrawn")
    if _role != rec["requested_by_role"]:
        raise err_forbidden_for_role(
            "Actor role does not match the case's requesting role on withdraw"
        )
    rec["status"] = "WITHDRAWN"
    util.touch(rec)
    return success_object(serialize_case(rec), 200)


@bp.post("/carrier/cancellation-cases/<caseId>/rescind")
@require_roles("ComplianceOfficer")
def rescind_case(caseId, _user_id, _role):
    rec = util.resolve(db.cancellation_cases, caseId)
    if rec["status"] not in ("APPROVED", "NOTICE_SENT"):
        raise err_invalid_state("Only an APPROVED or NOTICE_SENT case can be rescinded")
    if rec["status"] == "NOTICE_SENT":
        scheduled = util.parse_date(rec["scheduled_effective_date"], "scheduled_effective_date")
        if clock.today() >= scheduled:
            raise err_already_effective()
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
    return success_object(serialize_case(rec), 200)


@bp.post("/carrier/cancellation-cases/<caseId>/dispatch-notices")
@require_roles("Underwriter")
def dispatch_notices(caseId, _user_id, _role):
    rec = util.resolve(db.cancellation_cases, caseId)
    if rec["status"] != "APPROVED":
        raise err_invalid_state("Only an APPROVED case admits notice dispatch")
    body = util.get_body()
    util.check_fields(body, required=["notices"])
    policy = db.policies[rec["policy_id"]]
    profile = domain.policy_profile(policy)

    plan = domain.validate_notice_set(body["notices"], policy, "cancellation")
    base_days = domain.base_notice_days(profile, rec["ground_code"])
    scheduled = util.parse_date(rec["scheduled_effective_date"], "scheduled_effective_date")
    today = clock.today()

    for item in plan:
        required = (
            base_days
            if item["recipient_kind"] == "POLICYHOLDER"
            else profile["mortgagee_notice_days"]
        )
        item["required_days"] = required
        if item["mailed_on"] > today:
            raise err_mailing_date_in_future()
        if item["mailed_on"] + timedelta(days=required) > scheduled:
            raise err_notice_period_shortfall()

    created = []
    for item in plan:
        notice = util.stamp_new(
            {
                "cancellation_case_id": rec["id"],
                "nonrenewal_case_id": None,
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


@bp.get("/carrier/cancellation-cases/<caseId>/ledger-entries")
@require_roles(*ALL_READERS)
def list_case_ledger(caseId, _user_id, _role):
    rec = util.resolve(db.cancellation_cases, caseId)
    limit, offset = util.get_pagination()
    records = [
        e
        for e in db.ledger_entries.values()
        if e.get("cancellation_case_id") == rec["id"]
    ]
    records.sort(key=lambda e: (e["effective_date"], e["created_at"], e.get("_seq", 0)))
    page = records[offset : offset + limit]
    return success_list([util.public(r) for r in page], limit, offset, len(records))
