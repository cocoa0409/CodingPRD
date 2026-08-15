"""Retention policies and purge jobs (DataProtectionOfficer domain)."""

from datetime import timedelta

from flask import Blueprint, request

from db import store, now
from errors import (
    raise_err, invalid_request, not_found, invalid_state,
    ERR_RETENTION_NOT_EXPIRED,
)
from middleware import require_roles
from response import ok_object, ok_list
from serializers import policy_out, purge_job_out
from services import (
    make_record, bump, expire_consent, retention_anchor, applicable_policy,
    ISSUE_CATEGORIES,
)
from util import (
    get_payload, check_unknown, require, as_str, as_int, as_enum, page_of,
    query_enum,
)

bp = Blueprint("privacy", __name__)

POLICY_STATUSES = ("ACTIVE", "INACTIVE")
PURGE_STATUSES = ("PENDING", "EXECUTED", "BLOCKED_BY_HOLD")


# ---------------------------------------------------------------------------
# RetentionPolicy
# ---------------------------------------------------------------------------

@bp.route("/hotline/retention-policies", methods=["POST"])
def create_policy():
    require_roles("DataProtectionOfficer")
    data = get_payload()
    check_unknown(data, {"jurisdiction_id", "issue_category", "retention_days"})
    jurisdiction_id = data.get("jurisdiction_id")
    if jurisdiction_id is not None:
        as_str(jurisdiction_id, "jurisdiction_id")
        if jurisdiction_id not in store.jurisdictions:
            invalid_request("jurisdiction_id does not reference an existing jurisdiction")
    issue_category = data.get("issue_category")
    if issue_category is not None:
        as_enum(issue_category, "issue_category", ISSUE_CATEGORIES)
    retention_days = as_int(require(data, "retention_days"), "retention_days")
    if retention_days < 0:
        invalid_request("retention_days must be >= 0")
    # an ACTIVE policy for an occupied pair auto-deactivates the prior one
    for p in store.policies.values():
        if (
            p["status"] == "ACTIVE"
            and p["jurisdiction_id"] == jurisdiction_id
            and p["issue_category"] == issue_category
        ):
            p["status"] = "INACTIVE"
            bump(p)
    rec = make_record({
        "jurisdiction_id": jurisdiction_id,
        "issue_category": issue_category,
        "retention_days": retention_days,
        "status": "ACTIVE",
    })
    store.policies[rec["id"]] = rec
    return ok_object(policy_out(rec), status=201)


@bp.route("/hotline/retention-policies/<pid>", methods=["GET"])
def get_policy(pid):
    require_roles("DataProtectionOfficer", "HotlineSupervisor", "AgencyAdmin")
    rec = store.policies.get(pid)
    if rec is None:
        not_found("retention policy not found")
    return ok_object(policy_out(rec))


@bp.route("/hotline/retention-policies", methods=["GET"])
def list_policies():
    require_roles("DataProtectionOfficer", "HotlineSupervisor", "AgencyAdmin")
    jurisdiction_id = request.args.get("jurisdiction_id")
    issue_category = query_enum("issue_category", ISSUE_CATEGORIES)
    status = query_enum("status", POLICY_STATUSES)
    recs = list(store.policies.values())
    if jurisdiction_id is not None:
        recs = [r for r in recs if r["jurisdiction_id"] == jurisdiction_id]
    if issue_category is not None:
        recs = [r for r in recs if r["issue_category"] == issue_category]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total, limit, offset = page_of(recs)
    return ok_list([policy_out(r) for r in page], total, limit, offset)


# ---------------------------------------------------------------------------
# PurgeJob
# ---------------------------------------------------------------------------

@bp.route("/hotline/purge-jobs/<pid>", methods=["GET"])
def get_purge_job(pid):
    require_roles("DataProtectionOfficer", "HotlineSupervisor")
    rec = store.purge_jobs.get(pid)
    if rec is None:
        not_found("purge job not found")
    return ok_object(purge_job_out(rec))


@bp.route("/hotline/purge-jobs", methods=["GET"])
def list_purge_jobs():
    require_roles("DataProtectionOfficer", "HotlineSupervisor")
    caller_id = request.args.get("caller_id")
    status = query_enum("status", PURGE_STATUSES)
    recs = list(store.purge_jobs.values())
    if caller_id is not None:
        recs = [r for r in recs if r["caller_id"] == caller_id]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total, limit, offset = page_of(recs)
    return ok_list([purge_job_out(r) for r in page], total, limit, offset)


@bp.route("/hotline/purge-jobs/<pid>/execute", methods=["POST"])
def execute_purge_job(pid):
    require_roles("DataProtectionOfficer")
    job = store.purge_jobs.get(pid)
    if job is None:
        not_found("purge job not found")
    if job["status"] not in ("PENDING", "BLOCKED_BY_HOLD"):
        invalid_state("purge job transition %s -> EXECUTED is not allowed" % job["status"])
    caller = store.callers.get(job["caller_id"])
    if caller is None:
        invalid_state("purge target caller no longer exists")

    # a legal hold blocks the purge rather than erroring
    hold = any(
        c["caller_id"] == caller["id"] and c["legal_hold"]
        for c in store.cases.values()
    )
    if hold:
        job["status"] = "BLOCKED_BY_HOLD"
        job["blocked_reason"] = "LEGAL_HOLD"
        bump(job)
        return ok_object(purge_job_out(job))

    # eligibility re-check: >= 1 CLOSED case, applicable policy, inclusive boundary
    anchor, anchor_case = retention_anchor(caller["id"])
    policy = None
    if anchor_case is not None:
        policy = applicable_policy(anchor_case["jurisdiction_id"], anchor_case["issue_category"])
    if anchor is None or policy is None or now() < anchor + timedelta(days=policy["retention_days"]):
        raise_err(ERR_RETENTION_NOT_EXPIRED, "caller is not yet retention-eligible")

    # scrub the caller
    caller["phone"] = None
    caller["alias"] = "purged"
    caller["pii_purged"] = True
    bump(caller)
    # remaining GRANTED consents expire with their normal expiry cascades
    for consent in sorted(store.consents.values(), key=lambda c: (c["created_at"], c["_seq"])):
        if consent["caller_id"] == caller["id"] and consent["status"] == "GRANTED":
            expire_consent(consent)
    job["status"] = "EXECUTED"
    job["executed_at"] = now()
    job["blocked_reason"] = None
    bump(job)
    return ok_object(purge_job_out(job))
