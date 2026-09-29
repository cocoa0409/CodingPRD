"""All 26 read endpoints (13 single-resource, 12 filtered lists) plus the
computed capital-adequacy read.  Every read is open to all seven roles."""
from flask import Blueprint, request

import calc
import db
import response
import serialize
import validation
from errors import err
from middleware import ALL_ROLES, authenticate
from routes.helpers import listing, must_get

bp = Blueprint("reads", __name__)


# ------------------------------------------------------------ single resources
@bp.get("/de-novo/organizing-groups/<group_id>")
def get_group(group_id):
    authenticate(ALL_ROLES)
    group = must_get("groups", group_id)
    # PRD 318: the supervision year is refreshed lazily against the clock when a
    # single group is read.  A read is not a mutation, so no version bump.
    calc.recompute_supervision(group)
    return response.object_response(serialize.group(group))


@bp.get("/de-novo/organizers/<organizer_id>")
def get_organizer(organizer_id):
    authenticate(ALL_ROLES)
    return response.object_response(serialize.organizer(must_get("organizers", organizer_id)))


@bp.get("/de-novo/business-plans/<plan_id>")
def get_plan(plan_id):
    authenticate(ALL_ROLES)
    return response.object_response(serialize.plan(must_get("plans", plan_id)))


@bp.get("/de-novo/stress-scenarios/<scenario_id>")
def get_scenario(scenario_id):
    authenticate(ALL_ROLES)
    return response.object_response(serialize.scenario(must_get("scenarios", scenario_id)))


@bp.get("/de-novo/capital-raises/<raise_id>")
def get_raise(raise_id):
    authenticate(ALL_ROLES)
    return response.object_response(serialize.capital_raise(must_get("raises", raise_id)))


@bp.get("/de-novo/subscriptions/<subscription_id>")
def get_subscription(subscription_id):
    authenticate(ALL_ROLES)
    return response.object_response(
        serialize.subscription(must_get("subscriptions", subscription_id)))


@bp.get("/de-novo/regulatory-filings/<filing_id>")
def get_filing(filing_id):
    authenticate(ALL_ROLES)
    return response.object_response(serialize.filing(must_get("filings", filing_id)))


@bp.get("/de-novo/approval-conditions/<condition_id>")
def get_condition(condition_id):
    authenticate(ALL_ROLES)
    return response.object_response(serialize.condition(must_get("conditions", condition_id)))


@bp.get("/de-novo/policy-documents/<policy_id>")
def get_policy(policy_id):
    authenticate(ALL_ROLES)
    return response.object_response(serialize.policy(must_get("policies", policy_id)))


@bp.get("/de-novo/vendor-contracts/<contract_id>")
def get_contract(contract_id):
    authenticate(ALL_ROLES)
    return response.object_response(serialize.contract(must_get("contracts", contract_id)))


@bp.get("/de-novo/conversion-windows/<window_id>")
def get_window(window_id):
    authenticate(ALL_ROLES)
    return response.object_response(serialize.window(must_get("windows", window_id)))


@bp.get("/de-novo/readiness-exams/<exam_id>")
def get_exam(exam_id):
    authenticate(ALL_ROLES)
    return response.object_response(serialize.exam(must_get("exams", exam_id)))


@bp.get("/de-novo/deviation-requests/<deviation_id>")
def get_deviation(deviation_id):
    authenticate(ALL_ROLES)
    return response.object_response(serialize.deviation(must_get("deviations", deviation_id)))


# ---------------------------------------------------------------- filtered lists
@bp.get("/de-novo/organizers")
def list_organizers():
    authenticate(ALL_ROLES)
    return listing("organizers", serialize.organizer, (
        ("group_id", validation.str_filter("group_id")),
        ("role_on_board", validation.str_filter("role_on_board")),
        ("qualification_status", validation.str_filter("qualification_status")),
        ("is_independent", validation.bool_filter("is_independent")),
    ))


@bp.get("/de-novo/business-plans")
def list_plans():
    authenticate(ALL_ROLES)
    return listing("plans", serialize.plan, (
        ("group_id", validation.str_filter("group_id")),
        ("supersedes_plan_id", validation.str_filter("supersedes_plan_id")),
        ("status", validation.str_filter("status")),
    ))


