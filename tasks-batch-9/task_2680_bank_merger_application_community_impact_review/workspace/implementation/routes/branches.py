"""Branches, designations and the designation cascades (PRD 3.1, 3.6)."""
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
    ALL_ROLES,
    ROLE_ANALYST,
    ROLE_FILER,
    actor_id,
    get_body,
    opt_enum,
    opt_str,
    req_enum,
    req_str,
    require_roles,
)
from response import object_response

branches_bp = Blueprint("branches", __name__)

SERVICE_TYPES = ("FULL_SERVICE", "LIMITED_SERVICE")
DESIGNATION_TYPES = ("DIVESTITURE", "CLOSURE")
BLOCKING_APPLICATION_STATES = ("CONSUMMATED", "DENIED")


@branches_bp.post("/branches")
@require_roles(ROLE_ANALYST)
def create_branch():
    body = get_body(required=True)
    institution_id = req_str(body, "institution_id")
    market_id = req_str(body, "market_id")
    branch_name = req_str(body, "branch_name", min_len=1)
    deposits_usd = require_usd(body, "deposits_usd", minimum=1)
    service_type = opt_enum(body, "service_type", SERVICE_TYPES, default="FULL_SERVICE")

    institution = fetch_fk("institutions", institution_id)
    market = fetch_fk("markets", market_id)

    record = new_record(
        {
            "institution_id": institution["id"],
            "market_id": market["id"],
            "branch_name": branch_name,
            "deposits_usd": deposits_usd,
            "service_type": service_type,
            "status": "OPEN",
            "designation_application_id": None,
            "notice_sent_at": None,
            "planned_closure_date": None,
            "notice_lead_days": None,
        }
    )
    db.branches[record["id"]] = record

    aggregates.recompute_market(market)
    aggregates.recompute_institution(institution)
    aggregates.recompute_analyses_for_market(market["id"])
    return object_response(serialize(record), 201)


@branches_bp.get("/branches/<record_id>")
@require_roles(*ALL_ROLES)
def get_branch(record_id):
    return object_response(serialize(fetch("branches", record_id)))


@branches_bp.get("/branches")
@require_roles(*ALL_ROLES)
def list_branches():
    return list_and_respond(
        "branches", ("institution_id", "market_id", "designation_application_id", "status")
    )


def _satisfy_divestiture_conditions(application):
    """Cascade link 4: a clearing posture satisfies open divestiture conditions."""
    if application["competitive_posture"] not in ("CLEARED", "CLEARED_WITH_DIVESTITURE"):
        return
    decision = aggregates.application_decision(application["id"])
    if decision is None:
        return
    for condition in aggregates.decision_conditions(decision["id"]):
        if condition["condition_type"] == "DIVESTITURE" and condition["status"] == "OPEN":
            condition["_satisfied_by_cascade"] = True
            set_fields(
                condition,
                status="SATISFIED",
                satisfied_at=now_str(),
                satisfied_by_user_id="system",
            )


def _unsatisfy_divestiture_conditions(application):
    """The compensating action: a posture that stops clearing reopens them."""
    if application["competitive_posture"] in ("CLEARED", "CLEARED_WITH_DIVESTITURE"):
        return
    decision = aggregates.application_decision(application["id"])
    if decision is None:
        return
    for condition in aggregates.decision_conditions(decision["id"]):
        if (
            condition["condition_type"] == "DIVESTITURE"
            and condition["status"] == "SATISFIED"
            and condition.get("_satisfied_by_cascade")
        ):
            condition["_satisfied_by_cascade"] = False
            set_fields(
                condition, status="OPEN", satisfied_at=None, satisfied_by_user_id=None
            )


