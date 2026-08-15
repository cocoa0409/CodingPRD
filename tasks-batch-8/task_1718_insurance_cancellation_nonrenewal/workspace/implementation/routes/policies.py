"""Policy, InsuredInterest and policy-ledger endpoints (PRD §3.2, §2.9)."""

import db
import util
from errors import err_duplicate_policy_number, err_invalid_request
from middleware import require_roles
from response import success_list, success_object
from services import domain
from flask import Blueprint, request

bp = Blueprint("policies", __name__)

ALL_READERS = ("ComplianceOfficer", "Underwriter", "Policyholder")


@bp.post("/carrier/policies")
@require_roles("Underwriter")
def create_policy(_user_id, _role):
    body = util.get_body()
    util.check_fields(
        body,
        required=[
            "policyholder_id",
            "state_profile_id",
            "policy_number",
            "term_start_date",
            "term_end_date",
            "total_premium_cents",
        ],
    )
    policyholder_id = body["policyholder_id"]
    if not isinstance(policyholder_id, str) or policyholder_id not in db.policyholders:
        raise err_invalid_request("policyholder_id does not reference an existing policyholder")
    state_profile_id = body["state_profile_id"]
    if not isinstance(state_profile_id, str) or state_profile_id not in db.state_profiles:
        raise err_invalid_request("state_profile_id does not reference an existing profile")
    profile = db.state_profiles[state_profile_id]
    if profile["status"] != "ACTIVE":
        raise err_invalid_request("state_profile_id must reference an ACTIVE profile")
    policy_number = util.require_str(body, "policy_number")
    term_start = util.parse_date(body["term_start_date"], "term_start_date")
    term_end = util.parse_date(body["term_end_date"], "term_end_date")
    if term_end <= term_start:
        raise err_invalid_request("term_end_date must be strictly after term_start_date")
    total_premium_cents = util.require_int(body, "total_premium_cents")
    if total_premium_cents <= 0:
        raise err_invalid_request("total_premium_cents must be > 0")
    for existing in db.policies.values():
        if existing["policy_number"] == policy_number:
            raise err_duplicate_policy_number()

    rec = util.stamp_new(
        {
            "policyholder_id": policyholder_id,
            "state_profile_id": state_profile_id,
            "policy_number": policy_number,
            "status": "ACTIVE",
            "term_start_date": body["term_start_date"],
            "term_end_date": body["term_end_date"],
            "total_premium_cents": total_premium_cents,
            "cancellation_effective_date": None,
            "reinstatements_used": 0,
            "lapse_flag": False,
        }
    )
    db.policies[rec["id"]] = rec
    domain.post_ledger_entry(rec["id"], "WRITTEN", total_premium_cents, body["term_start_date"])
    return success_object(util.public(rec), 201)


@bp.get("/carrier/policies/<policyId>")
@require_roles(*ALL_READERS)
def get_policy(policyId, _user_id, _role):
    rec = util.resolve(db.policies, policyId)
    return success_object(util.public(rec), 200)


@bp.get("/carrier/policies")
@require_roles(*ALL_READERS)
def list_policies(_user_id, _role):
    limit, offset = util.get_pagination()
    records = util.apply_filters(
        list(db.policies.values()),
        {
            "policyholder_id": request.args.get("policyholder_id"),
            "state_profile_id": request.args.get("state_profile_id"),
            "status": request.args.get("status"),
        },
    )
    records = util.sort_chronological(records)
    page = records[offset : offset + limit]
    return success_list([util.public(r) for r in page], limit, offset, len(records))


@bp.post("/carrier/policies/<policyId>/interests")
@require_roles("Underwriter")
def create_interest(policyId, _user_id, _role):
    policy = util.resolve(db.policies, policyId)
    body = util.get_body()
    util.check_fields(
        body,
        required=["interest_type", "institution_name", "mailing_address"],
        optional=["loan_number"],
    )
    interest_type = util.require_enum(body, "interest_type", domain.INTEREST_TYPES)
    institution_name = util.require_str(body, "institution_name")
    mailing_address = util.require_str(body, "mailing_address")
    loan_number = body.get("loan_number", "")
    if not isinstance(loan_number, str):
        raise err_invalid_request("loan_number must be a string")

    rec = util.stamp_new(
        {
            "policy_id": policy["id"],
            "interest_type": interest_type,
            "institution_name": institution_name,
            "mailing_address": mailing_address,
            "loan_number": loan_number,
        }
    )
    db.insured_interests[rec["id"]] = rec
    return success_object(util.public(rec), 201)


@bp.get("/carrier/policies/<policyId>/interests")
@require_roles(*ALL_READERS)
def list_interests(policyId, _user_id, _role):
    policy = util.resolve(db.policies, policyId)
    limit, offset = util.get_pagination()
    records = domain.policy_interests(policy["id"])
    page = records[offset : offset + limit]
    return success_list([util.public(r) for r in page], limit, offset, len(records))


@bp.get("/carrier/policies/<policyId>/ledger-entries")
@require_roles(*ALL_READERS)
def list_policy_ledger(policyId, _user_id, _role):
    policy = util.resolve(db.policies, policyId)
    limit, offset = util.get_pagination()
    records = [e for e in db.ledger_entries.values() if e["policy_id"] == policy["id"]]
    # Chronological by effective_date, ties broken by created_at (PRD §2.9).
    records.sort(key=lambda e: (e["effective_date"], e["created_at"], e.get("_seq", 0)))
    page = records[offset : offset + limit]
    return success_list([util.public(r) for r in page], limit, offset, len(records))