@bp.get("/de-novo/stress-scenarios")
def list_scenarios():
    authenticate(ALL_ROLES)
    return listing("scenarios", serialize.scenario, (
        ("business_plan_id", validation.str_filter("business_plan_id")),
        ("scenario_code", validation.str_filter("scenario_code")),
        ("governing_variant", validation.str_filter("governing_variant")),
    ))


@bp.get("/de-novo/capital-raises")
def list_raises():
    authenticate(ALL_ROLES)
    return listing("raises", serialize.capital_raise, (
        ("group_id", validation.str_filter("group_id")),
        ("status", validation.str_filter("status")),
    ))


@bp.get("/de-novo/subscriptions")
def list_subscriptions():
    authenticate(ALL_ROLES)
    return listing("subscriptions", serialize.subscription, (
        ("capital_raise_id", validation.str_filter("capital_raise_id")),
        ("organizer_id", validation.str_filter("organizer_id")),
        ("funding_state", validation.str_filter("funding_state")),
        ("clearance_state", validation.str_filter("clearance_state")),
        ("counts_toward_escrow", validation.bool_filter("counts_toward_escrow")),
    ))


@bp.get("/de-novo/regulatory-filings")
def list_filings():
    authenticate(ALL_ROLES)
    return listing("filings", serialize.filing, (
        ("group_id", validation.str_filter("group_id")),
        ("pinned_business_plan_id", validation.str_filter("pinned_business_plan_id")),
        ("authority", validation.str_filter("authority")),
        ("status", validation.str_filter("status")),
    ))


@bp.get("/de-novo/approval-conditions")
def list_conditions():
    authenticate(ALL_ROLES)
    return listing("conditions", serialize.condition, (
        ("filing_id", validation.str_filter("filing_id")),
        ("category", validation.str_filter("category")),
        ("status", validation.str_filter("status")),
        ("is_pre_opening_blocking", validation.bool_filter("is_pre_opening_blocking")),
    ))


@bp.get("/de-novo/policy-documents")
def list_policies():
    authenticate(ALL_ROLES)
    return listing("policies", serialize.policy, (
        ("group_id", validation.str_filter("group_id")),
        ("drafted_by_organizer_id", validation.str_filter("drafted_by_organizer_id")),
        ("adopted_by_organizer_id", validation.str_filter("adopted_by_organizer_id")),
        ("domain", validation.str_filter("domain")),
        ("status", validation.str_filter("status")),
    ))


@bp.get("/de-novo/vendor-contracts")
def list_contracts():
    authenticate(ALL_ROLES)
    return listing("contracts", serialize.contract, (
        ("group_id", validation.str_filter("group_id")),
        ("service_domain", validation.str_filter("service_domain")),
        ("criticality", validation.str_filter("criticality")),
        ("status", validation.str_filter("status")),
    ))


@bp.get("/de-novo/conversion-windows")
def list_windows():
    authenticate(ALL_ROLES)
    return listing("windows", serialize.window, (
        ("vendor_contract_id", validation.str_filter("vendor_contract_id")),
        ("status", validation.str_filter("status")),
    ))


@bp.get("/de-novo/readiness-exams")
def list_exams():
    authenticate(ALL_ROLES)
    return listing("exams", serialize.exam, (
        ("group_id", validation.str_filter("group_id")),
        ("exam_scope", validation.str_filter("exam_scope")),
        ("status", validation.str_filter("status")),
    ))


@bp.get("/de-novo/deviation-requests")
def list_deviations():
    authenticate(ALL_ROLES)
    return listing("deviations", serialize.deviation, (
        ("group_id", validation.str_filter("group_id")),
        ("baseline_plan_id", validation.str_filter("baseline_plan_id")),
        ("metric", validation.str_filter("metric")),
        ("status", validation.str_filter("status")),
        ("requires_regulator_approval",
         validation.bool_filter("requires_regulator_approval")),
    ))


# --------------------------------------------------------------- computed read
@bp.get("/de-novo/organizing-groups/<group_id>/capital-adequacy")
def capital_adequacy(group_id):
    authenticate(ALL_ROLES)
    group = must_get("groups", group_id)
    requested = request.args.get("business_plan_id")
    if requested:
        plan = db.get("plans", requested)
        if plan is None or plan["group_id"] != group["id"]:
            raise err("ERR_BUSINESS_PLAN_NOT_FOUND")
    else:
        plan = calc.governing_plan(group)
        if plan is None:
            raise err("ERR_BUSINESS_PLAN_NOT_FOUND")
    return response.object_response(calc.capital_adequacy_verdict(group, plan))
