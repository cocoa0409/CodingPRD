"""Community benefits plans and commitment line items (PRD 3.9)."""
from flask import Blueprint

import aggregates
import calc
from db import db, new_record, serialize, set_fields, touch
from errors import ApiError
from helpers import (
    check_application_version,
    ensure_application_filer,
    fetch,
    fetch_fk,
    list_and_respond,
    require_usd,
)
from middleware import (
    ALL_ROLES,
    ROLE_FILER,
    get_body,
    opt_enum,
    req_enum,
    req_int,
    req_str,
    require_roles,
)
from response import object_response

plans_bp = Blueprint("plans", __name__)

MEASUREMENT_BASES = ("CUMULATIVE_TO_DATE", "ANNUAL_PRO_RATA")
CATEGORIES = (
    "MORTGAGE_LENDING",
    "SMALL_BUSINESS_LENDING",
    "PHILANTHROPY",
    "BRANCH_RETENTION",
    "CDFI_INVESTMENT",
)


def _plan_application(plan):
    application = db.applications.get(plan["application_id"])
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", "the plan's application is unknown")
    return application


def recompute_plan_targets(plan):
    """Sum the individually floored annual targets (PRD 3.9)."""
    items = aggregates.plan_line_items(plan["id"])
    total_committed = sum(int(i["committed_usd"]) for i in items)
    annual_total = sum(int(i["annual_target_usd"]) for i in items)
    quarterly_total = calc.floor_div(annual_total, calc.QUARTERS_PER_YEAR)
    set_fields(
        plan,
        total_committed_usd=total_committed,
        annual_target_total_usd=annual_total,
        quarterly_target_total_usd=quarterly_total,
        remaining_commitment_usd=total_committed - int(plan["credited_to_date_usd"]),
    )


@plans_bp.post("/community-benefits-plans")
@require_roles(ROLE_FILER)
def create_plan():
    body = get_body(required=True)
    application_id = req_str(body, "application_id")
    expected_version = req_int(body, "expected_application_version", minimum=0)
    term_years = req_int(body, "term_years", minimum=1, maximum=10)
    measurement_basis = opt_enum(
        body, "measurement_basis", MEASUREMENT_BASES, default="CUMULATIVE_TO_DATE"
    )

    application = fetch_fk("applications", application_id)
    ensure_application_filer(application)
    check_application_version(application, expected_version)

    prior_proposed = None
    for plan in db.plans.values():
        if plan["application_id"] != application["id"]:
            continue
        if plan["status"] == "EXECUTED":
            raise ApiError(
                "ERR_INVALID_PLAN_STATE",
                "an EXECUTED plan already exists for this application",
            )
        if plan["status"] == "PROPOSED":
            prior_proposed = plan

    record = new_record(
        {
            "application_id": application["id"],
            "term_years": term_years,
            "measurement_basis": measurement_basis,
            "total_committed_usd": 0,
            "annual_target_total_usd": 0,
            "quarterly_target_total_usd": 0,
            "credited_to_date_usd": 0,
            "remaining_commitment_usd": 0,
            "compliance_status": "COMPLIANT",
            "consecutive_deficient_periods": 0,
            "filed_report_count": 0,
            "status": "PROPOSED",
        }
    )
    if prior_proposed is not None:
        set_fields(prior_proposed, status="SUPERSEDED")
    db.plans[record["id"]] = record
    touch(application)
    return object_response(serialize(record), 201)


@plans_bp.get("/community-benefits-plans/<record_id>")
@require_roles(*ALL_ROLES)
def get_plan(record_id):
    return object_response(serialize(fetch("plans", record_id)))


@plans_bp.get("/community-benefits-plans")
@require_roles(*ALL_ROLES)
def list_plans():
    return list_and_respond("plans", ("application_id", "status"))


@plans_bp.post("/commitment-line-items")
@require_roles(ROLE_FILER)
def create_line_item():
    body = get_body(required=True)
    plan_id = req_str(body, "plan_id")
    category = req_enum(body, "category", CATEGORIES)
    committed_usd = require_usd(body, "committed_usd", minimum=1)

    plan = fetch_fk("plans", plan_id)
    application = _plan_application(plan)
    ensure_application_filer(application)

    if plan["status"] != "PROPOSED":
        raise ApiError(
            "ERR_INVALID_PLAN_STATE", "line items may be added only to a PROPOSED plan"
        )
    for existing in aggregates.plan_line_items(plan["id"]):
        if existing["category"] == category:
            raise ApiError(
                "ERR_INVALID_REQUEST", "this plan already carries a %s line item" % category
            )

    annual, final_year = calc.line_item_targets(committed_usd, plan["term_years"])
    record = new_record(
        {
            "plan_id": plan["id"],
            "category": category,
            "committed_usd": committed_usd,
            "annual_target_usd": annual,
            "final_year_target_usd": final_year,
            "credited_usd": 0,
        }
    )
    db.line_items[record["id"]] = record
    recompute_plan_targets(plan)
    return object_response(serialize(record), 201)


@plans_bp.get("/commitment-line-items/<record_id>")
@require_roles(*ALL_ROLES)
def get_line_item(record_id):
    return object_response(serialize(fetch("line_items", record_id)))


@plans_bp.get("/commitment-line-items")
@require_roles(*ALL_ROLES)
def list_line_items():
    return list_and_respond("line_items", ("plan_id", "category"))


@plans_bp.post("/community-benefits-plans/<record_id>/execute")
@require_roles(ROLE_FILER)
def execute_plan(record_id):
    plan = fetch("plans", record_id)
    get_body(required=False)
    application = _plan_application(plan)
    ensure_application_filer(application)

    if plan["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_PLAN_STATE", "only a PROPOSED plan can be executed")
    if application["filing_status"] not in ("UNDER_REVIEW", "RECOMMENDED", "DECIDED"):
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "the application must be UNDER_REVIEW, RECOMMENDED or DECIDED",
        )
    items = aggregates.plan_line_items(plan["id"])
    total_committed = sum(int(i["committed_usd"]) for i in items)
    if not items or total_committed <= 0:
        raise ApiError(
            "ERR_EMPTY_BENEFITS_PLAN", "an executed plan needs at least one funded commitment"
        )

    annual_total = sum(int(i["annual_target_usd"]) for i in items)
    quarterly_total = calc.floor_div(annual_total, calc.QUARTERS_PER_YEAR)
    set_fields(
        plan,
        status="EXECUTED",
        total_committed_usd=total_committed,
        annual_target_total_usd=annual_total,
        quarterly_target_total_usd=quarterly_total,
        compliance_status="COMPLIANT",
        credited_to_date_usd=0,
        remaining_commitment_usd=total_committed,
    )
    return object_response(serialize(plan))
