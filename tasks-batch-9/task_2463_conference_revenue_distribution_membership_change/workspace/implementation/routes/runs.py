"""Distribution runs: reads, the reconciliation identity, posting and reversal."""

from flask import Blueprint

import response
import serializers
import validation
from db import db
from errors import ApiError
from middleware import api, current_user_id, raw_body
from routes import common
from services import distribution

bp = Blueprint("runs", __name__)

RUN_READ_ROLES = (
    "Commissioner",
    "FinanceOfficer",
    "Treasurer",
    "Auditor",
    "PlatformAdmin",
    "MemberRepresentative",
)

RECONCILIATION_ROLES = (
    "Commissioner",
    "FinanceOfficer",
    "Treasurer",
    "Auditor",
    "PlatformAdmin",
)

POSTABLE_POOL_STATUSES = ("OPEN", "BOOKS_CLOSED")


@bp.route("/distribution-runs/<run_id>", methods=["GET"])
@api(RUN_READ_ROLES)
def read_run(run_id):
    return response.single(serializers.distribution_run(common.get_run(run_id)))


@bp.route("/distribution-runs", methods=["GET"])
@api(RUN_READ_ROLES)
def list_runs():
    criteria = {
        "revenue_pool_id": common.string_filter("revenue_pool_id"),
        "superseded_by_run_id": common.string_filter("superseded_by_run_id"),
        "variant": common.string_filter("variant"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        list(db.distribution_runs.values()),
        serializers.distribution_run,
        criteria=criteria,
    )


@bp.route("/distribution-runs/<run_id>/lines", methods=["GET"])
@api(RUN_READ_ROLES)
def list_run_lines(run_id):
    common.get_run(run_id)
    # PRD section 3.7: a run's lines are listed in the members' created_at
    # ascending order, which run_lines already applies.
    lines = distribution.run_lines(run_id)
    criteria = {
        "member_id": common.string_filter("member_id"),
        "status": common.string_filter("status"),
    }
    return common.listing(
        lines, serializers.distribution_line, criteria=criteria, presorted=True
    )


@bp.route("/distribution-runs/<run_id>/reconciliation", methods=["GET"])
@api(RECONCILIATION_ROLES)
def read_run_reconciliation(run_id):
    run = common.get_run(run_id)
    return response.single(distribution.reconciliation(run))


@bp.route("/distribution-runs/<run_id>/post", methods=["POST"])
@api(("Treasurer",))
def post_distribution_run(run_id):
    run = common.get_run(run_id)
    pool = db.revenue_pools.get(run["revenue_pool_id"])

    if pool is None or pool["status"] not in POSTABLE_POOL_STATUSES:
        raise ApiError("ERR_POOL_STATE_INVALID")
    if run["status"] != "COMPUTED":
        raise ApiError("ERR_RUN_STATE_INVALID")
    if current_user_id() == run["computed_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if run["variant"] == "FINAL_AUDITED" and not _has_issued_report(run["id"]):
        raise ApiError("ERR_AUDIT_REPORT_NOT_ISSUED")

    distribution.post_run(run, pool, current_user_id())
    return response.single(serializers.distribution_run(run))


def _has_issued_report(run_id):
    for report in db.audit_reports.values():
        if report["distribution_run_id"] == run_id and report["status"] == "ISSUED":
            return True
    return False


@bp.route("/distribution-runs/<run_id>/reverse", methods=["POST"])
@api(("Treasurer",))
def reverse_distribution_run(run_id):
    run = common.get_run(run_id)
    pool = db.revenue_pools.get(run["revenue_pool_id"])
    body = raw_body()
    reason = validation.get_optional_str(body, "reason")

    if pool is None or pool["status"] == "CLOSED":
        raise ApiError("ERR_POOL_STATE_INVALID")
    if run["status"] != "POSTED":
        raise ApiError("ERR_RUN_STATE_INVALID")

    distribution.reverse_run(run, pool, reason)
    return response.single(serializers.distribution_run(run))
