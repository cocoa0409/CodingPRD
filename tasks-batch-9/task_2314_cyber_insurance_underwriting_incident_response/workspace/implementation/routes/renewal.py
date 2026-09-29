"""Renewal conditions, remediation verification, renewal pricing and portfolio aggregation."""

from datetime import timedelta

from flask import Blueprint

import calc
import errors
import validate
from db import new_row, now_iso, round2, sorted_by_created, store, touch
from errors import ApiError, bad_request
from middleware import (INSURED, PORTFOLIO_ACTUARY, UNDERWRITER, endpoint, find_assessment,
                        find_policy, find_scenario, owner_of_assessment, owner_of_policy,
                        scope_guard, scoped_filter)
from response import created, listing, ok
from routes.common import apply_eq, filter_value

bp = Blueprint("renewal", __name__, url_prefix="/cyber")


# --------------------------------------------------------------------------
# renewal assessments
# --------------------------------------------------------------------------

@bp.route("/policies/<policy_id>/renewal-assessments", methods=["POST"])
@endpoint(roles=[UNDERWRITER])
def open_renewal_assessment(policy_id):
    policy = find_policy(policy_id)
    payload = validate.body()
    required = validate.req_array(payload, "required_control_keys", calc.CONTROL_KEYS,
                                  non_empty=False)
    due_raw, due_at = validate.opt_dt(payload, "remediation_due_at")

    if policy["lifecycle_status"] != "INFORCE":
        raise ApiError(errors.ERR_INVALID_POLICY_STATE, 409,
                       "a renewal assessment requires an INFORCE policy")
    window_opens = policy["_period_end"] - timedelta(days=calc.RENEWAL_WINDOW_DAYS)
    if store.clock < window_opens:
        raise ApiError(errors.ERR_RENEWAL_WINDOW_NOT_OPEN, 422,
                       "the renewal window opens %d days before period_end"
                       % calc.RENEWAL_WINDOW_DAYS)

    row = {
        "policy_id": policy["id"],
        "required_control_keys": sorted(required),
        "remediation_due_at": due_raw,
        "submitted_control_keys": [],
        "verified_control_keys": [],
        "verification_round": 0,
        "status": "CONDITIONS_ISSUED" if required else "CONDITIONS_MET",
        "loss_ratio": None,
        "premium_adjustment_pct": None,
        "renewal_premium_usd": None,
        "non_renewal_reason": None,
        "_remediation_due_at": due_at,
    }
    assessment = new_row(row)
    store.renewal_assessments[assessment["id"]] = assessment
    return created(assessment)


