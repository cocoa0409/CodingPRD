"""Referrals: legal-aid dispatch and self-help signposting."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, now
from errors import (
    raise_err, invalid_request, not_found, invalid_state,
    ERR_STALE_VERSION, ERR_REFERRAL_TARGET_MISMATCH, ERR_CONSENT_REQUIRED,
    ERR_ORG_COVERAGE_MISMATCH, ERR_RESOURCE_OUTDATED, ERR_SLA_BREACHED,
    ERR_ORG_NOT_ACCEPTING, ERR_ORG_CAPACITY_FULL,
)
from middleware import require_roles
from response import ok_object, ok_list
from serializers import referral_out
from services import (
    make_record, bump, org_week_reserved, SLA_HOURS, OPEN_COUNSELING_STATES,
)
from util import (
    get_payload, check_unknown, require, as_str, as_int, as_enum, page_of,
    query_enum,
)

bp = Blueprint("referrals", __name__)

REFERRAL_TYPES = ("LEGAL_AID", "SELF_HELP")
REFERRAL_STATUSES = ("PROPOSED", "DISPATCHED", "ACCEPTED", "DECLINED", "EXPIRED", "CANCELLED")
REFERRAL_ROLES = ("Counselor", "HotlineSupervisor")


def _legal_aid_release_granted(caller_id):
    return any(
        c["caller_id"] == caller_id
        and c["consent_type"] == "LEGAL_AID_RELEASE"
        and c["status"] == "GRANTED"
        for c in store.consents.values()
    )


def _org_covers(org, case):
    jurisdiction = store.jurisdictions[case["jurisdiction_id"]]
    return (
        jurisdiction["code"] in org["covered_jurisdiction_codes"]
        and case["issue_category"] in org["accepted_categories"]
    )


@bp.route("/hotline/cases/<cid>/referrals", methods=["POST"])
def create_referral(cid):
    require_roles(*REFERRAL_ROLES)
    case = store.cases.get(cid)
    if case is None:
        not_found("case not found")
    data = get_payload()
    check_unknown(data, {"referral_type", "legal_aid_org_id", "self_help_resource_id", "expected_case_version"})
    referral_type = as_enum(require(data, "referral_type"), "referral_type", REFERRAL_TYPES)
    legal_aid_org_id = data.get("legal_aid_org_id")
    self_help_resource_id = data.get("self_help_resource_id")
    if legal_aid_org_id is not None:
        as_str(legal_aid_org_id, "legal_aid_org_id")
    if self_help_resource_id is not None:
        as_str(self_help_resource_id, "self_help_resource_id")
    expected = as_int(require(data, "expected_case_version"), "expected_case_version")
    # referral type/target coherence
    if referral_type == "LEGAL_AID":
        if legal_aid_org_id is None or self_help_resource_id is not None:
            raise_err(ERR_REFERRAL_TARGET_MISMATCH,
                      "LEGAL_AID requires legal_aid_org_id and forbids self_help_resource_id")
    else:
        if self_help_resource_id is None or legal_aid_org_id is not None:
            raise_err(ERR_REFERRAL_TARGET_MISMATCH,
                      "SELF_HELP requires self_help_resource_id and forbids legal_aid_org_id")
    org = None
    resource = None
    if legal_aid_org_id is not None:
        org = store.orgs.get(legal_aid_org_id)
        if org is None:
            invalid_request("legal_aid_org_id does not reference an existing org")
    if self_help_resource_id is not None:
        resource = store.resources.get(self_help_resource_id)
        if resource is None:
            invalid_request("self_help_resource_id does not reference an existing resource")
    if expected != case["version"]:
        raise_err(ERR_STALE_VERSION, "expected_case_version does not match the case's current version")
    if case["status"] not in OPEN_COUNSELING_STATES:
        invalid_state("referrals attach only to cases in an open counseling state")
    if referral_type == "LEGAL_AID":
        if not _legal_aid_release_granted(case["caller_id"]):
            raise_err(ERR_CONSENT_REQUIRED,
                      "caller lacks a GRANTED LEGAL_AID_RELEASE consent")
        if not _org_covers(org, case):
            raise_err(ERR_ORG_COVERAGE_MISMATCH,
                      "org does not cover the case's jurisdiction and category")
    else:
        if resource["status"] != "CURRENT":
            raise_err(ERR_RESOURCE_OUTDATED, "self-help resource is not CURRENT")
    rec = make_record({
        "case_id": cid,
        "referral_type": referral_type,
        "legal_aid_org_id": legal_aid_org_id,
        "self_help_resource_id": self_help_resource_id,
        "status": "PROPOSED",
        "sla_dispatch_by": now() + timedelta(hours=SLA_HOURS[case["urgency_tier"]]),
        "accept_by": None,
        "dispatched_at": None,
        "declined_org_ids": [],
        "cancel_reason": None,
    })
    store.referrals[rec["id"]] = rec
    bump(case)
    return ok_object(referral_out(rec), status=201)


@bp.route("/hotline/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    require_roles(*REFERRAL_ROLES)
    rec = store.referrals.get(rid)
    if rec is None:
        not_found("referral not found")
    return ok_object(referral_out(rec))


@bp.route("/hotline/referrals", methods=["GET"])
def list_referrals():
    require_roles(*REFERRAL_ROLES)
    case_id = request.args.get("case_id")
    org_id = request.args.get("legal_aid_org_id")
    resource_id = request.args.get("self_help_resource_id")
    status = query_enum("status", REFERRAL_STATUSES)
    recs = list(store.referrals.values())
    if case_id is not None:
        recs = [r for r in recs if r["case_id"] == case_id]
    if org_id is not None:
        recs = [r for r in recs if r["legal_aid_org_id"] == org_id]
    if resource_id is not None:
        recs = [r for r in recs if r["self_help_resource_id"] == resource_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total, limit, offset = page_of(recs)
    return ok_list([referral_out(r) for r in page], total, limit, offset)


@bp.route("/hotline/referrals/<rid>/state", methods=["POST"])
def transition_referral(rid):
    _, uid = require_roles(*REFERRAL_ROLES)
    rec = store.referrals.get(rid)
    if rec is None:
        not_found("referral not found")
    data = get_payload()
    check_unknown(data, {"to_status", "legal_aid_org_id"})
    to_status = as_enum(require(data, "to_status"), "to_status", REFERRAL_STATUSES)
    current = rec["status"]
    case = store.cases.get(rec["case_id"])

    if current == "PROPOSED" and to_status == "DISPATCHED":
        t = now()
        if t > rec["sla_dispatch_by"]:
            raise_err(ERR_SLA_BREACHED, "dispatch attempted after sla_dispatch_by")
        if rec["referral_type"] == "LEGAL_AID":
            org = store.orgs.get(rec["legal_aid_org_id"])
            if org is None or org["status"] != "ACTIVE":
                raise_err(ERR_ORG_NOT_ACCEPTING, "org is not accepting new referrals")
            if org_week_reserved(org["id"], at=t) >= org["weekly_capacity"]:
                raise_err(ERR_ORG_CAPACITY_FULL, "org weekly capacity is exhausted")
        rec["status"] = "DISPATCHED"
        rec["dispatched_at"] = t
        rec["accept_by"] = t + timedelta(hours=96)
        bump(rec)
        return ok_object(referral_out(rec))

    if current == "DISPATCHED" and to_status == "ACCEPTED":
        rec["status"] = "ACCEPTED"  # slot remains consumed
        bump(rec)
        return ok_object(referral_out(rec))

    if current == "DISPATCHED" and to_status == "DECLINED":
        rec["status"] = "DECLINED"  # releases the org slot (computed on read)
        if rec["referral_type"] == "LEGAL_AID" and rec["legal_aid_org_id"] is not None:
            rec["declined_org_ids"].append(rec["legal_aid_org_id"])
        bump(rec)
        return ok_object(referral_out(rec))

    if to_status == "PROPOSED" and current == "DECLINED":
        new_org_id = data.get("legal_aid_org_id")
        if new_org_id is None:
            invalid_request("legal_aid_org_id is required for re-route")
        as_str(new_org_id, "legal_aid_org_id")
        if new_org_id in rec["declined_org_ids"]:
            invalid_request("re-route org has already declined this referral")
        org = store.orgs.get(new_org_id)
        if org is None:
            invalid_request("legal_aid_org_id does not reference an existing org")
        if case is not None:
            if not _legal_aid_release_granted(case["caller_id"]):
                raise_err(ERR_CONSENT_REQUIRED,
                          "caller lacks a GRANTED LEGAL_AID_RELEASE consent")
            if not _org_covers(org, case):
                raise_err(ERR_ORG_COVERAGE_MISMATCH,
                          "org does not cover the case's jurisdiction and category")
            rec["sla_dispatch_by"] = now() + timedelta(hours=SLA_HOURS[case["urgency_tier"]])
        rec["legal_aid_org_id"] = new_org_id
        rec["dispatched_at"] = None
        rec["accept_by"] = None
        rec["status"] = "PROPOSED"
        bump(rec)
        return ok_object(referral_out(rec))

    if to_status == "CANCELLED" and current in ("PROPOSED", "DISPATCHED"):
        rec["status"] = "CANCELLED"  # DISPATCHED cancellation releases the slot
        rec["cancel_reason"] = "OPERATOR"
        bump(rec)
        return ok_object(referral_out(rec))

    invalid_state("referral transition %s -> %s is not allowed" % (current, to_status))
