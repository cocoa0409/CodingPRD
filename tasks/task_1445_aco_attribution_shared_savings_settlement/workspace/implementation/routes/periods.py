"""Agreement periods: create, fetch, open, lock-assignment, expenditure summary."""
from flask import Blueprint

import db
from errors import (ApiError, ERR_PERIOD_NOT_OPEN, ERR_PERIOD_OVERLAP)
from middleware import (require_roles, ROLE_ACO_ADMIN, ROLE_ACTUARY,
                        ALL_DOMAIN_ROLES)
from response import success, list_success
from serializers import period_out
from services import calc
from validate import get_json_body, validate_body

bp = Blueprint("periods", __name__)

PERIOD_SPEC = {
    "aco_tax_id": {"type": "string", "required": True},
    "aco_name": {"type": "string", "required": True},
    "performance_start_date": {"type": "date", "required": True},
    "performance_end_date": {"type": "date", "required": True},
    "track": {"type": "enum", "enum": ["ONE_SIDED", "TWO_SIDED"], "required": True},
}


def get_period_or_404(period_id):
    period = db.periods.get(period_id)
    if period is None:
        from errors import not_found
        raise not_found("Agreement period not found")
    return period


@bp.post("/aco/agreement-periods")
def create_period():
    require_roles([ROLE_ACO_ADMIN])
    body = validate_body(get_json_body(), PERIOD_SPEC)
    if body["performance_end_date"] < body["performance_start_date"]:
        from errors import bad_request
        raise bad_request("performance_end_date must be >= performance_start_date")
    # Closed-interval overlap: new.start <= existing.end AND existing.start <=
    # new.end conflicts; mere adjacency (shared boundary date) conflicts too.
    for existing in db.periods.values():
        if existing["aco_tax_id"] != body["aco_tax_id"]:
            continue
        if (body["performance_start_date"] <= existing["performance_end_date"]
                and existing["performance_start_date"] <= body["performance_end_date"]):
            raise ApiError(
                ERR_PERIOD_OVERLAP, 409,
                "Period span overlaps an existing period for this aco_tax_id")
    period = db.stamp_new({
        "id": db.new_id(),
        "aco_tax_id": body["aco_tax_id"],
        "aco_name": body["aco_name"],
        "performance_start_date": body["performance_start_date"],
        "performance_end_date": body["performance_end_date"],
        "track": body["track"],
        "status": "SETUP",
    })
    db.periods[period["id"]] = period
    return success(period_out(period), 201)


@bp.get("/aco/agreement-periods/<period_id>")
def get_period(period_id):
    require_roles(ALL_DOMAIN_ROLES)
    return success(period_out(get_period_or_404(period_id)))


@bp.post("/aco/agreement-periods/<period_id>/open")
def open_period(period_id):
    require_roles([ROLE_ACO_ADMIN])
    get_json_body()  # tolerate an optional empty JSON body
    period = get_period_or_404(period_id)
    if period["status"] != "SETUP":
        raise ApiError(ERR_PERIOD_NOT_OPEN, 409,
                       "Open requires the period to be in SETUP")
    period["status"] = "OPEN"
    db.bump(period)
    return success(period_out(period))


@bp.post("/aco/agreement-periods/<period_id>/lock-assignment")
def lock_assignment(period_id):
    require_roles([ROLE_ACO_ADMIN])
    get_json_body()
    period = get_period_or_404(period_id)
    if period["status"] != "OPEN":
        raise ApiError(ERR_PERIOD_NOT_OPEN, 409,
                       "Lock-assignment requires the period to be OPEN")
    # Cascade: every PROVISIONAL AttributionRecord of the period -> FINAL.
    for rec in db.attribution_records.values():
        if rec["agreement_period_id"] == period_id and rec["status"] == "PROVISIONAL":
            rec["status"] = "FINAL"
            db.bump(rec)
    # Cascade: every COMPLETED AlignmentRun of the period -> LOCKED.
    for run in db.alignment_runs.values():
        if run["agreement_period_id"] == period_id and run["status"] == "COMPLETED":
            run["status"] = "LOCKED"
            db.bump(run)
    period["status"] = "ASSIGNMENT_LOCKED"
    db.bump(period)
    return success(period_out(period))


@bp.get("/aco/agreement-periods/<period_id>/expenditure-summary")
def expenditure_summary(period_id):
    require_roles([ROLE_ACO_ADMIN, ROLE_ACTUARY])
    period = get_period_or_404(period_id)
    return success(calc.expenditure_summary(period["id"]))