@bp.route("/renewal-assessments/<assessment_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY, INSURED])
def read_assessment(assessment_id):
    assessment = find_assessment(assessment_id)
    scope_guard(owner_of_assessment(assessment))
    return ok(assessment)


@bp.route("/renewal-assessments", methods=["GET"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY, INSURED])
def list_assessments():
    rows = list(store.renewal_assessments.values())
    rows = apply_eq(rows, "policy_id", filter_value("policy_id"))
    rows = apply_eq(rows, "status", filter_value("status", calc.ASSESSMENT_STATES))
    rows = scoped_filter(rows, owner_of_assessment)
    return listing(sorted_by_created(rows))


@bp.route("/renewal-assessments/<assessment_id>/submit-remediation", methods=["POST"])
@endpoint(roles=[INSURED, UNDERWRITER])
def submit_remediation(assessment_id):
    assessment = find_assessment(assessment_id)
    scope_guard(owner_of_assessment(assessment))
    payload = validate.body()
    submitted = validate.req_array(payload, "submitted_control_keys", calc.CONTROL_KEYS,
                                   non_empty=False)
    if assessment["status"] != "CONDITIONS_ISSUED":
        raise ApiError(errors.ERR_INVALID_ASSESSMENT_STATE, 409,
                       "remediation may only be submitted from CONDITIONS_ISSUED")
    required = assessment["required_control_keys"] or []
    for key in submitted:
        if key not in required:
            raise bad_request("%s is not among required_control_keys" % key)
    assessment["submitted_control_keys"] = sorted(submitted)
    assessment["status"] = "REMEDIATION_SUBMITTED"
    touch(assessment)
    return ok(assessment)


@bp.route("/renewal-assessments/<assessment_id>/verify-remediation", methods=["POST"])
@endpoint(roles=[UNDERWRITER])
def verify_remediation(assessment_id):
    assessment = find_assessment(assessment_id)
    payload = validate.body()
    verified = validate.req_array(payload, "verified_control_keys", calc.CONTROL_KEYS,
                                  non_empty=False)
    if assessment["status"] != "REMEDIATION_SUBMITTED":
        raise ApiError(errors.ERR_INVALID_ASSESSMENT_STATE, 409,
                       "verification requires the assessment in REMEDIATION_SUBMITTED")

    round_before = assessment["verification_round"]
    merged = sorted(set(assessment["verified_control_keys"] or []) | set(verified))
    assessment["verified_control_keys"] = merged
    assessment["verification_round"] = round_before + 1

    required = set(assessment["required_control_keys"] or [])
    if required.issubset(set(merged)):
        assessment["status"] = "CONDITIONS_MET"
    elif round_before < calc.MAX_VERIFICATION_ROUNDS:
        assessment["status"] = "CONDITIONS_ISSUED"
    else:
        assessment["status"] = "NON_RENEWED"
        assessment["non_renewal_reason"] = "CONDITIONS_NOT_MET"
        policy = store.policies.get(assessment["policy_id"])
        if policy is not None:
            policy["lifecycle_status"] = "NON_RENEWED"
            touch(policy)
    touch(assessment)
    return ok(assessment)


@bp.route("/renewal-assessments/<assessment_id>/issue-renewal-quote", methods=["POST"])
@endpoint(roles=[PORTFOLIO_ACTUARY])
def issue_renewal_quote(assessment_id):
    assessment = find_assessment(assessment_id)
    payload = validate.body()
    expected = validate.req_int(payload, "expected_policy_version", None, None)
    policy = store.policies[assessment["policy_id"]]
    if expected != policy["version"]:
        raise ApiError(errors.ERR_STALE_POLICY_VERSION, 412,
                       "expected_policy_version does not match the current version")
    if assessment["status"] != "CONDITIONS_MET":
        raise ApiError(errors.ERR_INVALID_ASSESSMENT_STATE, 409,
                       "a renewal quote requires the assessment in CONDITIONS_MET")
    if policy["lifecycle_status"] not in ("INFORCE", "EXPIRED"):
        raise ApiError(errors.ERR_INVALID_POLICY_STATE, 409,
                       "the policy under review is %s" % policy["lifecycle_status"])
    if policy["warranty_status"] != "COMPLIANT":
        raise ApiError(errors.ERR_MANDATORY_CONTROL_LAPSE, 422,
                       "the policy's warranty controls are lapsed")

    figures = calc.renewal_premium_adjustment(policy, assessment)
    assessment["loss_ratio"] = figures["loss_ratio"]
    assessment["renewal_premium_usd"] = figures["renewal_premium_usd"]
    assessment["premium_adjustment_pct"] = figures["premium_adjustment_pct"]
    assessment["status"] = "RENEWAL_QUOTED"
    touch(assessment)
    touch(policy)
    return ok(assessment)


# --------------------------------------------------------------------------
# systemic scenarios
# --------------------------------------------------------------------------

@bp.route("/systemic-scenarios", methods=["POST"])
@endpoint(roles=[PORTFOLIO_ACTUARY])
def create_scenario():
    payload = validate.body()
    row = new_row({
        "dependency_key": validate.req_enum(payload, "dependency_key",
                                            calc.NAMED_DEPENDENCY_KEYS),
        "assumed_outage_hours": validate.req_num(payload, "assumed_outage_hours", minimum=0,
                                                 exclusive_min=True, maximum=8760),
        "footprint_pct": validate.req_num(payload, "footprint_pct", minimum=0,
                                          exclusive_min=True, maximum=1),
        "portfolio_capacity_usd": round2(validate.req_num(
            payload, "portfolio_capacity_usd", minimum=0, exclusive_min=True, money=True)),
        "qualifying_definitions": validate.req_array(payload, "qualifying_definitions",
                                                     calc.DEPENDENT_BI_DEFINITIONS,
                                                     non_empty=True),
        "status": "DRAFT",
        "modeled_policy_count": 0,
        "modeled_gross_exposure_usd": None,
        "capacity_breached": False,
        "modeled_at": None,
    })
    store.systemic_scenarios[row["id"]] = row
    return created(row)


@bp.route("/systemic-scenarios/<scenario_id>", methods=["GET"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY])
def read_scenario(scenario_id):
    return ok(find_scenario(scenario_id))


@bp.route("/systemic-scenarios", methods=["GET"])
@endpoint(roles=[UNDERWRITER, PORTFOLIO_ACTUARY])
def list_scenarios():
    rows = list(store.systemic_scenarios.values())
    rows = apply_eq(rows, "dependency_key",
                    filter_value("dependency_key", calc.NAMED_DEPENDENCY_KEYS))
    rows = apply_eq(rows, "status", filter_value("status", calc.SCENARIO_STATES))
    return listing(sorted_by_created(rows))


@bp.route("/systemic-scenarios/<scenario_id>/model", methods=["POST"])
@endpoint(roles=[PORTFOLIO_ACTUARY])
def model_scenario(scenario_id):
    scenario = find_scenario(scenario_id)
    result = calc.systemic_aggregation_model(scenario)
    scenario["status"] = "MODELED"
    scenario["modeled_policy_count"] = result["modeled_policy_count"]
    scenario["modeled_gross_exposure_usd"] = result["modeled_gross_exposure_usd"]
    scenario["capacity_breached"] = result["capacity_breached"]
    scenario["modeled_at"] = now_iso()
    touch(scenario)
    if result["capacity_breached"]:
        for policy in result["included_policies"]:
            policy["aggregation_flagged"] = True
            touch(policy)
    return ok(scenario)
