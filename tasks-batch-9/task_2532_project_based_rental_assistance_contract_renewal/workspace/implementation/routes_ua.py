"""Utility allowance analyses and the recertification cascade (PRD 3.8)."""
from flask import Blueprint, g

from core import (
    ROLE_CA, ROLE_HFO, ROLE_OWNER, ROLE_PHA, bad_request, clock_date_str,
    create, fail, json_body, need_date, need_enum, need_int, need_number,
    need_str, opt_str, parse_date, respond_object, touch,
)
import calcs
from guards import (
    body_fk, deny_transition, endpoint, list_response, own_analysis,
    own_property, require_state, resolve,
)

bp = Blueprint("ua", __name__)

ALL_ROLES = (ROLE_OWNER, ROLE_CA, ROLE_HFO, ROLE_PHA)


@bp.post("/utility-allowance-analyses")
@endpoint(ROLE_OWNER)
def create_analysis():
    body = json_body()
    prop = body_fk(body, "property_id", "properties")
    if prop is not None:
        own_property(prop)
    need_str(body, "property_id")
    method = need_enum(body, "method", calcs.UA_METHODS)
    effective_date = need_date(body, "effective_date")
    rate_change = None
    estimate = None
    if method == "FACTOR_BASED":
        if body.get("engineering_estimate_cents") is not None:
            bad_request("engineering_estimate_cents is not accepted for a FACTOR_BASED analysis.")
        rate_change = need_number(body, "utility_rate_change_pct",
                                  minimum="-0.5", maximum="0.5")
    else:
        if body.get("utility_rate_change_pct") is not None:
            bad_request("utility_rate_change_pct is not accepted for an ENGINEERING_BASED analysis.")
        estimate = need_int(body, "engineering_estimate_cents", minimum=0)
    baseline = prop["current_utility_allowance_cents"]
    if baseline == 0:
        bad_request("The property's current utility allowance is zero, "
                    "which makes the change ratio undefined.")
    proposed, change_pct, requires_fo = calcs.utility_allowance_adjustment(
        method, baseline, rate_change, estimate)
    analysis = create("analyses", {
        "property_id": prop["id"],
        "method": method,
        "baseline_allowance_cents": baseline,
        "utility_rate_change_pct": rate_change,
        "engineering_estimate_cents": estimate,
        "proposed_allowance_cents": proposed,
        "change_pct": float(change_pct),
        "requires_field_office_approval": requires_fo,
        "effective_date": effective_date,
        "state": "DRAFT",
        "approver_user_id": None,
        "applied_on_date": None,
        "recertified_tenant_count": 0,
    })
    return respond_object(analysis, 201)


@bp.get("/utility-allowance-analyses/<analysis_id>")
@endpoint(*ALL_ROLES)
def read_analysis(analysis_id):
    return respond_object(resolve("analyses", analysis_id), 200)


@bp.post("/utility-allowance-analyses/<analysis_id>/submit")
@endpoint(ROLE_OWNER)
def submit_analysis(analysis_id):
    analysis = own_analysis(resolve("analyses", analysis_id))
    require_state(analysis, "state", "DRAFT", "REJECTED")
    for other in calcs.analyses_of_property(analysis["property_id"]):
        if other["id"] == analysis["id"]:
            continue
        if other["state"] in ("SUBMITTED", "APPROVED"):
            fail("ERR_UA_ANALYSIS_IN_FLIGHT",
                 "Another utility allowance analysis on this property is in flight.")
    analysis["state"] = "SUBMITTED"
    touch(analysis)
    return respond_object(analysis, 200)


@bp.post("/utility-allowance-analyses/<analysis_id>/decide")
@endpoint(ROLE_CA, ROLE_HFO)
def decide_analysis(analysis_id):
    analysis = resolve("analyses", analysis_id)
    body = json_body()
    decision = need_enum(body, "decision", ("ACCEPT", "REJECT"))
    opt_str(body, "reason")
    require_state(analysis, "state", "SUBMITTED")
    if analysis["requires_field_office_approval"] and g.role != ROLE_HFO:
        fail("ERR_UA_CHANGE_REQUIRES_FIELD_OFFICE",
             "A change beyond the field-office threshold may only be decided by HudFieldOffice.")
    analysis["state"] = "APPROVED" if decision == "ACCEPT" else "REJECTED"
    analysis["approver_user_id"] = g.user_id
    touch(analysis)
    return respond_object(analysis, 200)


@bp.post("/utility-allowance-analyses/<analysis_id>/apply")
@endpoint(ROLE_CA)
def apply_analysis(analysis_id):
    analysis = resolve("analyses", analysis_id)
    body = json_body()
    expected = need_int(body, "expected_property_version")
    prop = calcs.table("properties").get(analysis["property_id"])
    if prop is None or expected != prop["version"]:
        fail("ERR_STALE_PROPERTY_VERSION",
             "expected_property_version does not match the property's current version.")
    require_state(analysis, "state", "APPROVED")
    boundary = calcs.ua_coverage_boundary(prop)
    if boundary is not None and parse_date(analysis["effective_date"]) < boundary:
        fail("ERR_UA_INTERVAL_OVERLAP",
             "The twelve-month allowance coverage interval has not elapsed.")
    analysis["state"] = "APPLIED"
    analysis["applied_on_date"] = clock_date_str()
    prop["current_utility_allowance_cents"] = analysis["proposed_allowance_cents"]
    prop["last_applied_ua_effective_date"] = analysis["effective_date"]
    touch(prop)
    allowance = prop["current_utility_allowance_cents"]
    created = 0
    for household in calcs.households_of_property(prop["id"]):
        if household["status"] not in ("ACTIVE", "OPT_OUT_NOTICED", "EV_ISSUED"):
            continue
        previous = calcs.active_certification(household["id"])
        if previous is not None:
            previous["status"] = "SUPERSEDED"
            touch(previous)
        contract = calcs.contract_of_property(prop["id"])
        unit_rent = calcs.in_force_unit_rent(contract) if contract else 0
        money = calcs.tenant_rent_recalculation(household, allowance, unit_rent)
        create("certifications", {
            "tenant_id": household["id"],
            "cert_type": "UA_ADJUSTMENT",
            "effective_date": analysis["effective_date"],
            "utility_allowance_cents": allowance,
            "contract_rent_per_unit_cents": unit_rent,
            "gross_rent_cents": money["gross_rent_cents"],
            "ttp_cents": money["ttp_cents"],
            "tenant_rent_cents": money["tenant_rent_cents"],
            "utility_reimbursement_cents": money["utility_reimbursement_cents"],
            "hap_cents": money["hap_cents"],
            "status": "ACTIVE",
        })
        household["current_ttp_cents"] = money["ttp_cents"]
        household["current_hap_cents"] = money["hap_cents"]
        touch(household)
        created += 1
    analysis["recertified_tenant_count"] = created
    touch(analysis)
    for contract in calcs.contracts_of_property(prop["id"]):
        for submission in calcs.submissions_of_contract(contract["id"]):
            if submission["state"] != "DRAFT":
                continue
            total, included = calcs.monthly_voucher_hap_request(
                contract, submission["period_month"])
            submission["requested_hap_cents"] = total
            submission["included_certification_count"] = included
            touch(submission)
    return respond_object(analysis, 200)