@branches_bp.post("/branches/<record_id>/designate")
@require_roles(ROLE_FILER)
def designate_branch(record_id):
    branch = fetch("branches", record_id)
    body = get_body(required=True)
    application_id = req_str(body, "application_id")
    designation_type = req_enum(body, "designation_type", DESIGNATION_TYPES)
    notice_sent_at = opt_str(body, "notice_sent_at", default=None)
    planned_closure_date = opt_str(body, "planned_closure_date", default=None)
    if notice_sent_at is not None and parse_dt(notice_sent_at) is None:
        raise ApiError("ERR_INVALID_REQUEST", "notice_sent_at must be a valid UTC timestamp")
    if planned_closure_date is not None and parse_dt(planned_closure_date) is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", "planned_closure_date must be a valid UTC timestamp"
        )

    application = fetch_fk("applications", application_id)
    ensure_application_filer(application)

    if branch["status"] != "OPEN":
        raise ApiError("ERR_INVALID_BRANCH_STATE", "only an OPEN branch can be designated")
    if branch["institution_id"] not in (application["acquirer_id"], application["target_id"]):
        raise ApiError(
            "ERR_INVALID_BRANCH_STATE",
            "the branch belongs to neither party of the application",
        )
    if application["filing_status"] in BLOCKING_APPLICATION_STATES:
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "the application is %s" % application["filing_status"],
        )

    if designation_type == "DIVESTITURE":
        set_fields(
            branch,
            status="DESIGNATED_FOR_DIVESTITURE",
            designation_application_id=application["id"],
        )
        aggregates.recompute_analyses_for_market(branch["market_id"], application["id"])
        aggregates.rollup_posture(application)
        _satisfy_divestiture_conditions(application)
        return object_response(serialize(branch))

    # CLOSURE
    if notice_sent_at is None or planned_closure_date is None:
        raise ApiError(
            "ERR_CLOSURE_NOTICE_REQUIRED",
            "a closure designation requires notice_sent_at and planned_closure_date",
        )
    notice_dt = parse_dt(notice_sent_at)
    closure_dt = parse_dt(planned_closure_date)
    lead_days = whole_days_between(notice_dt, closure_dt)
    if lead_days < calc.CLOSURE_NOTICE_MIN_DAYS:
        raise ApiError(
            "ERR_CLOSURE_NOTICE_LEAD_INSUFFICIENT",
            "customer notice lead time is %s days; %s are required"
            % (lead_days, calc.CLOSURE_NOTICE_MIN_DAYS),
        )

    candidate = dict(branch)
    candidate["notice_sent_at"] = notice_sent_at
    candidate["planned_closure_date"] = planned_closure_date
    for plan in db.conversion_plans.values():
        if plan["application_id"] != application["id"]:
            continue
        conv_start = parse_dt(plan["conversion_start_date"])
        conv_end = parse_dt(plan["conversion_end_date"])
        if conversion_conflicts_with_branch(candidate, conv_start, conv_end):
            raise ApiError(
                "ERR_CONVERSION_BLACKOUT_CONFLICT",
                "the buffered closure window intersects the systems-conversion window",
            )

    set_fields(
        branch,
        status="DESIGNATED_FOR_CLOSURE",
        designation_application_id=application["id"],
        notice_sent_at=notice_sent_at,
        planned_closure_date=planned_closure_date,
        notice_lead_days=lead_days,
    )
    aggregates.recompute_analyses_for_market(branch["market_id"], application["id"])
    aggregates.rollup_posture(application)
    return object_response(serialize(branch))


@branches_bp.post("/branches/<record_id>/rescind-designation")
@require_roles(ROLE_FILER)
def rescind_designation(record_id):
    branch = fetch("branches", record_id)
    if branch["status"] not in ("DESIGNATED_FOR_DIVESTITURE", "DESIGNATED_FOR_CLOSURE"):
        raise ApiError(
            "ERR_INVALID_BRANCH_STATE", "the branch carries no rescindable designation"
        )
    application = db.applications.get(branch.get("designation_application_id"))
    if application is None:
        raise ApiError("ERR_APPLICATION_NOT_FOUND", "the designating application is unknown")
    ensure_application_filer(application)
    if application["filing_status"] in BLOCKING_APPLICATION_STATES:
        raise ApiError(
            "ERR_INVALID_APPLICATION_STATE",
            "the application is %s" % application["filing_status"],
        )

    was_divestiture = branch["status"] == "DESIGNATED_FOR_DIVESTITURE"
    market_id = branch["market_id"]
    set_fields(
        branch,
        status="OPEN",
        designation_application_id=None,
        notice_sent_at=None,
        planned_closure_date=None,
        notice_lead_days=None,
    )
    aggregates.recompute_analyses_for_market(market_id, application["id"])
    aggregates.rollup_posture(application)
    if was_divestiture:
        _unsatisfy_divestiture_conditions(application)
    return object_response(serialize(branch))
