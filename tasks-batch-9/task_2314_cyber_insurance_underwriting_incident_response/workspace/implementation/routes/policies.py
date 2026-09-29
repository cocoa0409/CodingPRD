"""Policies, the coverage tower, warranty reporting, loss summary and cancellation."""

from flask import Blueprint

import calc
import validate
from cascades import cancel_policy_cascade
from db import sorted_by_created, store, touch
from errors import ApiError
import errors
from middleware import (CLAIMS_ADJUSTER, INSURED, PORTFOLIO_ACTUARY, UNDERWRITER,
                        endpoint, find_policy, find_section, guard_account_filter,
                        owner_of_policy, owner_of_section, scope_guard, scoped_filter)
from response import listing, ok
from routes.common import apply_eq, filter_value

bp = Blueprint("policies", __name__, url_prefix="/cyber")


def _by_priority(rows):
    return sorted(rows, key=lambda row: (row["erosion_priority"], row["created_at"], row["_seq"]))


@bp.route("/policies/<policy_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def read_policy(policy_id):
    policy = find_policy(policy_id)
    scope_guard(owner_of_policy(policy))
    return ok(policy)


@bp.route("/policies", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def list_policies():
    guard_account_filter("insured_account_id")
    rows = list(store.policies.values())
    rows = apply_eq(rows, "insured_account_id", filter_value("insured_account_id"))
    rows = apply_eq(rows, "application_id", filter_value("application_id"))
    rows = apply_eq(rows, "lifecycle_status", filter_value("lifecycle_status", calc.LIFECYCLE_STATES))
    rows = apply_eq(rows, "limit_status", filter_value("limit_status", calc.LIMIT_STATES))
    rows = apply_eq(rows, "warranty_status", filter_value("warranty_status", calc.WARRANTY_STATES))
    rows = scoped_filter(rows, owner_of_policy)
    return listing(sorted_by_created(rows))


@bp.route("/policies/<policy_id>/coverage-sections", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def list_policy_sections(policy_id):
    policy = find_policy(policy_id)
    scope_guard(owner_of_policy(policy))
    rows = calc.sections_of(policy["id"])
    rows = apply_eq(rows, "section_key", filter_value("section_key", calc.SECTION_KEYS))
    return listing(_by_priority(rows))


@bp.route("/coverage-sections/<section_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def read_section(section_id):
    section = find_section(section_id)
    scope_guard(owner_of_section(section))
    return ok(section)


@bp.route("/coverage-sections", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY])
def list_sections():
    rows = list(store.coverage_sections.values())
    rows = apply_eq(rows, "policy_id", filter_value("policy_id"))
    rows = apply_eq(rows, "section_key", filter_value("section_key", calc.SECTION_KEYS))
    return listing(_by_priority(rows))


@bp.route("/policies/<policy_id>/loss-summary", methods=["GET"])
@endpoint(roles=[UNDERWRITER, CLAIMS_ADJUSTER, PORTFOLIO_ACTUARY, INSURED])
def read_loss_summary(policy_id):
    policy = find_policy(policy_id)
    scope_guard(owner_of_policy(policy))
    summary = calc.policy_loss_summary(policy)
    summary["aggregate_limit_remaining_usd"] = policy["aggregate_limit_remaining_usd"]
    summary["limit_status"] = policy["limit_status"]
    return ok(summary)


@bp.route("/policies/<policy_id>/warranty-reports", methods=["POST"])
@endpoint(roles=[UNDERWRITER])
def record_warranty_report(policy_id):
    policy = find_policy(policy_id)
    payload = validate.body()
    lapsed = validate.req_array(payload, "lapsed_control_keys", calc.CONTROL_KEYS,
                                non_empty=False)
    policy["lapsed_warranty_control_keys"] = sorted(lapsed)
    policy["warranty_status"] = "LAPSED" if lapsed else "COMPLIANT"
    touch(policy)
    return ok(policy)


@bp.route("/policies/<policy_id>/cancel", methods=["POST"])
@endpoint(roles=[UNDERWRITER])
def cancel_policy(policy_id):
    policy = find_policy(policy_id)
    payload = validate.body()
    reason = validate.req_str(payload, "cancellation_reason", 1, None)
    if policy["lifecycle_status"] != "INFORCE":
        raise ApiError(errors.ERR_INVALID_POLICY_STATE, 409,
                       "only an INFORCE policy may be cancelled")
    cancel_policy_cascade(policy, reason)
    return ok(policy)
