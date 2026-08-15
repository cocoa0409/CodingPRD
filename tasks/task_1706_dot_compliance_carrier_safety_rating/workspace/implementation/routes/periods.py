"""RandomTestingPeriod endpoints (PRD 3.6): open annual period, close with verdict."""
from datetime import datetime, timezone

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_DUPLICATE_TESTING_PERIOD, ERR_PERIOD_NOT_OPEN,
    ERR_PERIOD_NOT_ENDED,
)
from middleware import authorized
from response import success_object
from routes.helpers import public, list_response, get_one
from services import calc
from services.core import stamp_new, touch
from validate import (
    get_body, req_str, req_int, require_path_resource, require_ref,
)
from util import new_id, CLOCK

bp = Blueprint("periods", __name__)

ROLE = ["SafetyManager"]


def period_public(rec):
    out = public(rec)
    drug, alcohol = calc.completed_counts(rec)
    out["completed_drug_tests"] = drug
    out["completed_alcohol_tests"] = alcohol
    return out


@bp.post("/safety/random-testing-periods")
def create_period():
    authorized(ROLE)
    body = get_body()
    carrier_id = req_str(body, "carrier_id")
    program_year = req_int(body, "program_year")
    avg_driver_count = req_int(body, "avg_driver_count", minimum=1)
    require_ref("carriers", carrier_id, "carrier_id")
    for p in db["random_testing_periods"].values():
        if p["carrier_id"] == carrier_id and p["program_year"] == program_year:
            raise_error(ERR_DUPLICATE_TESTING_PERIOD,
                        "a testing period already exists for this carrier and year")
    period = stamp_new({
        "id": new_id(),
        "carrier_id": carrier_id,
        "program_year": program_year,
        "avg_driver_count": avg_driver_count,
        "required_drug_tests": calc.required_drug_tests(avg_driver_count),
        "required_alcohol_tests": calc.required_alcohol_tests(avg_driver_count),
        "status": "OPEN",
    })
    db["random_testing_periods"][period["id"]] = period
    return success_object(period_public(period), 201)


@bp.get("/safety/random-testing-periods")
def list_periods():
    return list_response("random_testing_periods", filters={
        "carrier_id": request.args.get("carrier_id"),
        "status": request.args.get("status"),
    }, serializer=period_public)


@bp.get("/safety/random-testing-periods/<rid>")
def get_period(rid):
    return get_one("random_testing_periods", rid, serializer=period_public)


@bp.post("/safety/random-testing-periods/<rid>/close")
def close_period(rid):
    authorized(ROLE)
    period = require_path_resource("random_testing_periods", rid)
    if period["status"] != "OPEN":
        raise_error(ERR_PERIOD_NOT_OPEN, "close requires an OPEN period")
    year_end = datetime(period["program_year"] + 1, 1, 1, tzinfo=timezone.utc)
    if CLOCK.now() < year_end:
        raise_error(ERR_PERIOD_NOT_ENDED, "the program year has not ended")
    drug, alcohol = calc.completed_counts(period)
    if drug >= period["required_drug_tests"] and alcohol >= period["required_alcohol_tests"]:
        period["status"] = "CLOSED_COMPLIANT"
    else:
        period["status"] = "CLOSED_DEFICIENT"
    touch(period)
    return success_object(period_public(period))
