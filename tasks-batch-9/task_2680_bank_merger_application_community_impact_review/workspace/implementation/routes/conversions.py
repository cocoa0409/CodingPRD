"""Systems conversion plans, customer disclosure and conversion (PRD 3.11)."""
from flask import Blueprint

import aggregates
import calc
from db import db, new_record, now_str, parse_dt, serialize, set_fields, whole_days_between
from errors import ApiError
from helpers import (
    conversion_conflicts_with_branch,
    ensure_application_filer,
    fetch,
    fetch_fk,
    list_and_respond,
    now,
    require_usd,
)
from middleware import (
    READ_ROLES_NO_COMMENTER,
    ROLE_FILER,
    get_body,
    present,
    req_dt,
    req_str,
    require_roles,
)
from response import object_response

conversions_bp = Blueprint("conversions", __name__)

CHANNELS = ("MAIL", "EMAIL", "IN_BRANCH_NOTICE", "ONLINE_BANKING")


def _plan_application(plan):
    application = db.applications.get(plan["application_id"])
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", "the plan's application is unknown")
    return application


@conversions_bp.post("/systems-conversion-plans")
@require_roles(ROLE_FILER)
def create_conversion_plan():
    body = get_body(required=True)
    application_id = req_str(body, "application_id")
    start_dt = req_dt(body, "conversion_start_date")
    end_dt = req_dt(body, "conversion_end_date")
    affected_customer_count = require_usd(body, "affected_customer_count", minimum=1)
    if end_dt < start_dt:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "conversion_end_date must be at or after conversion_start_date",
        )

    application = fetch_fk("applications", application_id)
    ensure_application_filer(application)

    for branch in db.branches.values():
        if (
            branch.get("designation_application_id") == application["id"]
            and branch["status"] == "DESIGNATED_FOR_CLOSURE"
            and conversion_conflicts_with_branch(branch, start_dt, end_dt)
        ):
            raise ApiError(
                "ERR_CONVERSION_BLACKOUT_CONFLICT",
                "the conversion window intersects a buffered branch-closure window",
            )
    for existing in db.conversion_plans.values():
        if existing["application_id"] == application["id"]:
            raise ApiError(
                "ERR_DUPLICATE_CONVERSION_PLAN",
                "a systems conversion plan already exists for this application",
            )

    record = new_record(
        {
            "application_id": application["id"],
            "conversion_start_date": body["conversion_start_date"],
            "conversion_end_date": body["conversion_end_date"],
            "affected_customer_count": affected_customer_count,
            "disclosure_channels": None,
            "customer_disclosure_sent_at": None,
            "disclosure_lead_days": None,
            "status": "DRAFT",
        }
    )
    db.conversion_plans[record["id"]] = record
    return object_response(serialize(record), 201)


@conversions_bp.get("/systems-conversion-plans/<record_id>")
@require_roles(*READ_ROLES_NO_COMMENTER)
def get_conversion_plan(record_id):
    return object_response(serialize(fetch("conversion_plans", record_id)))


@conversions_bp.get("/systems-conversion-plans")
@require_roles(*READ_ROLES_NO_COMMENTER)
def list_conversion_plans():
    return list_and_respond("conversion_plans", ("application_id", "status"))


@conversions_bp.post("/systems-conversion-plans/<record_id>/disclose")
@require_roles(ROLE_FILER)
def disclose_conversion_plan(record_id):
    plan = fetch("conversion_plans", record_id)
    body = get_body(required=True)
    if not present(body, "disclosure_channels"):
        raise ApiError("ERR_INVALID_REQUEST", "disclosure_channels is required")
    channels = body["disclosure_channels"]
    if not isinstance(channels, list) or not channels:
        raise ApiError("ERR_INVALID_REQUEST", "disclosure_channels must be a non-empty array")
    for channel in channels:
        if not isinstance(channel, str) or channel not in CHANNELS:
            raise ApiError(
                "ERR_INVALID_REQUEST", "disclosure_channels carries an undeclared channel"
            )

    application = _plan_application(plan)
    ensure_application_filer(application)
    if plan["status"] != "DRAFT":
        raise ApiError(
            "ERR_INVALID_CONVERSION_PLAN_STATE", "only a DRAFT plan can be disclosed"
        )

    sent_dt = now()
    start_dt = parse_dt(plan["conversion_start_date"])
    lead_days = whole_days_between(sent_dt, start_dt)
    if sent_dt >= start_dt or lead_days < calc.DISCLOSURE_MIN_LEAD_DAYS:
        raise ApiError(
            "ERR_DISCLOSURE_LEAD_INSUFFICIENT",
            "the disclosure lead time is %s days; %s are required"
            % (lead_days, calc.DISCLOSURE_MIN_LEAD_DAYS),
        )
    if "MAIL" not in channels:
        raise ApiError("ERR_CLOSURE_NOTICE_REQUIRED", "MAIL is a mandatory disclosure channel")

    set_fields(
        plan,
        status="DISCLOSED",
        disclosure_channels=list(channels),
        customer_disclosure_sent_at=now_str(),
        disclosure_lead_days=lead_days,
    )
    return object_response(serialize(plan))


@conversions_bp.post("/systems-conversion-plans/<record_id>/convert")
@require_roles(ROLE_FILER)
def convert_conversion_plan(record_id):
    plan = fetch("conversion_plans", record_id)
    get_body(required=False)
    application = _plan_application(plan)
    ensure_application_filer(application)

    if plan["status"] != "DISCLOSED":
        raise ApiError(
            "ERR_INVALID_CONVERSION_PLAN_STATE", "only a DISCLOSED plan can be converted"
        )
    decision = aggregates.application_decision(application["id"])
    if decision is None or decision["status"] != "CONSUMMATED":
        raise ApiError(
            "ERR_INVALID_DECISION_STATE", "the approval order must already be CONSUMMATED"
        )
    for condition in aggregates.decision_conditions(decision["id"]):
        if condition["condition_type"] == "SYSTEMS_CONVERSION" and condition[
            "status"
        ] != "SATISFIED":
            raise ApiError(
                "ERR_CONDITION_NOT_SATISFIED",
                "a systems-conversion condition is not SATISFIED",
            )

    set_fields(plan, status="CONVERTED")
    touched_markets = set()
    touched_institutions = set()
    for branch in db.branches.values():
        if (
            branch.get("designation_application_id") == application["id"]
            and branch["status"] == "DESIGNATED_FOR_CLOSURE"
        ):
            set_fields(branch, status="CLOSED")
            touched_markets.add(branch["market_id"])
            touched_institutions.add(branch["institution_id"])
    aggregates.recompute_market_ids(touched_markets)
    aggregates.recompute_institution_ids(touched_institutions)
    return object_response(serialize(plan))
